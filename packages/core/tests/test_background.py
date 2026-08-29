"""Work that happens after the request, and the two different things that prove it (P14).

A background task is the case every earlier phase's evidence rule was aimed at. It cannot be
called with invented input, it runs in a process the application never starts, and the thing
that makes it *background* -- the queue between the caller and the work -- is a service that
may not be up. So the phase is mostly about keeping two claims apart:

* **the task works** -- proven by a run that entered it, which is the project's own tests
  (Q7). They may well run it in-process; that is honest about what it proves;
* **the queue delivers** -- proven by the broker answering and a worker replying to a ping.

Neither may stand in for the other, and a graph that let one do so would be green while
nothing was ever actually delivered.

Three older rules are re-tested here rather than assumed, because a new runner is exactly
where they get quietly dropped: nothing is started implicitly (P11), the command is asked of
the project rather than guessed (§5.8), and what was started can be found again (P13).
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from framestack_core.api import read_graph
from framestack_core.observe import run_observations
from framestack_core.project import read_project
from framestack_core.runner import (
    WORKER_STATE_PATH,
    start_worker,
    stop_worker,
    worker_status,
)
from framestack_core.verdict import Verdict

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
WORKER = EXAMPLES / "service-with-worker"


# -- the graph --------------------------------------------------------------------


def test_background_work_is_a_subsystem_of_its_own() -> None:
    """Two top-level groups, not one: a task outlives the request that queued it.

    Making the queue a member of the service would say the service owns it -- and then a
    worker would look like something the application starts, which is the one thing it is
    not.
    """
    graph = read_project(WORKER)

    service = graph.node("api")
    workers = graph.node("work")

    assert service is not None and workers is not None
    assert workers.kind == "queue.workers"
    assert "work" not in service.members
    assert {"work.queue", "work.report", "work.sweep", "work.schedule"} <= set(workers.members)


def test_the_queues_knobs_are_on_the_queue_and_not_on_the_service() -> None:
    """`concurrency` is what a worker is run with, so it belongs where the button is."""
    queue = read_project(WORKER).node("work.queue")

    assert queue is not None
    assert {knob.name for knob in queue.knobs} >= {"broker_url", "concurrency"}


# -- the evidence -----------------------------------------------------------------


def test_a_task_is_proven_by_a_run_that_entered_it_not_by_the_registry() -> None:
    """The registry says a worker *could* run it. Only a run says it works.

    The check that asks celery for the registry exists and is useful -- but where a test
    exercised the task, that evidence outranks it, and the check name in the observation is
    how you can tell which one answered.
    """
    run = run_observations(read_project(WORKER), WORKER)

    report = run.observations["work.report"]

    assert report.passed is True
    assert report.check == "tests.exercised"


def test_a_queue_whose_broker_is_down_is_unproven_and_names_the_button() -> None:
    """Not red. The configuration is not wrong because nothing is listening yet (P11)."""
    run = run_observations(read_project(WORKER), WORKER)

    assert "work.queue" not in run.observations
    assert "the broker does not answer" in run.skipped["work.queue"]
    assert "compose" in run.skipped["work.queue"]


def test_with_the_broker_down_nothing_in_the_project_is_broken() -> None:
    """The standing promise since P12, on the project that has a queue in it."""
    from framestack_core.gate import check_graph

    graph = read_project(WORKER)
    run = run_observations(graph, WORKER)
    verdicts = check_graph(graph, observations=run.observations).verdicts

    assert Verdict.BROKEN.value not in verdicts.values()
    assert Verdict.GREEN.value in verdicts.values()


def test_the_schedule_is_checked_against_what_the_queue_actually_knows() -> None:
    """An entry naming a task nothing registered is a job that fails at 3am, forever."""
    run = run_observations(read_project(WORKER), WORKER)

    schedule = run.observations["work.schedule"]

    assert schedule.passed is True
    assert "registered tasks" in schedule.detail


def test_queueing_and_running_are_one_flow_arrow_across_two_subsystems() -> None:
    """Q9 on the case it was hardest for: the arrow crosses a process boundary.

    Nothing declared this edge and nothing parsed `.delay(...)` out of the route. A test
    queued a report, the task ran, and the run is what drew the arrow.
    """
    payload = read_graph(WORKER, observe=True)

    observed = {
        (edge["source"], edge["target"]) for edge in payload["flow"] if edge["origin"] == "observed"
    }

    assert ("reports.request", "work.report") in observed


# -- the worker -------------------------------------------------------------------


def test_a_worker_is_refused_rather_than_started_when_the_broker_is_down() -> None:
    """P11 held where it is easiest to lose: nothing starts a service on the way past.

    A worker started against a dead broker sits there retrying and looks, from the outside,
    exactly like one that is working. Refusing names the button instead.
    """
    started = start_worker(WORKER)

    assert started.ok is False
    assert "start them from the compose file's node" in started.detail
    assert started.state is None
    assert not (WORKER / WORKER_STATE_PATH).exists()


def test_a_project_with_no_queue_is_refused_with_the_reason(tmp_path: Path) -> None:
    (tmp_path / "nothing.py").write_text("x = 1\n")

    started = start_worker(tmp_path)

    assert started.ok is False
    assert started.state is None


def test_where_the_queue_is_comes_from_the_project(tmp_path: Path) -> None:
    """§5.8: `-A proj` is a convention, and a convention is wrong on the first odd layout."""
    from framestack_core.environment import project_interpreter
    from framestack_core.runner import _ask_project, _project_modules

    root = queue_project(tmp_path)
    interpreter, _ = project_interpreter(root)

    answer = _ask_project(root, interpreter, _project_modules(root), "queue")

    assert answer["target"] == "work.queue:celery_app"
    assert answer["concurrency"] == 1


# -- the worker, actually running -------------------------------------------------


def queue_project(root: Path) -> Path:
    """A queue whose broker is a directory.

    Celery's filesystem transport is a real broker between real processes -- no server, no
    container, nothing skipped. What it buys is that the interesting path can be tested
    everywhere rather than only where someone has redis running.
    """
    (root / "work").mkdir(parents=True, exist_ok=True)
    (root / "work" / "__init__.py").write_text("")
    (root / "work" / "queue.py").write_text(
        textwrap.dedent(
            '''
            """A queue whose broker is a folder on disk."""

            import os
            from typing import Annotated

            from celery import Celery

            from bp import Param, editable, generated, node


            # The folder is resolved from this file, never from the working directory:
            # the worker runs inside the project and the process that pings it does not,
            # so a relative broker would be two different brokers.
            HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


            @node(id="work.queue", kind="queue.app", title="Task queue")
            class TaskQueue:
                broker_dir: Annotated[str, Param(label="Broker folder")] = "broker"
                concurrency: Annotated[int, Param(min=1, max=4)] = 1

                @generated()
                def build(self) -> Celery:
                    # GENERATED. Queue assembly; edited through the graph, not by hand.
                    root = os.path.join(HERE, self.broker_dir)
                    for name in ("messages", "control"):
                        os.makedirs(os.path.join(root, name), exist_ok=True)
                    app = Celery("work", broker="filesystem://")
                    app.conf.worker_concurrency = self.concurrency
                    app.conf.broker_transport_options = {
                        "data_folder_in": os.path.join(root, "messages"),
                        "data_folder_out": os.path.join(root, "messages"),
                        "control_folder": os.path.join(root, "control"),
                    }
                    return app


            queue = TaskQueue()
            celery_app = queue.build()


            @node(id="work.echo", kind="queue.task", title="Echo")
            @editable(signature_locked=True)
            def echo(value: int) -> int:
                # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
                return value


            @generated()
            def register_tasks(app: object) -> None:
                # GENERATED. Task registration; edited through the graph, not by hand.
                app.task(name="work.echo")(echo)  # type: ignore[attr-defined]


            register_tasks(celery_app)
            '''
        ).lstrip()
    )
    (root / "work" / "__node__.py").write_text(
        textwrap.dedent(
            '''
            """The background work."""

            from bp import group_node
            from work.queue import TaskQueue, echo

            workers = group_node(
                id="work", kind="queue.workers", title="Work", members=[TaskQueue, echo]
            )
            '''
        ).lstrip()
    )
    return root


@pytest.fixture
def queued(tmp_path: Path) -> Path:
    root = queue_project(tmp_path / "project")
    try:
        yield root
    finally:
        stop_worker(root)


def test_a_worker_starts_answers_the_queue_and_stops(queued: Path) -> None:
    """The whole loop. Readiness is a reply to a ping, never a line in a log.

    A worker publishes no port, so P13's question -- does it answer where it said it would?
    -- is put to the queue instead. "ready" printed on stdout is a string the process chose
    to print; a reply that came back through the broker is the thing itself.
    """
    started = start_worker(queued)

    assert started.ok is True, started.detail
    assert started.state is not None
    assert started.state.target == "work.queue:celery_app"
    assert "--concurrency" in started.state.command

    assert worker_status(queued).ok is True

    assert stop_worker(queued).ok is True
    assert worker_status(queued).ok is False


def test_starting_twice_adopts_rather_than_doubling(queued: Path) -> None:
    """Two workers, one of them forgotten, is what the record on disk prevents."""
    first = start_worker(queued)
    second = start_worker(queued)

    assert first.state is not None and second.state is not None
    assert second.state.pid == first.state.pid
    assert "already running" in second.detail


def test_stopping_works_on_a_worker_this_session_did_not_start(queued: Path) -> None:
    """The crashed-session case, which is the only reason the record is on disk (P13)."""
    from framestack_core import runner

    assert start_worker(queued).ok is True
    runner._STARTED_HERE.clear()  # as if this session had never known about it

    assert (queued / WORKER_STATE_PATH).is_file()
    assert stop_worker(queued).ok is True
    assert not (queued / WORKER_STATE_PATH).is_file()


def test_the_workers_output_is_polled_like_everything_else(queued: Path) -> None:
    from framestack_core.runner import read_worker_logs

    start_worker(queued)

    first = read_worker_logs(queued)

    assert first.ok is True
    assert first.offset > 0
    assert read_worker_logs(queued, first.offset).logs == ""  # already read; not sent twice


def test_the_application_and_the_worker_are_recorded_apart(queued: Path) -> None:
    """Separate processes with separate lifetimes, so separate records.

    One record for both would mean stopping the application stopped the worker, and a
    project can perfectly well run one without the other.
    """
    from framestack_core.runner import RUN_STATE_PATH

    assert start_worker(queued).ok is True

    assert (queued / WORKER_STATE_PATH).is_file()
    assert not (queued / RUN_STATE_PATH).exists()


def test_ending_the_session_ends_the_worker_it_started(queued: Path) -> None:
    """A session is the sidecar's lifetime, and it takes its worker with it (P13)."""
    from framestack_core.runner import stop_everything_started_here

    assert start_worker(queued).ok is True

    stop_everything_started_here()

    assert worker_status(queued).ok is False


def test_the_new_verbs_are_methods_in_the_core(queued: Path) -> None:
    """The extension point is `HANDLERS`, never a new command in the Rust shell.

    A capability that arrived as a Tauri command would put logic in the transport layer,
    and the shell would stop being transport.
    """
    from framestack_core.handlers import dispatch

    answer = dispatch("work.status", {"project": str(queued)})

    assert answer["ok"] is False
    assert answer["detail"] == "no worker running"


# -- the example, whole -----------------------------------------------------------


def test_the_example_still_reads_the_same_after_it_is_copied(tmp_path: Path) -> None:
    """Nothing in the graph depends on where the project sits."""
    root = tmp_path / "copy"
    shutil.copytree(WORKER, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))

    here = {node.id: node.kind for node in read_project(root).nodes}
    there = {node.id: node.kind for node in read_project(WORKER).nodes}

    assert here == there
