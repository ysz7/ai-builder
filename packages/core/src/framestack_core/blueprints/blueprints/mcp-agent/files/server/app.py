"""The MCP server this project exposes.

Generated assembly and nothing else: the object exists, and the tools are put on it in
`tools.py`. Two files rather than one because the tools import the server, and a server
that imported its tools back would be a cycle -- the same shape the queue example uses.
"""

from mcp.server.mcpserver import MCPServer

from bp import generated


@generated()
def build_server() -> MCPServer:
    # GENERATED. Server assembly; edited through the graph, not by hand.
    return MCPServer("notes", instructions="Small text utilities, offered over MCP.")


mcp_server = build_server()
