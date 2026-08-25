"""The state every step reads and writes."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from bp import node


@node(id="agent.state", kind="langgraph.state", title="Agent state")
class AgentState(TypedDict):
    """What travels between the steps. The contract, not a knob in sight."""

    question: str
    messages: Annotated[list[AnyMessage], add_messages]
    answer: str
