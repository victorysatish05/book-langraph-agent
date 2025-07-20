#!/usr/bin/env python3
"""
Simple fix for start.py to handle missing mock server gracefully.
"""

def fix_start_script():
    """Fix the start.py script to handle missing mock server."""
    
    # Read the current start.py file
    with open('start.py', 'r') as f:
        content = f.read()
    
    # Replace the problematic start_mcp_server function call
    content = content.replace(
        'mcp_process = start_mcp_server()',
        'mcp_process = None  # Mock server removed - use external MCP server'
    )
    
    # Replace the check for mcp_process
    content = content.replace(
        '''if mcp_process is None:
        print("❌ Failed to start MCP server")
        return False''',
        '''if mcp_process is None:
        print("💡 Using external MCP server on port 8080")'''
    )
    
    # Update the messaging
    content = content.replace(
        'print("🚀 Starting MCP server...")',
        'print("💡 Expecting external MCP server on port 8080...")'
    )
    
    # Remove cleanup code for mcp_process
    content = content.replace(
        '''# Clean up MCP server process
        if mcp_process:
            mcp_process.terminate()
            mcp_process.wait()''',
        '# Mock server removed - no cleanup needed'
    )
    
    # Write the fixed content back
    with open('start.py', 'w') as f:
        f.write(content)
    
    print("✅ Fixed start.py to work without mock server")

if __name__ == "__main__":
    fix_start_script()