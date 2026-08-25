"""Run the server over stdio.

No markup here and none wanted: this file starts a program, and the builder never imports
a `__main__`. Reaching a server is an action a person or a client takes, never something
that happens while a graph is being drawn.
"""

from server.app import mcp_server
from server.tools import expose_tools  # noqa: F401 -- importing is what puts the tools on

mcp_server.run()
