"""Running the thing, and seeing what ran (P13).

The verbs the product implies and nothing else provided: start it, look at what it printed,
call it, stop it. Three rules are load-bearing and each has a test that would notice if they
were traded away for a convenience:

* **Nothing holds the wire open.** `start` returns once the application answers; logs are
  polled with an offset the caller keeps. A stream would have cost a protocol version and
  frozen the window for as long as a slow process takes.
* **What was started can always be found again.** The process is recorded on disk, so `stop`
  works on one this session never started -- which is the only way a crashed session's
  orphan is ever cleaned up.
* **Flow comes from the run** (Q9). Not parsed out of assembly code, not declared in markup:
  the order a passing test actually went in, and the wiring the framework itself holds.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from aibuilder_core.api import read_graph
from aibuilder_core.runner import (
    RUN_STATE_PATH,
    call_endpoint,
    read_logs,
    run_status,
    start_application,
    stop_application,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
SERVICE = EXAMPLES / "fastapi-service"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A copy of the reference service, and nothing of it left running afterwards."""
    root = tmp_path / "service"
    shutil.copytree(SERVICE, root, ignore=shutil.ignore_patterns("__pycache__", ".aibuilder"))
    try:
        yield root
    finally:
        stop_application(root)


# -- the verbs --------------------------------------------------------------------


def test_an_application_starts_answers_and_stops(project: Path) -> None:
    """The whole loop, in the order a person would do it."""
    started = start_application(project)

    assert started.ok is True, started.detail
    assert started.state is not None
    assert started.state.target == "app.main:app"

    assert run_status(project).ok is True

    answered = call_endpoint(project, "/health")
    assert answered.status == 200
    assert json.loads(answered.body) == {"status": "ok"}

    assert stop_application(project).ok is True
    assert run_status(project).ok is False


def test_starting_twice_adopts_rather_than_doubling(project: Path) -> None:
    """Two servers on two ports, one of them forgotten, is what the record prevents."""
    first = start_application(project)
    second = start_application(project)

    assert first.state is not None and second.state is not None
    assert second.state.port == first.state.port
    assert "already running" in second.detail


def test_stopping_works_on_a_process_this_session_did_not_start(project: Path) -> None:
    """The crashed-session case, which is the only reason the record is on disk.

    Forgetting the process in memory is exactly what a crash does. What survives is the
    file, and `stop` has to work from that alone.
    """
    from aibuilder_core import runner

    started = start_application(project)
    assert started.ok is True
    runner._STARTED_HERE.clear()  # as if this session had never known about it

    assert (project / RUN_STATE_PATH).is_file()
    assert stop_application(project).ok is True
    assert not (project / RUN_STATE_PATH).is_file()


def test_a_record_whose_process_is_gone_is_not_believed(project: Path) -> None:
    """Asked of the operating system, never of a memory."""
    (project / RUN_STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (project / RUN_STATE_PATH).write_text(
        json.dumps({"pid": 999999, "port": 1, "target": "x:y"}), encoding="utf-8"
    )

    status = run_status(project)

    assert status.ok is False
    assert "gone" in status.detail
    assert not (project / RUN_STATE_PATH).is_file()


def test_logs_are_polled_with_an_offset_the_caller_keeps(project: Path) -> None:
    """No stream, no buffer in the core: ask again from where you got to."""
    start_application(project)
    call_endpoint(project, "/health")

    first = read_logs(project)
    assert first.ok is True
    assert first.offset > 0

    call_endpoint(project, "/users")
    second = read_logs(project, first.offset)

    assert "/users" in second.logs
    assert "/health" not in second.logs  # already read; not sent twice
    assert second.offset > first.offset


def test_calling_a_project_that_is_not_running_is_a_result_not_a_crash(project: Path) -> None:
    answered = call_endpoint(project, "/health")

    assert answered.ok is False
    assert answered.status is None


def test_a_project_with_no_application_is_refused_with_the_reason(tmp_path: Path) -> None:
    """A refusal is a normal answer here, the way a rejected knob write is."""
    (tmp_path / "nothing.py").write_text("x = 1\n")

    started = start_application(tmp_path)

    assert started.ok is False
    assert started.state is None


def test_ending_the_session_ends_what_it_started(project: Path) -> None:
    """A session is the sidecar's lifetime; a CLI invocation is not one."""
    from aibuilder_core.runner import stop_everything_started_here

    start_application(project)
    assert run_status(project).ok is True

    stop_everything_started_here()

    assert run_status(project).ok is False


# -- flow (Q9) --------------------------------------------------------------------


def test_a_pipelines_order_is_read_off_the_run() -> None:
    """The RAG stages, in the order a passing test actually went through them.

    Nothing declared this and nothing parsed the assembly code for it. It is what happened.
    """
    payload = read_graph(EXAMPLES / "rag-pipeline", observe=True)
    observed = {
        (edge["source"], edge["target"]) for edge in payload["flow"] if edge["origin"] == "observed"
    }

    assert ("rag.chunking", "rag.embedding") in observed
    assert ("rag.retrieval", "rag.generation") in observed


def test_an_agents_wiring_is_asked_of_the_compiled_graph() -> None:
    """§5.8 again: the library holds its own edges, so the library is what we ask."""
    payload = read_graph(EXAMPLES / "langgraph-agent", observe=True)
    origins = {edge["origin"] for edge in payload["flow"]}

    assert "wiring" in origins
    assert "observed" in origins


def test_there_are_no_flow_arrows_before_a_run() -> None:
    """A path nothing took is dark. That is the same honesty as `unproven`."""
    payload = read_graph(EXAMPLES / "rag-pipeline")

    assert payload["flow"] == []


def test_flow_is_not_an_edge() -> None:
    """Two different relations: a type crossing a boundary, and one node running after another."""
    payload = read_graph(EXAMPLES / "rag-pipeline", observe=True)
    contract_edges = {(edge["source"], edge["target"]) for edge in payload["graph"]["edges"]}
    flow_edges = {(edge["source"], edge["target"]) for edge in payload["flow"]}

    assert flow_edges
    assert not (flow_edges & contract_edges)
