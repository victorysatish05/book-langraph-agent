# Summary of Changes Made to Connect to Actual MCP Server

## Changes Made

### 1. Updated Configuration (agent/config.py)
- Changed MCP server base URL to use port 8080 (actual MCP server port)
- Updated endpoints to use `/mcp/message` and `/mcp/tools` instead of `/api/` endpoints
- Configuration now matches the reference implementation in book-service-agent

### 2. Updated MCPToolClient (agent/tools.py)
- Modified `discover_tools()` method to use JSON-RPC protocol:
  - First sends an "initialize" request to establish connection
  - Then sends "tools/list" request to get available tools
  - Properly handles JSON-RPC response format
- Modified `call_tool()` method to use JSON-RPC protocol:
  - Sends "tools/call" request with tool name and arguments
  - Handles MCP content format in responses
  - Properly extracts results from JSON-RPC responses

### 3. Environment Configuration (.env)
- Set `MCP_SERVER_BASE_URL=http://127.0.0.1:8080` to connect to actual MCP server
- Changed Flask port to 5001 to avoid conflicts with MCP server on port 8080

## Current Status

The code has been updated to connect to the actual MCP server instead of the mock server. However, the actual MCP server (Java application) is not currently running.

## To Start the Actual MCP Server

Based on the reference implementation, the actual MCP server should be started with:

```bash
java -jar target/book-service-1.0.0.jar --mcp
```

This will start the MCP server on port 8080 with the following endpoints:
- `/mcp/message` - JSON-RPC endpoint for tool calls
- `/mcp/tools` - REST endpoint for tool discovery (optional)

## Testing the Connection

Once the actual MCP server is running, you can test the connection using:

```bash
python3 test_mcp_connection.py
python3 test_mcp_tool_client.py
```

## Key Differences from Mock Server

1. **Protocol**: Uses JSON-RPC 2.0 instead of simple REST API
2. **Initialization**: Requires initialization handshake before tool discovery
3. **Response Format**: Uses MCP content format with structured responses
4. **Port**: Runs on port 8080 instead of 8080 (mock server port)

The implementation now follows the Model Context Protocol (MCP) specification and is compatible with actual MCP servers.