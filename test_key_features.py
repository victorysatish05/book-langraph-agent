#!/usr/bin/env python3
"""
Comprehensive test file for key features of the book-langraph-agent.
This test covers:
1. MCP server connection and tool discovery
2. Tool execution functionality
3. Agent functionality with various scenarios
4. Web interface endpoints
5. Basic health checks
"""

import asyncio
import sys
import os
import httpx
import json
import time

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agent.tools import tool_executor, MCPToolClient
from agent.config import config
from agent.agent_graph import AutonomousAgent
from agent.state import LLMProvider
from web.app import app, session_manager

class TestResults:
    """Track test results."""
    def __init__(self):
        self.results = []
    
    def add_result(self, test_name, success, message=""):
        self.results.append({
            'test': test_name,
            'success': success,
            'message': message
        })
        status = "✅" if success else "❌"
        print(f"{status} {test_name}: {message}")
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for r in self.results if r['success'])
        total = len(self.results)
        
        for result in self.results:
            status = "✅ PASS" if result['success'] else "❌ FAIL"
            print(f"{status}: {result['test']}")
            if result['message'] and not result['success']:
                print(f"    Error: {result['message']}")
        
        print(f"\nOverall: {passed}/{total} tests passed")
        return passed == total

# Test Results Tracker
test_results = TestResults()

async def test_mcp_connection():
    """Test MCP server connection and tool discovery."""
    print("\n" + "-" * 60)
    print("1. TESTING MCP CONNECTION AND TOOL DISCOVERY")
    print("-" * 60)
    
    try:
        # Test basic MCP client connection
        client = MCPToolClient()
        tools = await client.discover_tools()
        
        if tools:
            test_results.add_result(
                "MCP Tool Discovery", 
                True, 
                f"Discovered {len(tools)} tools"
            )
            
            # List discovered tools
            print("   Available tools:")
            for tool in tools[:5]:  # Show first 5 tools
                print(f"     - {tool.name}: {tool.description}")
            if len(tools) > 5:
                print(f"     ... and {len(tools) - 5} more tools")
        else:
            test_results.add_result(
                "MCP Tool Discovery", 
                False, 
                "No tools discovered"
            )
            
    except Exception as e:
        test_results.add_result(
            "MCP Tool Discovery", 
            False, 
            str(e)
        )

async def test_tool_execution():
    """Test tool execution functionality."""
    print("\n" + "-" * 60)
    print("2. TESTING TOOL EXECUTION")
    print("-" * 60)
    
    try:
        # Initialize tool executor
        await tool_executor.initialize()
        available_tools = tool_executor.get_available_tools()
        
        if available_tools:
            test_results.add_result(
                "Tool Executor Initialization", 
                True, 
                f"Initialized with {len(available_tools)} tools"
            )
            
            # Test a simple tool call (get_all_books if available)
            get_all_books_tool = None
            for tool in available_tools:
                if tool.name == "get_all_books":
                    get_all_books_tool = tool
                    break
            
            if get_all_books_tool:
                try:
                    result = await tool_executor.execute_tool("get_all_books", {})
                    test_results.add_result(
                        "Tool Execution (get_all_books)", 
                        True, 
                        f"Successfully executed, result type: {type(result)}"
                    )
                except Exception as e:
                    test_results.add_result(
                        "Tool Execution (get_all_books)", 
                        False, 
                        str(e)
                    )
            else:
                test_results.add_result(
                    "Tool Execution (get_all_books)", 
                    False, 
                    "get_all_books tool not found"
                )
        else:
            test_results.add_result(
                "Tool Executor Initialization", 
                False, 
                "No tools available"
            )
            
    except Exception as e:
        test_results.add_result(
            "Tool Executor Initialization", 
            False, 
            str(e)
        )

async def test_agent_functionality():
    """Test agent functionality with various scenarios."""
    print("\n" + "-" * 60)
    print("3. TESTING AGENT FUNCTIONALITY")
    print("-" * 60)
    
    # Test scenarios
    scenarios = [
        ("Book Query", "What books are available?"),
        ("Simple Math", "What is 5 + 3?"),
        ("Book Count", "How many books are there?"),
    ]
    
    for description, user_goal in scenarios:
        try:
            print(f"   Testing: {description}")
            agent = AutonomousAgent()
            result = await agent.run(
                user_goal=user_goal,
                selected_llm=LLMProvider.GEMINI
            )
            
            success = result.is_complete and len(result.errors) == 0
            message = f"Complete: {result.is_complete}, Tools used: {len(result.tool_calls)}, Errors: {len(result.errors)}"
            
            test_results.add_result(
                f"Agent Scenario ({description})", 
                success, 
                message
            )
            
        except Exception as e:
            test_results.add_result(
                f"Agent Scenario ({description})", 
                False, 
                str(e)
            )

async def test_web_endpoints():
    """Test web interface endpoints."""
    print("\n" + "-" * 60)
    print("4. TESTING WEB ENDPOINTS")
    print("-" * 60)
    
    # Test basic endpoints
    endpoints_to_test = [
        ('http://127.0.0.1:5000/', 'Web Root'),
        ('http://127.0.0.1:5000/api/tools', 'API Tools'),
        ('http://127.0.0.1:8080/health', 'MCP Health'),
    ]
    
    async with httpx.AsyncClient(timeout=5) as client:
        for url, name in endpoints_to_test:
            try:
                response = await client.get(url)
                success = response.status_code == 200
                message = f"Status: {response.status_code}"
                
                test_results.add_result(
                    f"Endpoint ({name})", 
                    success, 
                    message
                )
                
            except Exception as e:
                test_results.add_result(
                    f"Endpoint ({name})", 
                    False, 
                    str(e)
                )

def test_web_chat_interface():
    """Test web chat interface."""
    print("\n" + "-" * 60)
    print("5. TESTING WEB CHAT INTERFACE")
    print("-" * 60)
    
    try:
        with app.test_client() as client:
            # Test chat endpoint
            session_id = "test_session_key_features"
            
            response = client.post('/api/chat', 
                                 json={
                                     'session_id': session_id,
                                     'message': 'Hello, test message',
                                     'llm_provider': 'gemini'
                                 },
                                 content_type='application/json')
            
            success = response.status_code == 200
            message = f"Status: {response.status_code}"
            
            test_results.add_result(
                "Web Chat Interface", 
                success, 
                message
            )
            
            # Test session endpoint
            session_response = client.get(f'/api/session/{session_id}')
            success = session_response.status_code == 200
            message = f"Status: {session_response.status_code}"
            
            test_results.add_result(
                "Session Management", 
                success, 
                message
            )
            
    except Exception as e:
        test_results.add_result(
            "Web Chat Interface", 
            False, 
            str(e)
        )

async def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("COMPREHENSIVE KEY FEATURES TEST")
    print("=" * 60)
    print(f"MCP Server URL: {config.MCP_SERVER_BASE_URL}")
    print(f"Flask Port: {config.FLASK_PORT}")
    
    # Run async tests
    await test_mcp_connection()
    await test_tool_execution()
    await test_agent_functionality()
    await test_web_endpoints()
    
    # Run sync tests
    test_web_chat_interface()
    
    # Print final summary
    all_passed = test_results.print_summary()
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED! Key features are working correctly.")
    else:
        print("\n⚠️  SOME TESTS FAILED. Check the details above.")
        print("\n💡 Common issues:")
        print("   - MCP server not running on port 8080")
        print("   - Flask app not running on port 5000")
        print("   - Missing API keys in .env file")
    
    return all_passed

if __name__ == "__main__":
    asyncio.run(run_all_tests())