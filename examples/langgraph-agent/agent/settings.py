"""Agent knobs.

The same rule as everywhere: one `Annotated` field per knob, a literal default, one
unambiguous write target. Nothing here is computed and nothing is assembled from another
field -- the graph rewrites these defaults through the syntax tree.
"""

from typing import Annotated

from pydantic import BaseModel

from bp import Param, node


@node(id="agent.settings", kind="langgraph.settings", title="Settings")
class AgentSettings(BaseModel):
    """The knobs, and the node they are edited from."""

    max_notes: Annotated[int, Param(min=1, max=20, label="Notes before answering")] = 3
    recursion_limit: Annotated[int, Param(min=2, max=50, label="Step budget")] = 12
    tone: Annotated[str, Param(widget="select", choices=("plain", "formal", "terse"))] = "plain"


settings = AgentSettings()
