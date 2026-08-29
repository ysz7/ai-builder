"""Graph assembly. Generated zone from top to bottom."""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.settings import settings
from agent.state import AgentState
from agent.steps import consult, plan
from agent.tools import build_tools
from bp import generated


@generated()
def build_graph() -> StateGraph:
    # GENERATED. Graph assembly; edited through the graph, not by hand.
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan)
    builder.add_node("tools", ToolNode(build_tools()))
    builder.add_node("consult", consult)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "tools")
    builder.add_edge("tools", "consult")
    builder.add_edge("consult", END)
    return builder


graph = build_graph().compile()


@generated()
def ask(question: str) -> AgentState:
    # GENERATED. Entry point; edited through the graph, not by hand.
    start: AgentState = {"question": question, "messages": [], "answer": ""}
    return graph.invoke(start, {"recursion_limit": settings.recursion_limit})
