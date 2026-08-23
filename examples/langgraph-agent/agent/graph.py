"""Graph assembly.

Generated zone from top to bottom: building the state graph, adding the nodes, wiring the
edges, compiling. None of it is a decision the user makes by hand -- they make it through
a node, and the writer puts it back here.
"""

from langgraph.graph import END, START, StateGraph

from agent.nodes import answer, gather, plan
from agent.routing import enough_notes
from agent.settings import settings
from agent.state import AgentState
from bp import generated


@generated()
def build_graph() -> StateGraph:
    # GENERATED. Graph assembly; edited through the graph, not by hand.
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan)
    builder.add_node("gather", gather)
    builder.add_node("answer", answer)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", enough_notes, {"gather": "gather", "answer": "answer"})
    builder.add_edge("gather", "answer")
    builder.add_edge("answer", END)
    return builder


graph = build_graph().compile()


@generated()
def ask(question: str) -> AgentState:
    # GENERATED. Entry point; edited through the graph, not by hand.
    start: AgentState = {"question": question, "notes": [], "answer": "", "steps": []}
    return graph.invoke(start, {"recursion_limit": settings.recursion_limit})
