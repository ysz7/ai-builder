"""An agent with tools, and one MCP server it is configured to reach.

`run` takes a message and returns a reply. What it is built on is nobody's business but this
package's — the boundary is the export.
"""

from __future__ import annotations

from agent.loop import answer
from agent.settings import AgentSettings

__all__ = ["AgentSettings", "run"]


def run(message: str, **kw: object) -> str:
    """Answer `message`, using the tools it names."""
    settings = AgentSettings()
    steps = kw.get("steps")
    if isinstance(steps, int):
        settings = settings.model_copy(update={"steps": steps})
    return answer(message, settings)
