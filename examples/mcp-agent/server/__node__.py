"""The server as a subsystem of its own.

A group beside the agent's group rather than inside it: the server is a program other
people connect to, and it runs whether this project's agent is running or not. The agent
happens to be one of its clients, and what says so is a flow arrow drawn by a run.
"""

from bp import group_node
from server.tools import summarize, word_count

service = group_node(
    id="tools",
    kind="mcp.service",
    title="Notes tools",
    members=[summarize, word_count],
)
