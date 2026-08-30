"""The Gmail MCP server this project consults.

The declaration, not the server (P15). `token_env` holds the **name** of the environment
variable carrying the server's OAuth credentials -- never the value, so no secret ever
lands in this file or in a knob the graph writes. Set the value in the builder's
Environment panel, and make sure the project loads `.env` itself.

Calls go through `connect()`, the project's own object, so a run through it leaves a frame
the graph can observe -- reaching into the SDK directly would show library frames only.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bp import Param, generated, node


@node(id="mcp.gmail", kind="mcp.server", title="Gmail MCP Server")
class GmailServer:
    """Search, read and send mail through a Gmail MCP server."""

    command: Annotated[str, Param(label="Command")] = "npx"
    args: Annotated[list[str], Param(widget="tags", label="Arguments")] = [
        "-y",
        "@gongrzhe/server-gmail-autoauth-mcp",
    ]
    connect_timeout_s: Annotated[int, Param(min=1, max=120, label="Connect timeout (s)")] = 30
    #: The **name** of the variable, never its value (P15).
    token_env: Annotated[str, Param(label="Credentials env var")] = "GMAIL_MCP_CREDENTIALS"
    allowed_tools: Annotated[list[str], Param(widget="tags", label="Allowed remote tools")] = [
        "search_emails",
        "read_email",
    ]

    @generated()
    @asynccontextmanager
    async def connect(self) -> AsyncIterator[ClientSession]:
        # GENERATED. Bootstraps a session from the knobs; edited through the graph.
        import asyncio

        env = {self.token_env: os.environ[self.token_env]} if self.token_env in os.environ else None
        params = StdioServerParameters(command=self.command, args=self.args, env=env)
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await asyncio.wait_for(session.initialize(), timeout=self.connect_timeout_s)
            yield session


gmail_server = GmailServer()
