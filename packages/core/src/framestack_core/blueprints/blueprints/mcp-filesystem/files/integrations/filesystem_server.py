"""The filesystem MCP server this project consults.

This is the **declaration, not the server**: a class holding how to reach a foreign
program and what it may be asked, never the program itself -- exactly as a compose file
declares `redis:7-alpine` without redis's source being in the repository (P15).

`roots` is the one knob that decides what the server can see at all. It is a path and not
a secret, so it lives here; anything that *is* a secret would live in an environment
variable whose **name** a knob holds.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bp import Param, generated, node


@node(id="mcp.filesystem", kind="mcp.server", title="Filesystem MCP Server")
class FilesystemServer:
    """Read and search files under the roots this node allows."""

    command: Annotated[str, Param(label="Command")] = "npx"
    args: Annotated[list[str], Param(widget="tags", label="Arguments")] = [
        "-y",
        "@modelcontextprotocol/server-filesystem",
    ]
    #: What the server may reach. Passed after `args`, because this server takes its roots
    #: as trailing positional arguments -- and a root nobody set is no root at all.
    roots: Annotated[list[str], Param(widget="tags", label="Allowed roots")] = ["."]
    connect_timeout_s: Annotated[int, Param(min=1, max=120, label="Connect timeout (s)")] = 30
    allowed_tools: Annotated[list[str], Param(widget="tags", label="Allowed remote tools")] = [
        "read_file",
        "list_directory",
        "search_files",
    ]

    @generated()
    @asynccontextmanager
    async def connect(self) -> AsyncIterator[ClientSession]:
        # GENERATED. Bootstraps a session from the knobs; edited through the graph.
        import asyncio

        params = StdioServerParameters(command=self.command, args=[*self.args, *self.roots])
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await asyncio.wait_for(session.initialize(), timeout=self.connect_timeout_s)
            yield session


filesystem_server = FilesystemServer()
