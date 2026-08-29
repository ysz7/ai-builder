"""Agent knobs. One `Annotated` field each, one literal default, one write target."""

from typing import Annotated

from pydantic import BaseModel

from bp import Param, node


@node(id="agent.settings", kind="langgraph.settings", title="Settings")
class AgentSettings(BaseModel):
    """The knobs, and the node they are edited from."""

    sentences: Annotated[int, Param(min=1, max=5, label="Sentences to keep")] = 1
    recursion_limit: Annotated[int, Param(min=2, max=50, label="Step budget")] = 12


settings = AgentSettings()
