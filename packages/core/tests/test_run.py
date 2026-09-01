"""`Run`: calling one export, and everything it must not do (Phase 5).

Every test here calls the reference project's real exports in a real subprocess. That is the
point: the claim under test is "pressing Run calls the function the convention names", and a
stubbed importer would prove that the plumbing works while proving nothing about the thing a
person presses.

Two of these matter more than the rest, and neither is about a call succeeding:

* **A run colours nothing.** Green is earned by a passing test that executed the code (I-3),
  and a successful call is a person typing a query. If a run could ever write an observation,
  a node would be green because somebody used it -- which is the flow-document defect this
  whole rebuild exists to remove, arriving through a side door.
* **A run is one node.** No traversal, no order, no "and then". The graph is a projection,
  not an executor.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from contract import validate, wire_form

from framestack_core.api import (
    RUN_SCHEMA,
    run_last,
    run_read,
    run_start,
)
from framestack_core.observe import OBSERVATION_PATH
from framestack_core.run import (
    ACTIONS,
    DOCUMENTS_PATH,
    RunOutcome,
    last_run,
    read_run,
    start_run,
    stop_run,
)

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "reference"

#: Long enough for a cold interpreter to import the project on a loaded machine, short enough
#: that a hang fails the suite rather than holding CI open.
PATIENCE = 120


def project(tmp_path: Path, name: str = "project") -> Path:
    """A writable copy. `Run` writes into `.framestack/`; the reference is not ours to."""
    root = tmp_path / name
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def call(root: Path, node: str, action: str, given: dict[str, Any] | None = None) -> RunOutcome:
    """Run it and wait. The polling is the contract (P13), so the helper uses it."""
    started = start_run(root, node, action, given or {})
    assert started.ok, started.detail

    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        answer = read_run(root, node, 0)
        if not answer.running:
            assert answer.outcome is not None, answer.detail
            return answer.outcome
        time.sleep(0.05)
    raise AssertionError("the call did not finish")


def document(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# -- the four kinds, each called through the export its kind requires ------------------------


def test_the_agent_answers_the_message_it_was_given(tmp_path: Path) -> None:
    outcome = call(project(tmp_path), "agent", "run", {"message": "otters"})

    assert outcome.ok, outcome.error
    assert isinstance(outcome.value, str)
    assert "otters" in outcome.value


def test_uploading_a_document_indexes_it_and_a_query_finds_it(tmp_path: Path) -> None:
    """The whole RAG acceptance criterion, as one sentence of Python.

    Two calls and therefore two processes, which is exactly why this is worth asserting: an
    index a person fills in one press and queries in the next has to survive between them.
    """
    root = project(tmp_path)
    paper = document(tmp_path, "otters.txt", "Otters hold hands while they sleep.")

    indexed = call(root, "rag", "index", {"paths": [paper]})
    assert indexed.ok, indexed.error

    found = call(root, "rag", "search", {"query": "otters"})

    assert found.ok, found.error
    assert isinstance(found.value, list) and found.value
    assert "hold hands" in found.value[0]["text"]


def test_an_uploaded_document_appears_in_the_node_s_list(tmp_path: Path) -> None:
    root = project(tmp_path)
    paper = document(tmp_path, "otters.txt", "Otters hold hands while they sleep.")

    call(root, "rag", "index", {"paths": [paper]})

    assert last_run(root, "rag").documents == (paper,)
    # And it is beside the layout and the observation, not in the project's source.
    assert (root / DOCUMENTS_PATH).is_file()


def test_the_same_document_is_not_listed_twice(tmp_path: Path) -> None:
    root = project(tmp_path)
    paper = document(tmp_path, "otters.txt", "Otters hold hands while they sleep.")

    call(root, "rag", "index", {"paths": [paper]})
    call(root, "rag", "index", {"paths": [paper]})

    assert last_run(root, "rag").documents == (paper,)


def test_the_service_answers_a_request_on_a_route_it_has(tmp_path: Path) -> None:
    outcome = call(project(tmp_path), "api", "request", {"method": "GET", "path": "/health"})

    assert outcome.ok, outcome.error
    assert outcome.value["status"] == 200
    assert "framestack reference" in outcome.value["body"]


def test_a_route_the_service_does_not_have_is_the_service_s_answer_and_not_a_failure(
    tmp_path: Path,
) -> None:
    """A 404 is what the application said. The run succeeded; the route did not exist.

    Kept apart deliberately: an interface that turned somebody's 404 into "the run failed"
    would be reporting our opinion of their status code.
    """
    outcome = call(project(tmp_path), "api", "request", {"path": "/nowhere"})

    assert outcome.ok, outcome.error
    assert outcome.value["status"] == 404


def test_a_worker_lists_the_handlers_it_declares_and_runs_one(tmp_path: Path) -> None:
    root = project(tmp_path)

    listed = call(root, "worker", "handlers")
    assert listed.ok, listed.error
    assert listed.value == ["echo", "reindex"]

    handled = call(root, "worker", "handle", {"handler": "echo", "payload": {"hello": "there"}})
    assert handled.ok, handled.error
    assert handled.value == {"hello": "there"}


def test_a_handler_that_is_not_there_says_which_ones_are(tmp_path: Path) -> None:
    outcome = call(project(tmp_path), "worker", "handle", {"handler": "nope", "payload": {}})

    assert not outcome.ok
    assert "echo" in outcome.error and "reindex" in outcome.error


# -- what a run is not ------------------------------------------------------------------------


def test_a_successful_run_colours_nothing(tmp_path: Path) -> None:
    """I-3, stated as the thing that must not happen.

    A call that returned is not evidence. If this file ever appears, a node has gone green
    because somebody pressed a button on it, and the product is Flowise with better prose.
    """
    root = project(tmp_path)

    call(root, "agent", "run", {"message": "otters"})
    call(root, "rag", "search", {"query": "otters"})

    assert not (root / OBSERVATION_PATH).exists()
    assert last_run(root, "agent").outcome is not None


def test_a_run_reaches_exactly_one_node(tmp_path: Path) -> None:
    """No traversal. `agent.run` imports `rag` in this project, and `rag` is still unrun."""
    root = project(tmp_path)

    call(root, "agent", "run", {"message": "otters"})

    assert last_run(root, "rag").outcome is None


def test_every_action_is_an_export_the_convention_already_requires(tmp_path: Path) -> None:
    """The list cannot grow without the convention growing.

    An action that called something other than a required export would be this toolchain
    inspecting an implementation, which is the one thing the parser is forbidden to do.
    """
    from framestack_core.parser import REQUIRED

    for kind, actions in ACTIONS.items():
        assert set(actions.values()) <= set(REQUIRED[kind])


# -- refusals, each of them a result -----------------------------------------------------------


def test_a_kind_is_only_asked_what_its_kind_answers(tmp_path: Path) -> None:
    answer = start_run(project(tmp_path), "rag", "run", {})

    assert not answer.ok
    assert "index, search" in answer.detail


def test_a_file_node_has_nothing_to_call(tmp_path: Path) -> None:
    answer = start_run(project(tmp_path), ".env", "run", {})

    assert not answer.ok
    assert "file" in answer.detail


def test_a_node_nobody_has_heard_of_is_refused_rather_than_attempted(tmp_path: Path) -> None:
    answer = start_run(project(tmp_path), "nowhere", "run", {})

    assert not answer.ok
    assert "nowhere" in answer.detail


def test_an_incomplete_node_is_named_rather_than_imported(tmp_path: Path) -> None:
    """The parser already read this. Spawning a process to rediscover it would be a process
    bought to learn something we know."""
    root = project(tmp_path)
    (root / "agent" / "__init__.py").write_text('"""No run here."""\n', encoding="utf-8")

    answer = start_run(root, "agent", "run", {"message": "hello"})

    assert not answer.ok
    assert "does not export run" in answer.detail


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    answer = start_run(tmp_path / "nothing", "agent", "run", {})

    assert not answer.ok
    assert "no project" in answer.detail


def test_a_second_call_into_the_same_node_is_refused_while_the_first_runs(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    started = start_run(root, "agent", "run", {"message": "otters"})
    assert started.ok

    second = start_run(root, "agent", "run", {"message": "otters"})

    call_ended = read_run(root, "agent", 0)
    while call_ended.running:
        time.sleep(0.05)
        call_ended = read_run(root, "agent", 0)

    assert not second.ok
    assert "already running" in second.detail


def test_nothing_is_known_before_a_node_has_been_run(tmp_path: Path) -> None:
    answer = last_run(project(tmp_path), "agent")

    assert answer.ok
    assert answer.outcome is None
    assert answer.documents == ()


def test_stopping_something_that_is_not_running_is_a_result(tmp_path: Path) -> None:
    answer = stop_run(project(tmp_path), "agent")

    assert not answer.ok
    assert "nothing is running" in answer.detail


# -- what the child leaves behind ------------------------------------------------------------


def test_the_project_s_own_output_is_polled_with_an_offset_the_caller_keeps(
    tmp_path: Path,
) -> None:
    """P13, and the reason the panel can show a long call while it happens."""
    root = project(tmp_path)
    (root / "agent" / "__init__.py").write_text(
        '"""An agent that says something on the way."""\n\n\n'
        "def run(message: str, **kw: object) -> str:\n"
        '    print("thinking about " + message)\n'
        '    return "done"\n',
        encoding="utf-8",
    )

    call(root, "agent", "run", {"message": "otters"})

    whole = read_run(root, "agent", 0)
    assert "thinking about otters" in whole.output
    assert read_run(root, "agent", whole.offset).output == ""


def test_a_raising_export_comes_back_as_its_own_traceback(tmp_path: Path) -> None:
    """Verbatim, and never repaired into something plausible. It is the way out of the state
    the code is actually in."""
    root = project(tmp_path)
    (root / "agent" / "__init__.py").write_text(
        '"""An agent that does not work."""\n\n\n'
        "def run(message: str, **kw: object) -> str:\n"
        '    raise ValueError("no model configured")\n',
        encoding="utf-8",
    )

    outcome = call(root, "agent", "run", {"message": "otters"})

    assert not outcome.ok
    assert "ValueError: no model configured" in outcome.error


def test_the_answer_outlives_the_window_that_asked_for_it(tmp_path: Path) -> None:
    """A closed window has to find the result when it comes back, so it is on disk."""
    root = project(tmp_path)
    outcome = call(root, "agent", "run", {"message": "otters"})

    from framestack_core import run as module

    module._CALLS.clear()

    assert last_run(root, "agent").outcome == outcome


def test_the_last_answer_survives_the_start_of_the_next_call(tmp_path: Path) -> None:
    """ "It is running again" is not "it has never been run", and a panel that blanked itself
    would be saying the second thing."""
    root = project(tmp_path)
    call(root, "agent", "run", {"message": "otters"})

    started = start_run(root, "agent", "run", {"message": "penguins"})
    assert started.ok
    assert read_run(root, "agent", 0).outcome is not None

    while read_run(root, "agent", 0).running:
        time.sleep(0.05)


# -- the contract ------------------------------------------------------------------------------


def test_every_verb_matches_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)

    validate(wire_form(run_last(root, "agent")), RUN_SCHEMA)
    validate(wire_form(run_start(root, "agent", "run", {"message": "otters"})), RUN_SCHEMA)

    answer = run_read(root, "agent", 0)
    while answer["running"]:
        time.sleep(0.05)
        answer = run_read(root, "agent", 0)
    validate(wire_form(answer), RUN_SCHEMA)

    # And a refusal, which is a result and has to be the same shape as one.
    validate(wire_form(run_start(root, "rag", "run", {})), RUN_SCHEMA)
