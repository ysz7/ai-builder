"""The agent's own tests, and therefore the run the graph observes.

Ordinary LangGraph tests: invoke the compiled graph and check what came back. The builder
instruments the carriers while these run and records which nodes actually fired -- so the
route through the graph that a test does not take is a node that stays honestly unproven.
"""

from agent.graph import ask, graph
from agent.routing import enough_notes
from agent.state import AgentState


def test_the_agent_answers_from_its_notes() -> None:
    final = ask("what about blueprints?")

    assert "Unreal Blueprints" in final["answer"]
    assert final["steps"] == ["plan", "gather", "answer"]


def test_a_question_it_knows_nothing_about_is_answered_honestly() -> None:
    final = ask("what about the weather?")

    assert final["answer"] == "I have nothing on that."
    assert "gather" in final["steps"]


def test_the_router_sends_a_fresh_question_to_gathering() -> None:
    state: AgentState = {"question": "graph", "notes": [], "answer": "", "steps": ["plan"]}

    assert enough_notes(state) == "gather"


def test_the_router_stops_gathering_once_notes_exist() -> None:
    state: AgentState = {"question": "graph", "notes": ["a note"], "answer": "", "steps": ["plan"]}

    assert enough_notes(state) == "answer"


def test_every_declared_node_is_in_the_compiled_graph() -> None:
    assert {"plan", "gather", "answer"} <= set(graph.nodes)
