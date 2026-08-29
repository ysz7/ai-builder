"""Talking to what the project built (P17.1).

The tests that carry the phase are the ones about what a conversation refuses to be. It is
not a node -- it is addressed by one (Q18). It is not a fresh process per turn -- the
project's own memory has to survive between questions (Q19). And it is not a stream -- the
wire carries one answer per request and the caller keeps the offset (P13).

The probe is exercised as a real subprocess rather than imported, because that is how it
runs: importing it here would import the module that imports the user's project, which is
the one thing this codebase does not do.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from test_api import validate, wire_form

from framestack_core.api import (
    TALK_SCHEMA,
    talk_close,
    talk_open,
    talk_poll,
    talk_say,
    talk_state,
)
from framestack_core.converse import (
    TALK_STATE_PATH,
    conversations_held,
    poll_talk,
    say_to,
    start_talk,
    stop_talk,
    talk_status,
)
from framestack_core.observe import probe_script

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "rag-pipeline"


def a_project(tmp_path: Path, body: str) -> Path:
    """A module to talk to. Not a graph -- these tests are about the conversation."""
    (tmp_path / "bot.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def through_the_probe(
    project: Path,
    *said: str,
    how: str = "rag.ask",
    modules: tuple[str, ...] = ("bot",),
    carrier: str = "bot",
) -> list[dict[str, object]]:
    """Run one whole conversation the way the core runs it, and read what came back.

    `rag.ask` throughout: it is the convention whose way in the system prompt guarantees --
    a function named `answer` in the project's own modules -- so a plain module is a fair
    stand-in for a pipeline without dragging a framework into these tests.
    """
    plan = {
        "project": str(project),
        "modules": list(modules),
        "ask": "converse",
        "carrier": carrier,
        "how": how,
        "node": "some.node",
    }
    lines = [json.dumps(plan)] + [json.dumps({"say": text}) for text in said]
    completed = subprocess.run(
        [sys.executable, str(probe_script())],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


# -- the conversation itself ------------------------------------------------------


def test_the_project_remembers_between_questions(tmp_path: Path) -> None:
    """The whole reason the process lives between turns (Q19). Spawned per question, an
    in-memory checkpointer would make a dialogue into a series of strangers."""
    project = a_project(
        tmp_path,
        """
        said = []
        def answer(question):
            said.append(question)
            return f"{len(said)}"
        """,
    )

    spoken = through_the_probe(project, "one", "two", "three")
    answers = [event["text"] for event in spoken if event["type"] == "answer"]

    assert answers == ["1", "2", "3"]


def test_what_the_project_prints_does_not_corrupt_the_stream(tmp_path: Path) -> None:
    """The same rule one level down: stdout carries the events and nothing else. A project
    is free to print, and it would otherwise land in the middle of a line being parsed."""
    project = a_project(
        tmp_path,
        """
        print("chatty on import")
        def answer(question):
            print("chatty while answering")
            return "quiet answer"
        """,
    )

    spoken = through_the_probe(project, "hello")

    assert [event["type"] for event in spoken] == ["ready", "asked", "answer"]
    assert [event["text"] for event in spoken if event["type"] == "answer"] == ["quiet answer"]


def test_a_question_that_broke_the_agent_is_an_answer_about_the_agent(tmp_path: Path) -> None:
    """Data, never an exception -- and the conversation survives it, so the next question
    still gets asked. A crash that ends the process would lose the memory as well."""
    project = a_project(
        tmp_path,
        """
        def answer(question):
            if question == "bad":
                raise ValueError("no")
            return "fine"
        """,
    )

    spoken = through_the_probe(project, "bad", "good")
    kinds = [event["type"] for event in spoken]

    assert kinds == ["ready", "asked", "failed", "asked", "answer"]
    assert "ValueError: no" in str(spoken[2]["detail"])
    assert spoken[2]["traceback"]


def test_a_project_with_no_way_in_is_refused_before_anything_is_said(tmp_path: Path) -> None:
    """The prompt requires a pipeline to expose `answer(question)`. One that does not is
    told so, rather than searched for something that looks close enough."""
    project = a_project(tmp_path, "greeting = 'hello'\n")

    spoken = through_the_probe(project, "anything")

    assert [event["type"] for event in spoken] == ["failed"]
    assert "exposes no answer(question)" in str(spoken[0]["detail"])


def test_a_conversation_this_build_does_not_know_is_named_in_the_refusal(
    tmp_path: Path,
) -> None:
    """A `converses` value with no case here is refused by name. Silence would be a node
    that opens a conversation and then never answers anything."""
    project = a_project(tmp_path, "def answer(question):\n    return question\n")

    spoken = through_the_probe(project, "hello", how="telepathy")

    assert [event["type"] for event in spoken] == ["failed"]
    assert "telepathy" in str(spoken[0]["detail"])


def test_a_project_that_will_not_import_says_so_rather_than_hanging(tmp_path: Path) -> None:
    project = a_project(tmp_path, "raise RuntimeError('this project is broken')\n")

    spoken = through_the_probe(project, "hello")

    assert [event["type"] for event in spoken] == ["failed"]
    assert "did not import" in str(spoken[0]["detail"])


def test_end_of_input_ends_the_conversation(tmp_path: Path) -> None:
    """Closing the pipe is how the probe is told there is nothing more to answer, which is
    why nothing here needs a goodbye message somebody could forget to send."""
    project = a_project(tmp_path, "def answer(question):\n    return question\n")

    spoken = through_the_probe(project)

    assert [event["type"] for event in spoken] == ["ready"]


# -- the verbs, and what they refuse ----------------------------------------------


@pytest.fixture
def talking(tmp_path: Path, monkeypatch) -> Path:
    """A project the core will talk to, with the graph lookup stood in for.

    Which nodes may be talked to at all is P17.2's question; this one is about the process.
    """
    from framestack_core import converse

    a_project(
        tmp_path,
        """
        said = []
        def answer(question):
            said.append(question)
            return f"you said {question}"
        """,
    )
    monkeypatch.setattr(
        converse,
        "_way_to",
        lambda project, node: (
            converse.WayIn(carrier="bot", modules=("bot",), how="rag.ask"),
            "",
        ),
    )
    return tmp_path


def test_a_conversation_is_opened_asked_and_answered(talking: Path) -> None:
    opened = start_talk(talking, "some.node", python=sys.executable)
    assert opened.ok and opened.running

    assert say_to(talking, "some.node", "hello").ok

    answers: list[str] = []
    offset = 0
    for _ in range(200):
        answered = poll_talk(talking, "some.node", offset)
        offset = answered.offset
        answers += [str(event["text"]) for event in answered.events if event["type"] == "answer"]
        if answers:
            break

    stop_talk(talking, "some.node")
    assert answers == ["you said hello"]


def test_polling_hands_back_only_what_came_after_the_offset(talking: Path) -> None:
    """P13: nothing is pushed, and the caller keeps the offset it was given."""
    start_talk(talking, "some.node", python=sys.executable)
    first = poll_talk(talking, "some.node", 0)
    again = poll_talk(talking, "some.node", first.offset)
    stop_talk(talking, "some.node")

    assert [event["type"] for event in first.events] == ["ready"]
    assert again.events == ()
    assert again.offset == first.offset


def test_asking_with_nothing_open_is_a_refusal_not_a_fault(tmp_path: Path) -> None:
    answered = say_to(tmp_path, "some.node", "hello")

    assert not answered.ok
    assert "start one first" in answered.detail


def test_nothing_here_starts_a_conversation_by_itself(talking: Path) -> None:
    """P11. A read must never be the thing that spawns a process."""
    assert talk_status(talking).open == ()
    assert poll_talk(talking, "some.node").ok is False
    assert not (talking / TALK_STATE_PATH).is_file()


def test_a_record_on_disk_survives_the_sidecar(talking: Path) -> None:
    """What we start, we can find again: a crashed sidecar leaves something stoppable."""
    start_talk(talking, "some.node", python=sys.executable)
    record = json.loads((talking / TALK_STATE_PATH).read_text(encoding="utf-8"))

    assert list(record) == ["some.node"]
    assert record["some.node"]["carrier"] == "bot"
    assert record["some.node"]["how"] == "rag.ask"

    stop_talk(talking, "some.node")
    assert not (talking / TALK_STATE_PATH).is_file()


def test_two_nodes_are_two_conversations(talking: Path) -> None:
    """An agent and the pipeline that feeds it are talked to separately, and neither one's
    transcript may land in the other's file."""
    start_talk(talking, "one", python=sys.executable)
    start_talk(talking, "two", python=sys.executable)

    open_now = talk_status(talking).open
    stop_talk(talking, "one")
    after = talk_status(talking).open
    stop_talk(talking, "two")

    assert open_now == ("one", "two")
    assert after == ("two",)


def test_asking_twice_for_the_open_one_does_not_start_a_second(talking: Path) -> None:
    first = start_talk(talking, "some.node", python=sys.executable)
    again = start_talk(talking, "some.node", python=sys.executable)
    stop_talk(talking, "some.node")

    assert again.ok
    assert "already open" in again.detail
    assert first.node == again.node


def test_a_project_that_refuses_never_leaves_a_record_behind(tmp_path: Path, monkeypatch) -> None:
    """A refusal has to leave nothing to stop, or `talk.state` reports a conversation that
    is not there and the button to close it does nothing."""
    from framestack_core import converse

    a_project(tmp_path, "greeting = 'hello'\n")
    monkeypatch.setattr(
        converse,
        "_way_to",
        lambda project, node: (
            converse.WayIn(carrier="bot", modules=("bot",), how="rag.ask"),
            "",
        ),
    )

    refused = start_talk(tmp_path, "some.node", python=sys.executable)

    assert not refused.ok
    assert "exposes no answer(question)" in refused.detail
    assert not (tmp_path / TALK_STATE_PATH).is_file()


# -- the carrier comes from the graph, not from a convention ----------------------


def test_the_way_in_is_read_out_of_the_graph_and_the_registry(tmp_path: Path) -> None:
    """A conversation addresses a node, and what a node *is* is a carrier object (I-3).
    **Whether** it can be talked to comes from its kind, which opts in by naming a way in."""
    from framestack_core.converse import _way_to

    way, refusal = _way_to(EXAMPLE, "rag")

    assert refusal == ""
    assert way is not None
    assert way.how == "rag.ask"
    assert "rag.pipeline" in way.modules


def test_a_kind_that_has_not_opted_in_is_refused_rather_than_tried(tmp_path: Path) -> None:
    """The failure mode this codebase minds most is a button that appears to work. Calling
    anything callable would construct `Chunker` and report its `repr` as an answer."""
    from framestack_core.converse import _way_to

    way, refusal = _way_to(EXAMPLE, "rag.chunking")

    assert way is None
    assert "rag.chunking is not something this build can talk to" in refusal


def test_a_node_that_is_not_there_is_named_in_the_refusal(tmp_path: Path) -> None:
    from framestack_core.converse import _way_to

    _, refusal = _way_to(EXAMPLE, "no.such.node")

    assert "no.such.node" in refusal


def test_only_the_kinds_that_named_a_way_in_can_be_talked_to() -> None:
    """The registry is the whole rule: a kind joins by naming a convention, and the
    mechanism learns nothing new when the next one does."""
    from framestack_core.kinds import REGISTRY

    talkable = {name: kind.converses for name, kind in REGISTRY.items() if kind.converses}

    assert talkable == {"langgraph.agent": "langgraph.ask", "rag.pipeline": "rag.ask"}


def test_the_talk_payloads_match_the_declared_contract(talking: Path) -> None:
    """Every verb, including the refusals: a refusal crosses the same wire as an answer,
    and a shape that only holds when things go well is not a contract."""
    validate(wire_form(talk_open(talking, "some.node", sys.executable)), TALK_SCHEMA)
    validate(wire_form(talk_say(talking, "some.node", "hello")), TALK_SCHEMA)
    validate(wire_form(talk_poll(talking, "some.node", 0)), TALK_SCHEMA)
    validate(wire_form(talk_state(talking)), TALK_SCHEMA)
    validate(wire_form(talk_close(talking, "some.node")), TALK_SCHEMA)
    validate(wire_form(talk_say(talking, "some.node", "nobody is there")), TALK_SCHEMA)
    validate(wire_form(talk_poll(talking, "never.opened", 0)), TALK_SCHEMA)


# -- the way in comes from the node, and only from inside it ----------------------


def test_a_name_the_project_uses_elsewhere_is_not_mistaken_for_the_way_in(
    tmp_path: Path,
) -> None:
    """Found by measuring, not by reasoning: the probe imports **every** module there is,
    tests included (Q12), and the reference agent's own suite defines a helper called `ask`.
    Searching the whole project found it and refused over a collision that was not one."""
    a_project(tmp_path, "def answer(question):\n    return 'the pipeline'\n")
    (tmp_path / "tests_of_it.py").write_text(
        "def answer(question):\n    return 'a test helper'\n", encoding="utf-8"
    )

    spoken = through_the_probe(tmp_path, "hello", modules=("bot", "tests_of_it"), carrier="bot")

    assert [event["text"] for event in spoken if event["type"] == "answer"] == ["the pipeline"]


def test_two_ways_in_inside_one_node_are_refused_rather_than_chosen_between(
    tmp_path: Path,
) -> None:
    """A tie is not something to break by import order. An agent's step function and its
    entry point can share a word, and calling the wrong one would look like an answer."""
    package = tmp_path / "bot"
    package.mkdir()
    (package / "__init__.py").write_text("def answer(question):\n    return 'one'\n")
    (package / "other.py").write_text("def answer(question):\n    return 'two'\n")

    spoken = through_the_probe(tmp_path, "hello", modules=("bot", "bot.other"), carrier="bot")

    assert [event["type"] for event in spoken] == ["failed"]
    assert "more than one answer(question)" in str(spoken[0]["detail"])


# -- the two conventions, against the projects they were written for --------------


AGENT = Path(__file__).resolve().parents[3] / "examples" / "langgraph-agent"


def whole_conversation(project: Path, node: str, question: str) -> list[str]:
    """Open, ask, poll until something is said, close. What the UI will do (P17.3)."""
    import time

    opened = start_talk(project, node, python=sys.executable)
    assert opened.ok, opened.detail
    assert say_to(project, node, question).ok

    said: list[str] = []
    offset = 0
    for _ in range(200):
        answered = poll_talk(project, node, offset)
        offset = answered.offset
        said += [
            f"{event['type']}: {event['text'] or event['detail']}"
            for event in answered.events
            if event["type"] in ("answer", "failed")
        ]
        if said:
            break
        time.sleep(0.05)
    stop_talk(project, node)
    return said


def test_the_reference_agent_answers_a_question_asked_from_its_node() -> None:
    """The end of P17.1 and P17.2 together, against a real project: a real process, real
    input, a real answer. Which is also why it counts as evidence (P17.4)."""
    said = whole_conversation(AGENT, "agent", "tell me about ravens")

    assert said and said[0].startswith("answer: "), said


def test_the_reference_pipeline_answers_a_question_asked_from_its_node() -> None:
    said = whole_conversation(EXAMPLE, "rag", "what do ravens do?")

    assert said and said[0].startswith("answer: "), said


# -- a conversation as evidence (P17.4) -------------------------------------------


def talk_until_answered(project: Path, node: str, question: str) -> None:
    """Ask one thing and wait for the answer, leaving the conversation open."""
    import time

    assert start_talk(project, node, python=sys.executable).ok
    assert say_to(project, node, question).ok
    offset = 0
    for _ in range(400):
        answered = poll_talk(project, node, offset)
        offset = answered.offset
        if any(event["type"] in ("answer", "failed") for event in answered.events):
            return
        time.sleep(0.05)
    raise AssertionError(f"{node} never answered")


def test_a_conversation_nobody_had_proves_nothing(talking: Path) -> None:
    """I-5's hard half: absence of evidence is never a pass, and never synthesised."""
    assert conversations_held(talking) == {}

    start_talk(talking, "some.node", python=sys.executable)
    opened_only = conversations_held(talking)
    stop_talk(talking, "some.node")

    assert opened_only == {}, "an open pipe is not an answer"


def test_an_answer_is_evidence_and_a_closed_conversation_keeps_none(talking: Path) -> None:
    talk_until_answered(talking, "some.node", "hello")
    held = conversations_held(talking)
    stop_talk(talking, "some.node")

    assert held["some.node"]["status"] == "passed"
    assert "answered 1 question(s)" in held["some.node"]["detail"]
    # Closing takes the record with it: a colleague who has not talked to the node sees
    # `unproven`, never somebody else's yesterday.
    assert conversations_held(talking) == {}


def test_a_question_that_broke_the_node_is_evidence_of_breakage(tmp_path: Path, monkeypatch):
    import framestack_core.converse as converse

    a_project(tmp_path, "def answer(question):\n    raise RuntimeError('no')\n")
    monkeypatch.setattr(
        converse,
        "_way_to",
        lambda project, node: (converse.WayIn("bot", ("bot",), "rag.ask"), ""),
    )
    talk_until_answered(tmp_path, "some.node", "hello")
    held = conversations_held(tmp_path)
    stop_talk(tmp_path, "some.node")

    assert held["some.node"]["status"] == "failed"
    assert "RuntimeError" in held["some.node"]["detail"]


def test_the_ranking_lives_in_the_probe_and_the_tests_still_win() -> None:
    """Q7 and Q19 together, asked of the runner rather than of a comment.

    A conversation outranks a direct check and loses to a passing test, and both halves are
    decided in `run_plan` -- so both are asked of `run_plan`, with the plan as the only input.
    """
    from framestack_core.probe import _conversation

    plan = {"conversations": {"n": {"status": "passed", "detail": "answered 1 question(s)"}}}
    spoken = _conversation({"id": "n", "kind": "rag.pipeline"}, plan)

    assert spoken is not None
    assert spoken.status == "passed"
    assert spoken.check == "talk.answered"
    assert _conversation({"id": "other", "kind": "rag.pipeline"}, plan) is None


def test_the_pipeline_is_green_off_the_conversation_it_had() -> None:
    """The phase, end to end: a node nothing else could prove, proven by being talked to."""
    from framestack_core.observe import run_observations
    from framestack_core.project import read_project

    graph = read_project(EXAMPLE)
    talk_until_answered(EXAMPLE, "rag", "what do ravens do?")
    try:
        observed = run_observations(graph, EXAMPLE, python=sys.executable)
    finally:
        stop_talk(EXAMPLE, "rag")

    proof = observed.observations.get("rag")
    assert proof is not None and proof.passed
    # And by the conversation rather than by the check that was there anyway: the direct
    # check only proves the stages load, and being answered proves more than that.
    assert proof.check == "talk.answered"
    assert "answered 1 question(s)" in (proof.detail or "")


def test_the_agent_is_green_off_the_conversation_it_had() -> None:
    """The same claim against the other topology: what proves an agent is being asked one.

    Both reference projects have a check that passes without anybody talking to them --
    `graph.compiles`, `rag.stages_load` -- and neither proves the thing a person cares
    about. A conversation does, which is why it outranks them.
    """
    from framestack_core.observe import run_observations
    from framestack_core.project import read_project

    graph = read_project(AGENT)
    talk_until_answered(AGENT, "agent", "tell me about ravens")
    try:
        observed = run_observations(graph, AGENT, python=sys.executable)
    finally:
        stop_talk(AGENT, "agent")

    proof = observed.observations.get("agent")
    assert proof is not None and proof.passed
    assert proof.check == "talk.answered"
