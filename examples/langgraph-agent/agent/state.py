"""The state every node reads and writes.

A LangGraph agent is a graph over one state object, so the state is a node in its own
right: it is the contract the whole subsystem shares, and a change to it reaches every
other node. It has a class of its own to be a carrier (I-3), and the graph is built
against exactly this schema -- which is what its observable check verifies.
"""

from typing import Annotated, TypedDict

from bp import editable, node


@editable(signature_locked=True)
def add_steps(existing: list[str], incoming: list[str]) -> list[str]:
    # USER-EDITABLE. The reducer for `steps`: each node appends, nothing overwrites.
    # Classified because it lives in a file that carries a node -- inside a carrier,
    # unmarked reads as a forgotten mark, never as "generated" (§4).
    return [*existing, *incoming]


@node(id="agent.state", kind="langgraph.state", title="Agent state")
class AgentState(TypedDict):
    """What travels between the nodes. Not a knob in sight: this is the contract."""

    question: str
    notes: list[str]
    answer: str
    steps: Annotated[list[str], add_steps]
