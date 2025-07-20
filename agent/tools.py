import asyncio
import json
from typing import Dict, Any, List, Optional, AsyncGenerator
import httpx
import subprocess
import sys
from datetime import datetime

from .config import config
from .state import ToolMetadata, ToolCall

class MCPToolClient:
    """Client for interacting with MCP (Model Context Protocol) server tools."""

    def __init__(self, base_url: str = None, mode: str = None):
        self.mode = mode or config.MCP_SERVER_MODE
        self.base_url = base_url or config.MCP_SERVER_BASE_URL
        self.tools_endpoint = config.MCP_TOOLS_URL
        self.timeout = config.TOOL_TIMEOUT
        self.mcp_command = config.MCP_SERVER_COMMAND
        self._cached_tools: Optional[List[ToolMetadata]] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = 300  # 5 minutes cache TTL
        self._request_id = 1  # For JSON-RPC request IDs

    async def _send_jsonrpc_stdio(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send JSON-RPC request via stdin/stdout to MCP server."""
        try:
            # Start the MCP server process
            process = await asyncio.create_subprocess_shell(
                self.mcp_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Send the JSON-RPC request
            request_json = json.dumps(payload) + '\n'
            stdout, stderr = await process.communicate(request_json.encode())

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Process failed"
                raise Exception(f"MCP server process failed: {error_msg}")

            # Parse the response
            response_text = stdout.decode().strip()
            if not response_text:
                raise Exception("Empty response from MCP server")

            response_data = json.loads(response_text)
            return response_data

        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response from MCP server: {str(e)}")
        except Exception as e:
            raise Exception(f"Error communicating with MCP server via stdio: {str(e)}")

    async def _send_jsonrpc_http(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send JSON-RPC request via HTTP to MCP server."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    config.MCP_SERVER_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                return response.json()
        except httpx.RequestError as e:
            raise Exception(f"Failed to connect to MCP server: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise Exception(f"MCP server returned error {e.response.status_code}: {e.response.text}")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response from MCP server: {str(e)}")

    async def _send_jsonrpc(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send JSON-RPC request using the configured communication method."""
        if self.mode == "stdio":
            return await self._send_jsonrpc_stdio(payload)
        else:  # default to http
            return await self._send_jsonrpc_http(payload)

    async def discover_tools(self, force_refresh: bool = False) -> List[ToolMetadata]:
        """Discover available tools from the MCP server using JSON-RPC protocol."""
        # Check cache first
        if not force_refresh and self._is_cache_valid():
            return self._cached_tools

        try:
            # First initialize the MCP server
            init_payload = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "initialize",
                "params": {}
            }
            self._request_id += 1

            init_response = await self._send_jsonrpc(init_payload)

            # Check for JSON-RPC error
            if "error" in init_response:
                raise Exception(f"MCP server initialization error: {init_response['error']['message']}")

            # Then get the tools list
            tools_payload = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/list",
                "params": {}
            }
            self._request_id += 1

            response_data = await self._send_jsonrpc(tools_payload)

            # Check for JSON-RPC error
            if "error" in response_data:
                raise Exception(f"MCP server error: {response_data['error']['message']}")

            tools_list = response_data.get("result", {}).get("tools", [])
            tools = []

            for tool_data in tools_list:
                tool = ToolMetadata(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    endpoint="",  # Not used in JSON-RPC protocol
                    input_schema=tool_data.get("inputSchema", {})
                )
                tools.append(tool)

            # Add missing tools that are expected by the application but not provided by MCP server
            existing_tool_names = {tool.name for tool in tools}

            # Define additional tools that should be available
            additional_tools = [
                {
                    "name": "get_all_books",
                    "description": "Get all books in the library (alias for list_books)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "get_book_by_id",
                    "description": "Get a book by its ID (alias for get_book_details)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "integer",
                                "description": "The ID of the book"
                            }
                        },
                        "required": ["id"]
                    }
                },
                {
                    "name": "create_book",
                    "description": "Create a new book in the library (alias for add_book)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Book title"
                            },
                            "author": {
                                "type": "string",
                                "description": "Book author"
                            },
                            "genre": {
                                "type": "string",
                                "description": "Book genre"
                            },
                            "isbn": {
                                "type": "string",
                                "description": "ISBN number"
                            },
                            "year": {
                                "type": "integer",
                                "description": "Publication year"
                            }
                        },
                        "required": ["title", "author"]
                    }
                },
                {
                    "name": "update_book",
                    "description": "Update an existing book's information",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "book_id": {
                                "type": "integer",
                                "description": "The ID of the book to update"
                            },
                            "title": {
                                "type": "string",
                                "description": "Updated book title"
                            },
                            "author": {
                                "type": "string",
                                "description": "Updated book author"
                            },
                            "genre": {
                                "type": "string",
                                "description": "Updated book genre"
                            },
                            "isbn": {
                                "type": "string",
                                "description": "Updated ISBN number"
                            },
                            "year": {
                                "type": "integer",
                                "description": "Updated publication year"
                            }
                        },
                        "required": ["book_id"]
                    }
                },
                {
                    "name": "delete_book",
                    "description": "Delete a book from the library",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "book_id": {
                                "type": "integer",
                                "description": "The ID of the book to delete"
                            }
                        },
                        "required": ["book_id"]
                    }
                },
                {
                    "name": "get_book_count",
                    "description": "Get the total number of books in the library",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "add_author",
                    "description": "Add a new author to the system",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Author's full name"
                            },
                            "bio": {
                                "type": "string",
                                "description": "Author's biography (optional)"
                            },
                            "birth_year": {
                                "type": "integer",
                                "description": "Author's birth year (optional)"
                            },
                            "nationality": {
                                "type": "string",
                                "description": "Author's nationality (optional)"
                            }
                        },
                        "required": ["name"]
                    }
                },
                {
                    "name": "get_authors",
                    "description": "Get all authors in the system",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "get_author_by_name",
                    "description": "Get author details by name",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Author's name to search for"
                            }
                        },
                        "required": ["name"]
                    }
                },
                {
                    "name": "update_author",
                    "description": "Update an existing author's information",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Current author's name"
                            },
                            "new_name": {
                                "type": "string",
                                "description": "New author's name (optional)"
                            },
                            "bio": {
                                "type": "string",
                                "description": "Updated biography (optional)"
                            },
                            "birth_year": {
                                "type": "integer",
                                "description": "Updated birth year (optional)"
                            },
                            "nationality": {
                                "type": "string",
                                "description": "Updated nationality (optional)"
                            }
                        },
                        "required": ["name"]
                    }
                },
                {
                    "name": "delete_author",
                    "description": "Delete an author from the system",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Author's name to delete"
                            }
                        },
                        "required": ["name"]
                    }
                }
            ]

            # Add additional tools that don't already exist
            for additional_tool in additional_tools:
                if additional_tool["name"] not in existing_tool_names:
                    tool = ToolMetadata(
                        name=additional_tool["name"],
                        description=additional_tool["description"],
                        endpoint="",  # Not used in JSON-RPC protocol
                        input_schema=additional_tool["inputSchema"]
                    )
                    tools.append(tool)

            # Update cache
            self._cached_tools = tools
            self._cache_timestamp = datetime.now()

            return tools

        except Exception as e:
            raise Exception(f"Error discovering tools: {str(e)}")

    def _is_cache_valid(self) -> bool:
        """Check if the cached tools are still valid."""
        if not self._cached_tools or not self._cache_timestamp:
            return False

        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self._cache_ttl

    async def _handle_author_tool(self, tool_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle author management tools locally since MCP server doesn't support them."""
        # Simple in-memory storage for demonstration (in a real system, this would use a database)
        if not hasattr(self, '_authors_storage'):
            self._authors_storage = []

        try:
            if tool_name == "add_author":
                name = input_data.get("name")
                if not name:
                    return {"error": "Author name is required"}

                # Check if author already exists
                existing_author = next((author for author in self._authors_storage if author["name"] == name), None)
                if existing_author:
                    return {"error": f"Author '{name}' already exists"}

                # Add new author
                new_author = {
                    "name": name,
                    "bio": input_data.get("bio", ""),
                    "birth_year": input_data.get("birth_year"),
                    "nationality": input_data.get("nationality", ""),
                    "created_at": datetime.now().isoformat()
                }
                self._authors_storage.append(new_author)

                return {
                    "success": True,
                    "message": f"Author '{name}' has been successfully added to the system",
                    "author": new_author
                }

            elif tool_name == "get_authors":
                return {
                    "success": True,
                    "authors": self._authors_storage,
                    "count": len(self._authors_storage)
                }

            elif tool_name == "get_author_by_name":
                name = input_data.get("name")
                if not name:
                    return {"error": "Author name is required"}

                author = next((author for author in self._authors_storage if author["name"] == name), None)
                if author:
                    return {"success": True, "author": author}
                else:
                    return {"error": f"Author '{name}' not found"}

            elif tool_name == "update_author":
                name = input_data.get("name")
                if not name:
                    return {"error": "Author name is required"}

                author = next((author for author in self._authors_storage if author["name"] == name), None)
                if not author:
                    return {"error": f"Author '{name}' not found"}

                # Update author fields
                if "new_name" in input_data:
                    author["name"] = input_data["new_name"]
                if "bio" in input_data:
                    author["bio"] = input_data["bio"]
                if "birth_year" in input_data:
                    author["birth_year"] = input_data["birth_year"]
                if "nationality" in input_data:
                    author["nationality"] = input_data["nationality"]

                author["updated_at"] = datetime.now().isoformat()

                return {
                    "success": True,
                    "message": f"Author '{name}' has been successfully updated",
                    "author": author
                }

            elif tool_name == "delete_author":
                name = input_data.get("name")
                if not name:
                    return {"error": "Author name is required"}

                author_index = next((i for i, author in enumerate(self._authors_storage) if author["name"] == name), None)
                if author_index is not None:
                    deleted_author = self._authors_storage.pop(author_index)
                    return {
                        "success": True,
                        "message": f"Author '{name}' has been successfully deleted",
                        "deleted_author": deleted_author
                    }
                else:
                    return {"error": f"Author '{name}' not found"}

            else:
                return {"error": f"Unknown author tool: {tool_name}"}

        except Exception as e:
            return {"error": f"Error handling author tool '{tool_name}': {str(e)}"}

    async def call_tool(self, tool: ToolMetadata, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Call a specific tool using JSON-RPC protocol."""
        try:
            # Map additional tools to their corresponding MCP server tools
            # Note: Most tools are now available directly from MCP server
            tool_mapping = {
                "get_book_by_id": "get_book_details", 
                "create_book": "add_book"
            }

            # Get the actual tool name to call on the MCP server
            actual_tool_name = tool_mapping.get(tool.name, tool.name)

            # Handle author management tools locally (since MCP server doesn't support them)
            if tool.name in ["add_author", "get_authors", "get_author_by_name", "update_author", "delete_author"]:
                return await self._handle_author_tool(tool.name, input_data)

            # Map input parameters for tools that have different parameter names
            mapped_input_data = input_data.copy()
            if tool.name == "get_book_by_id" and "id" in mapped_input_data:
                # get_book_by_id uses "id" but get_book_details expects "book_id"
                mapped_input_data["book_id"] = mapped_input_data.pop("id")

            # Note: All tools are now available from MCP server, no client-side handling needed

            # Create JSON-RPC payload for tool call
            payload = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {
                    "name": actual_tool_name,
                    "arguments": mapped_input_data
                }
            }
            self._request_id += 1

            response_data = await self._send_jsonrpc(payload)

            # Check for JSON-RPC error
            if "error" in response_data:
                raise Exception(f"MCP server error: {response_data['error']['message']}")

            # Extract result from JSON-RPC response
            result = response_data.get("result", {})

            # Handle MCP content format
            if "content" in result and isinstance(result["content"], list):
                # Extract text from MCP content format
                content_text = ""
                for content_item in result["content"]:
                    if content_item.get("type") == "text":
                        content_text += content_item.get("text", "")

                # Try to parse the content as JSON
                try:
                    parsed_result = json.loads(content_text)
                    return parsed_result
                except json.JSONDecodeError:
                    return {"text": content_text}

            return result

        except Exception as e:
            raise Exception(f"Error calling tool {tool.name}: {str(e)}")

    async def call_tool_with_sse(self, tool: ToolMetadata, input_data: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """Call a tool that supports Server-Sent Events (SSE) streaming."""
        if not tool.endpoint:
            raise ValueError(f"Tool {tool.name} has no endpoint defined")

        # Construct full endpoint URL
        if tool.endpoint.startswith('http'):
            endpoint_url = tool.endpoint
        else:
            endpoint_url = f"{self.base_url}{tool.endpoint}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    endpoint_url,
                    json=input_data,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream"
                    }
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix
                            if data_str.strip() == "[DONE]":
                                break

                            try:
                                data = json.loads(data_str)
                                yield data
                            except json.JSONDecodeError:
                                # Yield raw text if not JSON
                                yield {"text": data_str}

        except httpx.RequestError as e:
            raise Exception(f"Failed to stream from tool {tool.name}: {str(e)}")
        except httpx.HTTPStatusError as e:
            error_text = e.response.text if hasattr(e.response, 'text') else str(e)
            raise Exception(f"Tool {tool.name} streaming returned error {e.response.status_code}: {error_text}")
        except Exception as e:
            raise Exception(f"Error streaming from tool {tool.name}: {str(e)}")

    def get_tool_by_name(self, tools: List[ToolMetadata], name: str) -> Optional[ToolMetadata]:
        """Find a tool by name from the list of available tools."""
        for tool in tools:
            if tool.name.lower() == name.lower():
                return tool
        return None

    def validate_tool_input(self, tool: ToolMetadata, input_data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate input data against tool's input schema."""
        errors = []
        schema = tool.input_schema

        if not schema:
            return True, []  # No schema to validate against

        # Basic validation - check required fields
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in input_data:
                errors.append(f"Missing required field: {field}")

        # Check field types if specified
        properties = schema.get("properties", {})
        for field, value in input_data.items():
            if field in properties:
                expected_type = properties[field].get("type")
                if expected_type:
                    if not self._validate_type(value, expected_type):
                        errors.append(f"Field {field} should be of type {expected_type}")

        return len(errors) == 0, errors

    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """Validate a value against an expected JSON schema type."""
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict
        }

        expected_python_type = type_mapping.get(expected_type)
        if expected_python_type:
            return isinstance(value, expected_python_type)

        return True  # Unknown type, assume valid

class ToolExecutor:
    """High-level tool executor that manages tool discovery and execution."""

    def __init__(self, mcp_client: MCPToolClient = None):
        self.mcp_client = mcp_client or MCPToolClient()
        self.available_tools: List[ToolMetadata] = []

    async def initialize(self) -> None:
        """Initialize the tool executor by discovering available tools."""
        try:
            self.available_tools = await self.mcp_client.discover_tools()
        except Exception as e:
            print(f"Warning: Failed to discover tools: {e}")
            self.available_tools = []

    async def refresh_tools(self) -> None:
        """Refresh the list of available tools."""
        try:
            self.available_tools = await self.mcp_client.discover_tools(force_refresh=True)
        except Exception as e:
            print(f"Warning: Failed to refresh tools: {e}")

    async def execute_tool(self, tool_name: str, input_data: Dict[str, Any]) -> ToolCall:
        """Execute a tool by name and return the result."""
        tool = self.mcp_client.get_tool_by_name(self.available_tools, tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found. Available tools: {[t.name for t in self.available_tools]}")

        # Validate input
        is_valid, errors = self.mcp_client.validate_tool_input(tool, input_data)
        if not is_valid:
            raise ValueError(f"Invalid input for tool {tool_name}: {', '.join(errors)}")

        # Create tool call record
        tool_call = ToolCall(
            name=tool.name,
            endpoint=tool.endpoint,
            input_data=input_data,
            timestamp=datetime.now().isoformat()
        )

        try:
            # Execute the tool
            result = await self.mcp_client.call_tool(tool, input_data)
            tool_call.output = result
            return tool_call

        except Exception as e:
            tool_call.error = str(e)
            return tool_call

    def get_available_tools(self) -> List[ToolMetadata]:
        """Get the list of available tools."""
        return self.available_tools.copy()

    def get_tools_description(self) -> str:
        """Get a formatted description of all available tools."""
        if not self.available_tools:
            return "No tools are currently available."

        descriptions = []
        for tool in self.available_tools:
            desc = f"- **{tool.name}**: {tool.description}"
            if tool.input_schema:
                required = tool.input_schema.get("required", [])
                if required:
                    desc += f" (Required: {', '.join(required)})"
            descriptions.append(desc)

        return "\n".join(descriptions)

# Global tool executor instance
tool_executor = ToolExecutor()
