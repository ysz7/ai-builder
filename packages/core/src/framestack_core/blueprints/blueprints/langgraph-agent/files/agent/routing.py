"""Where the graph goes next.

A router is a node of its own kind: it decides an edge at runtime, so it is neither a
state node nor an edge the parser could read off a type. Its body is the user's; the
signature is the contract LangGraph calls it by.
"""

from agent.state import AgentState
from bp import editable, node


@node(id="agent.route", kind="langgraph.router", title="Enough notes?")
@editable(signature_locked=True)
def enough_notes(state: AgentState) -> str:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return "answer" if state["notes"] or "gather" in state["steps"] else "gather"
