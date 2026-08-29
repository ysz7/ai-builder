"""The agent's state nodes.

Three carriers, three nodes. Each takes the state and returns the part of it that it
changes -- the LangGraph contract -- and each body is the user's to edit while the
signature stays locked, because that signature is what the graph binds to.
"""

from agent.knowledge import lookup
from agent.settings import settings
from agent.state import AgentState
from bp import editable, node


@node(id="agent.plan", kind="langgraph.node", title="Plan")
@editable(signature_locked=True)
def plan(state: AgentState) -> dict[str, object]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return {"steps": ["plan"], "notes": []}


@node(id="agent.gather", kind="langgraph.node", title="Gather notes")
@editable(signature_locked=True)
def gather(state: AgentState) -> dict[str, object]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    found = lookup(state["question"])
    kept = [*state["notes"], *found][: settings.max_notes]
    return {"steps": ["gather"], "notes": kept}


@node(id="agent.answer", kind="langgraph.node", title="Answer")
@editable(signature_locked=True)
def answer(state: AgentState) -> dict[str, object]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    if not state["notes"]:
        return {"steps": ["answer"], "answer": "I have nothing on that."}
    joined = " ".join(state["notes"])
    if settings.tone == "terse":
        joined = state["notes"][0]
    return {"steps": ["answer"], "answer": joined}
