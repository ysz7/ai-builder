"""The agent's steps.

`plan` asks for the local tool by name; `consult` is the step that uses the **consumed**
server, and it goes through the project's own object rather than straight into the SDK.
That convention is what makes "the agent actually uses this server" observable at all: a
call made directly to the library leaves only library frames behind, so nothing watching
the run would see the node being entered and no flow arrow would ever be drawn.
"""

import asyncio

from langchain_core.messages import AIMessage

from agent.servers import notes
from agent.settings import settings
from agent.state import AgentState
from bp import editable, node


@node(id="agent.plan", kind="langgraph.node", title="Plan")
@editable(signature_locked=True)
def plan(state: AgentState) -> dict[str, object]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    call = {"name": "shout", "args": {"text": state["question"]}, "id": "shout-1"}
    return {"messages": [AIMessage(content="", tool_calls=[call])]}


@node(id="agent.consult", kind="langgraph.node", title="Consult the notes server")
@editable(signature_locked=True)
def consult(state: AgentState) -> dict[str, object]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    shouted = str(state["messages"][-1].content)
    return {"answer": asyncio.run(_summarize(shouted))}


@editable(signature_locked=True)
async def _summarize(text: str) -> str:
    # USER-EDITABLE. Classified because it lives in a file that carries a node -- inside a
    # carrier, an unmarked function reads as a forgotten mark, never as "generated" (§4).
    async with notes.connect() as client:
        answered = await client.call_tool(
            "summarize", {"text": text, "sentences": settings.sentences}
        )
    return str(answered.structured_content["result"])
