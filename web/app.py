from flask import Flask, render_template, request, jsonify, Response
import asyncio
import json
from datetime import datetime
import uuid
from typing import Dict, Any
import threading
from queue import Queue

# Import agent components
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_graph import agent
from agent.state import LLMProvider
from agent.config import config
from agent.llm_router import llm_router

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Store active sessions
active_sessions: Dict[str, Dict[str, Any]] = {}

class SessionManager:
    """Manages agent sessions for the web interface."""

    def __init__(self):
        self.sessions = {}

    def create_session(self, session_id: str = None) -> str:
        """Create a new agent session."""
        if not session_id:
            session_id = str(uuid.uuid4())

        self.sessions[session_id] = {
            'id': session_id,
            'created_at': datetime.now().isoformat(),
            'messages': [],
            'status': 'idle',
            'current_llm': LLMProvider.GEMINI,
            'agent_state': None
        }

        return session_id

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session data."""
        return self.sessions.get(session_id, {})

    def update_session(self, session_id: str, updates: Dict[str, Any]):
        """Update session data."""
        if session_id in self.sessions:
            self.sessions[session_id].update(updates)

    def add_message(self, session_id: str, role: str, content: str):
        """Add a message to the session."""
        if session_id in self.sessions:
            message = {
                'role': role,
                'content': content,
                'timestamp': datetime.now().isoformat()
            }
            self.sessions[session_id]['messages'].append(message)

    def cleanup_session(self, session_id: str):
        """Clean up a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]

session_manager = SessionManager()

@app.route('/')
def index():
    """Main chat interface."""
    # Get available LLM providers
    try:
        available_providers = llm_router.get_available_providers()
        providers = [{'value': p.value, 'name': p.value.title()} for p in available_providers]
    except Exception as e:
        print(f"Error getting providers: {e}")
        providers = [{'value': 'gemini', 'name': 'Gemini'}]

    # Create a new session
    session_id = session_manager.create_session()

    return render_template('chat.html', 
                         session_id=session_id,
                         providers=providers,
                         default_provider=config.DEFAULT_LLM_PROVIDER)

@app.route('/api/config')
def get_config():
    """Get configuration information."""
    try:
        available_providers = llm_router.get_available_providers()
        api_key_status = config.validate_api_keys()

        return jsonify({
            'success': True,
            'available_providers': [p.value for p in available_providers],
            'api_key_status': api_key_status,
            'mcp_server_url': config.MCP_SERVER_BASE_URL,
            'default_provider': config.DEFAULT_LLM_PROVIDER
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat messages."""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        message = data.get('message', '').strip()
        selected_llm = data.get('llm_provider', config.DEFAULT_LLM_PROVIDER)

        if not message:
            return jsonify({'success': False, 'error': 'Message is required'}), 400

        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID is required'}), 400

        # Validate LLM provider
        try:
            llm_provider = LLMProvider(selected_llm.lower())
        except ValueError:
            return jsonify({'success': False, 'error': f'Invalid LLM provider: {selected_llm}'}), 400

        # Check if provider is available
        available_providers = llm_router.get_available_providers()
        if llm_provider not in available_providers:
            return jsonify({
                'success': False, 
                'error': f'LLM provider {selected_llm} is not configured'
            }), 400

        # Get or create session
        session = session_manager.get_session(session_id)
        if not session:
            session_id = session_manager.create_session(session_id)
            session = session_manager.get_session(session_id)

        # Add user message to session
        session_manager.add_message(session_id, 'user', message)
        session_manager.update_session(session_id, {
            'status': 'processing',
            'current_llm': llm_provider
        })

        # Start agent execution in background
        def run_agent():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                # Run the agent
                final_state = loop.run_until_complete(
                    agent.run(
                        user_goal=message,
                        user_message=message,
                        selected_llm=llm_provider
                    )
                )

                # Update session with results
                session_manager.update_session(session_id, {
                    'status': 'completed',
                    'agent_state': final_state
                })

                # Add agent response to session
                response = "I completed the task but couldn't generate a response."

                # Safely extract final_response from the state
                try:
                    if hasattr(final_state, 'final_response') and final_state.final_response:
                        response = final_state.final_response
                    elif isinstance(final_state, dict) and 'final_response' in final_state:
                        response = final_state['final_response']
                    elif isinstance(final_state, dict):
                        # Try to find the response in various possible keys
                        for key in ['final_response', 'response', 'content', 'output']:
                            if key in final_state and final_state[key]:
                                response = final_state[key]
                                break
                except Exception as e:
                    print(f"[DEBUG_LOG] Error extracting response: {str(e)}")
                    response = f"Task completed but response extraction failed: {str(e)}"

                session_manager.add_message(session_id, 'assistant', response)

            except Exception as e:
                error_msg = f"Agent execution failed: {str(e)}"
                session_manager.update_session(session_id, {
                    'status': 'error',
                    'error': error_msg
                })
                session_manager.add_message(session_id, 'assistant', f"Sorry, I encountered an error: {error_msg}")

            finally:
                loop.close()

        # Start agent in background thread
        thread = threading.Thread(target=run_agent)
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Processing started'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/session/<session_id>')
def get_session(session_id):
    """Get session information."""
    try:
        session = session_manager.get_session(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404

        # Prepare response data
        response_data = {
            'success': True,
            'session': {
                'id': session['id'],
                'status': session['status'],
                'messages': session['messages'],
                'current_llm': session['current_llm'].value if hasattr(session['current_llm'], 'value') else session['current_llm']
            }
        }

        # Add agent state information if available
        if session.get('agent_state'):
            agent_state = session['agent_state']
            response_data['session']['agent_info'] = {
                'is_complete': agent_state.is_complete,
                'iteration_count': agent_state.iteration_count,
                'tools_used': len(agent_state.tool_calls),
                'errors': len(agent_state.errors),
                'execution_steps': len(agent_state.execution_steps),
                'completed_steps': len(agent_state.completed_steps)
            }

        # Add error if present
        if session.get('error'):
            response_data['session']['error'] = session['error']

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/session/<session_id>/stream')
def stream_session(session_id):
    """Stream session updates using Server-Sent Events."""
    def generate():
        # Get the current message count at the start to avoid re-sending existing messages
        session = session_manager.get_session(session_id)
        if not session:
            print(f"[DEBUG_LOG] Session {session_id} not found, ending stream")
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        # Start from current message count to only send NEW messages
        last_message_count = len(session['messages'])
        last_status = None
        status_sent = False
        completion_sent = False  # Additional flag to prevent duplicate completion events

        print(f"[DEBUG_LOG] Starting stream for session {session_id}, starting from message {last_message_count}")

        while True:
            try:
                session = session_manager.get_session(session_id)
                if not session:
                    print(f"[DEBUG_LOG] Session {session_id} not found, ending stream")
                    yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
                    break

                # Check for new messages
                current_message_count = len(session['messages'])
                if current_message_count > last_message_count:
                    # Send only truly new messages
                    new_messages = session['messages'][last_message_count:]
                    for message in new_messages:
                        print(f"[DEBUG_LOG] Sending message: {message.get('role', 'unknown')}")
                        yield f"data: {json.dumps({'type': 'message', 'data': message})}\n\n"
                    last_message_count = current_message_count

                # Only send status updates when status changes or when completed/error (and not already sent)
                current_status = session['status']
                should_send_status = (
                    current_status != last_status or 
                    (current_status in ['completed', 'error'] and not status_sent)
                )

                if should_send_status and not (current_status == 'completed' and completion_sent):
                    print(f"[DEBUG_LOG] Sending status update: {current_status}")

                    status_data = {
                        'type': 'status',
                        'data': {
                            'status': current_status,
                            'current_llm': session['current_llm'].value if hasattr(session['current_llm'], 'value') else session['current_llm']
                        }
                    }

                    # Add agent info if available and status is completed
                    if current_status == 'completed' and session.get('agent_state'):
                        agent_state = session['agent_state']
                        status_data['data']['agent_info'] = {
                            'is_complete': agent_state.is_complete,
                            'iteration_count': agent_state.iteration_count,
                            'tools_used': len(agent_state.tool_calls),
                            'errors': len(agent_state.errors)
                        }

                    yield f"data: {json.dumps(status_data)}\n\n"
                    last_status = current_status

                    if current_status in ['completed', 'error']:
                        status_sent = True
                        if current_status == 'completed':
                            completion_sent = True

                # Break if session is completed or has error and we've sent the status
                if session['status'] in ['completed', 'error'] and status_sent:
                    print(f"[DEBUG_LOG] Session {session_id} finished with status {session['status']}, ending stream")
                    break

                # Wait before next check
                import time
                time.sleep(1)

            except Exception as e:
                print(f"[DEBUG_LOG] Stream error for session {session_id}: {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/session/<session_id>/clear', methods=['POST'])
def clear_session(session_id):
    """Clear session messages."""
    try:
        session = session_manager.get_session(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404

        # Reset session
        session_manager.update_session(session_id, {
            'messages': [],
            'status': 'idle',
            'agent_state': None,
            'error': None
        })

        return jsonify({'success': True, 'message': 'Session cleared'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tools')
def get_tools():
    """Get available tools from MCP server."""
    try:
        from agent.tools import tool_executor

        # Initialize tool executor if not already done
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Test MCP server connection first
            connection_result = loop.run_until_complete(test_mcp_connection())

            if not connection_result['success']:
                return jsonify({
                    'success': False,
                    'error': f"MCP server connection failed: {connection_result['error']}",
                    'connection_details': connection_result,
                    'tools': [],
                    'count': 0
                })

            # Initialize and get tools
            loop.run_until_complete(tool_executor.initialize())
            tools = tool_executor.get_available_tools()

            if not tools:
                return jsonify({
                    'success': False,
                    'error': "No tools are currently available from the MCP server",
                    'connection_details': connection_result,
                    'tools': [],
                    'count': 0
                })

            tools_data = []
            for tool in tools:
                tools_data.append({
                    'name': tool.name,
                    'description': tool.description,
                    'endpoint': tool.endpoint,
                    'input_schema': tool.input_schema
                })

            return jsonify({
                'success': True,
                'tools': tools_data,
                'count': len(tools_data),
                'connection_details': connection_result
            })

        finally:
            loop.close()

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'tools': [],
            'count': 0
        })

async def test_mcp_connection():
    """Test MCP server connection and return detailed status."""
    try:
        from agent.tools import MCPToolClient
        import httpx

        client = MCPToolClient()

        # Test basic connectivity first
        try:
            async with httpx.AsyncClient(timeout=5) as http_client:
                response = await http_client.get(f"{config.MCP_SERVER_BASE_URL}/health")
                if response.status_code == 200:
                    health_status = "healthy"
                else:
                    health_status = f"unhealthy (HTTP {response.status_code})"
        except Exception:
            health_status = "unreachable"

        # Test tool discovery
        try:
            tools = await client.discover_tools()
            return {
                'success': True,
                'server_url': config.MCP_SERVER_BASE_URL,
                'health_status': health_status,
                'tools_count': len(tools),
                'message': f"Successfully connected to MCP server and discovered {len(tools)} tools"
            }
        except Exception as e:
            return {
                'success': False,
                'server_url': config.MCP_SERVER_BASE_URL,
                'health_status': health_status,
                'tools_count': 0,
                'error': str(e),
                'message': f"Failed to discover tools from MCP server: {str(e)}"
            }

    except Exception as e:
        return {
            'success': False,
            'server_url': config.MCP_SERVER_BASE_URL,
            'health_status': 'error',
            'tools_count': 0,
            'error': str(e),
            'message': f"MCP connection test failed: {str(e)}"
        }

@app.route('/mcp/message', methods=['POST'])
def mcp_message():
    """Handle MCP JSON-RPC 2.0 requests."""
    try:
        # Get JSON-RPC request from body
        request_data = request.get_json()

        if not request_data:
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            }), 400

        # Validate JSON-RPC format
        if request_data.get("jsonrpc") != "2.0":
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_data.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request"
                }
            }), 400

        method = request_data.get("method")
        params = request_data.get("params", {})
        request_id = request_data.get("id")

        # Handle different MCP methods
        if method == "initialize":
            # Return server capabilities
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "book-service-mcp-client",
                        "version": "1.0.0"
                    }
                }
            })

        elif method == "tools/list":
            # Use the existing tool discovery functionality
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                from agent.tools import MCPToolClient
                client = MCPToolClient(mode="http")  # Force HTTP mode for web endpoint
                tools = loop.run_until_complete(client.discover_tools())

                tools_list = []
                for tool in tools:
                    tools_list.append({
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema
                    })

                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": tools_list
                    }
                })
            finally:
                loop.close()

        elif method == "tools/call":
            # Handle tool calls
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not tool_name:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params: missing tool name"
                    }
                }), 400

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                from agent.tools import MCPToolClient
                client = MCPToolClient(mode="http")  # Force HTTP mode for web endpoint
                tools = loop.run_until_complete(client.discover_tools())

                # Find the requested tool
                target_tool = None
                for tool in tools:
                    if tool.name == tool_name:
                        target_tool = tool
                        break

                if not target_tool:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": "Tool not found",
                            "message": f"Unknown tool: {tool_name}"
                        }
                    }), 400

                # Call the tool
                result = loop.run_until_complete(client.call_tool(target_tool, arguments))

                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result) if isinstance(result, dict) else str(result)
                            }
                        ]
                    }
                })
            finally:
                loop.close()

        else:
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }), 400

    except Exception as e:
        return jsonify({
            "jsonrpc": "2.0",
            "id": request_data.get("id") if 'request_data' in locals() else None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("🚀 Starting Autonomous Agent Web Interface...")
    print(f"🔗 Server will be available at: http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    print(f"🧠 Default LLM: {config.DEFAULT_LLM_PROVIDER}")

    # Check configuration
    try:
        available_providers = llm_router.get_available_providers()
        print(f"✅ Available LLM providers: {', '.join([p.value for p in available_providers])}")
    except Exception as e:
        print(f"⚠️  Warning: Error checking LLM providers: {e}")

    print("-" * 50)

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        threaded=True
    )
