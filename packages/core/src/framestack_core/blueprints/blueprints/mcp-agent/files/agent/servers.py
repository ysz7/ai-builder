"""The MCP server this project consumes.

What is in the repository is the **declaration**, never the server. Somebody else's server
is a foreign program reached by a command or a URL; what the project holds is how to reach
it, which environment variable carries its token, its timeout, and which of its tools this
project may call -- exactly as `compose.yaml` declares `redis:7-alpine` without redis's
source being in the repository. So the knobs here are only the things we control: a knob is
a syntax node in *this* project's source, and no write of ours reaches into a third party's
process.

**A knob never holds a secret.** `token_env` is the *name* of an environment variable, never
its value -- otherwise the first write of it puts somebody's key into a source file on its
way to git.

The server it happens to point at is this project's own (`python -m server`), which is what
makes the interesting path testable anywhere: a real stdio transport between two real
processes, with no account, no key and no network.
"""

import sys
from pathlib import Path
from typing import Annotated

from mcp import Client, StdioServerParameters

from bp import Param, generated, node

PROJECT = Path(__file__).resolve().parent.parent


@node(id="agent.notes", kind="mcp.server", title="Notes server")
class NotesServer:
    """How to reach the notes server, and what this project is allowed to ask it for."""

    module: Annotated[str, Param(label="Server module")] = "server"
    timeout_s: Annotated[int, Param(min=1, max=120, label="Timeout (s)")] = 20
    token_env: Annotated[str, Param(label="Token variable")] = ""
    allowed_tools: Annotated[str, Param(label="Tools this project may call")] = "summarize"

    @generated()
    def connect(self) -> Client:
        # GENERATED. Connection assembly; edited through the graph, not by hand.
        # A plain function returning something to `async with`, never a context manager
        # built by a decorator: the decorator's wrapper carries the *library's* code object,
        # and a run through it would be invisible to the graph -- or worse, would look like
        # every other context manager in the project.
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", self.module], cwd=str(PROJECT)
        )
        return Client(parameters, read_timeout_seconds=float(self.timeout_s))


notes = NotesServer()
