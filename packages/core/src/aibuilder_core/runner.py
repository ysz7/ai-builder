"""Checks for the nodes the probe cannot look at.

`probe.py` is the module that imports the user's project; a `Dockerfile` imports nothing and
a compose file is not Python. Their checks run here instead, in the toolchain's own process,
and the separation is the point: the probe's one dangerous property -- it executes a
stranger's code -- must not spread to a check that only needs to ask docker a question
(architecture §5.7).

Everything in here follows §5.8. Nothing reads a file: what the compose file says is asked
of `docker compose`, and whether a service is usable is answered by connecting to the port
it publishes.

**A check never starts anything.** A compose file whose services are down is not a broken
node -- it is an unproven one, and the reason names the button that would prove it (P11).

The rest of this module is the running itself (P13): starting the application, reading what
it printed, calling it, and stopping it. Three rules shape it:

* **Nothing blocks the wire.** The protocol is one request and one answer with nothing in
  between, so `start` returns as soon as the application answers and never streams. Logs and
  status are *asked for*, which costs a poll and keeps a slow process from freezing the
  window. Pushing events would need a second message shape and a protocol version; it can be
  added later without taking anything back, which is why it is not being added now.
* **What we start, we can find again.** The process is recorded in `.aibuilder/run.json` --
  tooling state beside the snapshot and the agent log, never something the graph reads a
  fact out of. A session that ends leaves nothing running; a session that *crashed* leaves a
  record the next one can act on, which is the only way an orphan is ever cleaned up.
* **The command is asked of the project, never guessed.** "main:app" is a convention that is
  wrong the moment a project is laid out differently, so the application's location comes
  from the probe importing it and saying where it found it (§5.8).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aibuilder_core.environment import Environment, describe_environment
from aibuilder_core.ir import Graph, Node
from aibuilder_core.kinds import CarrierType, lookup
from aibuilder_core.verdict import Observation

__all__ = [
    "ArtifactRun",
    "CallResult",
    "CommandList",
    "command_status",
    "project_commands",
    "read_command_logs",
    "start_command",
    "stop_command",
    "RunState",
    "artifact_nodes",
    "ServerResult",
    "build_image",
    "call_endpoint",
    "call_server_tool",
    "check_artifacts",
    "index_pipeline",
    "inspect_server",
    "read_logs",
    "read_worker_logs",
    "run_status",
    "start_application",
    "start_worker",
    "stop_application",
    "stop_worker",
    "worker_status",
]

#: Where the running process is recorded, beside the snapshot and the agent log. Tooling
#: state: delete it and the project is unchanged, and nothing draws a graph from it.
RUN_STATE_PATH = Path(".aibuilder") / "run.json"

#: Where the application's output goes. A file rather than a pipe held in memory: the core
#: must not have to stay alive for output to survive, and a crash must leave it readable.
RUN_LOG_PATH = Path(".aibuilder") / "run.log"

#: The same two files for the worker (P14). A separate record because it is a separate
#: process with a separate lifetime: an application can run with no worker behind it, and a
#: worker can outlive the application it was started beside.
WORKER_STATE_PATH = Path(".aibuilder") / "worker.json"
WORKER_LOG_PATH = Path(".aibuilder") / "worker.log"

#: How long to wait for the application to answer on its port before calling it a failure.
STARTUP_TIMEOUT_S = 30

#: How long indexing may take. Generous, and deliberately so: embedding a corpus is the one
#: verb here that does real work rather than asking a question, and a store that is slow is
#: not a store that is broken.
INDEX_TIMEOUT_S = 600

#: What this session started, so that ending the session ends them. Sessions are the unit:
#: a process started here is not left behind for someone to find in a month. The `Popen` is
#: kept because a child has to be **reaped**, not merely killed: a dead child nobody waited
#: on is a zombie, and a zombie answers "yes" when asked whether it is still there.
_STARTED_HERE: dict[tuple[str, str], subprocess.Popen[bytes]] = {}


class ArtifactRun:
    """What could be proven about the artifact nodes, and why the rest could not."""

    def __init__(self) -> None:
        self.observations: dict[str, Observation] = {}
        self.skipped: dict[str, str] = {}

    def passed(self, node: str, check: str, detail: str) -> None:
        self.observations[node] = Observation(passed=True, check=check, detail=detail)

    def failed(self, node: str, check: str, detail: str) -> None:
        self.observations[node] = Observation(passed=False, check=check, detail=detail)

    def skip(self, node: str, detail: str) -> None:
        self.skipped[node] = detail


def artifact_nodes(graph: Graph) -> tuple[Node, ...]:
    """The nodes carried by a file. The probe is never told about these."""
    return tuple(node for node in graph.nodes if node.carrier_type == CarrierType.FILE.value)


def check_artifacts(
    graph: Graph, project: Path | str, environment: Environment | None = None
) -> ArtifactRun:
    """Run each artifact node's check. Reads and asks; changes nothing."""
    run = ArtifactRun()
    nodes = artifact_nodes(graph)
    if not nodes:
        return run

    state = environment or describe_environment(project)

    for node in nodes:
        kind = lookup(node.kind)
        if kind is None:
            continue  # an unregistered kind has no check; the gate already said so
        check = CHECKS.get(kind.check)
        if check is None:
            run.skip(node.id, "no runner for this check yet")
            continue
        check(run, node, state)
    return run


def _services_answer(run: ArtifactRun, node: Node, environment: Environment) -> None:
    """The services this file declares, and whether anything answers where they publish."""
    check = "docker.services_answer"

    if environment.docker_unavailable:
        run.skip(node.id, environment.docker_unavailable)
        return
    if not environment.services:
        run.skip(node.id, "this file declares no services")
        return

    published = [service for service in environment.services if service.ports]
    if not published:
        run.skip(node.id, "no declared service publishes a port, so none can be reached from here")
        return

    missing = environment.services_missing
    if missing:
        # Not a failure: the file is fine and the services are simply not up. The reason
        # names what would prove it, which is the button on this node (P11).
        run.skip(
            node.id,
            f"nothing answers where these services publish: {', '.join(missing)}"
            " -- start them from this node",
        )
        return

    run.passed(node.id, check, f"all {len(published)} declared service(s) answer")


def _image_referenced(run: ArtifactRun, node: Node, environment: Environment) -> None:
    """Is this Dockerfile the one a declared service builds from?

    The wiring question, and the same one route mounting asks: declared is not enough, it
    has to be the file something actually builds. Asked of `docker compose config`, so a
    Dockerfile that is built by hand or by CI is unproven here rather than wrong -- this
    project has nothing that says otherwise.
    """
    check = "docker.image_referenced"

    if environment.docker_unavailable:
        run.skip(node.id, environment.docker_unavailable)
        return

    building = [
        service.name
        for service in environment.services
        if service.dockerfile and Path(service.dockerfile).name == Path(node.carrier).name
    ]
    if not building:
        run.skip(node.id, "no declared service builds from this file")
        return

    run.passed(node.id, check, f"built by the service(s): {', '.join(sorted(building))}")


CHECKS = {
    "docker.services_answer": _services_answer,
    "docker.image_referenced": _image_referenced,
}


# -- running the application ------------------------------------------------------


@dataclass(frozen=True)
class RunState:
    """A process this toolchain started, as recorded on disk."""

    pid: int
    port: int
    target: str
    command: tuple[str, ...] = ()
    started_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "port": self.port,
            "target": self.target,
            "command": list(self.command),
            "started_at": self.started_at,
        }


@dataclass(frozen=True)
class RunResult:
    """The answer to every verb here. Refusals are results, never protocol faults."""

    ok: bool
    detail: str
    state: RunState | None = None
    logs: str = ""
    #: Where the reader got to, so the next poll asks for what came after it.
    offset: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "state": None if self.state is None else self.state.as_dict(),
            "logs": self.logs,
            "offset": self.offset,
        }


@dataclass(frozen=True)
class CallResult:
    """What the running application answered when it was called."""

    ok: bool
    detail: str
    status: int | None = None
    body: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "status": self.status, "body": self.body}


def _state_path(project: Path, state: Path = RUN_STATE_PATH) -> Path:
    return project / state


def _read_state(project: Path, state: Path = RUN_STATE_PATH) -> RunState | None:
    path = _state_path(project, state)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RunState(
            pid=int(payload["pid"]),
            port=int(payload["port"]),
            target=str(payload.get("target", "")),
            command=tuple(str(part) for part in payload.get("command", ())),
            started_at=str(payload.get("started_at", "")),
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _write_state(project: Path, state: RunState, path: Path = RUN_STATE_PATH) -> None:
    target = _state_path(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state.as_dict()), encoding="utf-8")


def _forget(project: Path, state: Path = RUN_STATE_PATH) -> None:
    with contextlib.suppress(OSError):
        _state_path(project, state).unlink()


def _reap(pid: int) -> None:
    """Collect the process if it happens to be ours.

    A child that was killed and never waited on stays in the process table as a zombie, and
    a zombie answers "yes" to `kill(pid, 0)` forever. When the process belongs to a session
    that is gone it is not ours to reap and the operating system has already done it -- so
    "not our child" is a normal answer here, not an error.
    """
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)


def _alive(pid: int) -> bool:
    """Is this process still there? Asked of the operating system, not remembered."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive and not ours to signal
    return True


def _answers(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _free_port() -> int:
    """A port nothing is using, chosen by asking the operating system for one."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _ask_project(
    project: Path,
    python: str,
    modules: list[str],
    ask: str,
    timeout_s: int = 60,
    **extra: Any,
) -> dict[str, Any]:
    """Put a question to the project, in the project's own interpreter (§5.8).

    Every question the runner needs answered -- where the application is, where the queue
    is, whether a worker is listening -- is a question only the project can answer, and it
    is answered where the project lives: in the probe's process, never in this one.
    """
    from aibuilder_core.observe import probe_script

    plan = {"project": str(project.resolve()), "modules": modules, "ask": ask, **extra}
    try:
        completed = subprocess.run(
            [python, str(probe_script())],
            input=json.dumps(plan),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"detail": f"the project could not be asked ({ask}): {exc}"}

    if completed.returncode != 0:
        return {"detail": f"the project could not be imported to answer ({ask})"}

    try:
        answer = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"detail": f"the project gave no readable answer ({ask})"}
    return dict(answer)


def _project_modules(root: Path) -> list[str]:
    """The modules the graph already knows about -- the same set the checks import."""
    from aibuilder_core.observe import build_plan
    from aibuilder_core.project import read_project

    listed = build_plan(read_project(root), root).get("modules", [])
    return [str(name) for name in listed] if isinstance(listed, list) else []


def _application_target(project: Path, python: str, modules: list[str]) -> tuple[str | None, str]:
    """Where the application is, asked of the project through the probe."""
    answer = _ask_project(project, python, modules, "application")
    return answer.get("target"), str(answer.get("detail", ""))


def start_application(
    project: Path | str, python: str | None = None, port: int | None = None
) -> RunResult:
    """Start the project's application, and return once it answers.

    Returns rather than streams: the wire carries one answer per request, and a start that
    held it open would freeze everything else for as long as the application takes to come
    up. What it waits for is the port answering -- not the process existing, which proves
    nothing, and not a log line, which is a string a project can print whenever it likes.
    """
    from aibuilder_core.environment import project_interpreter

    root = Path(project).resolve()
    existing = _read_state(root)
    if existing and _alive(existing.pid):
        # Adopting rather than starting a second one. Two servers on two ports, one of them
        # forgotten, is exactly the mess the state file exists to prevent.
        return RunResult(True, f"already running on port {existing.port}", existing)
    if existing:
        _forget(root)

    interpreter, _ = project_interpreter(root, python)
    modules = _project_modules(root)

    target, detail = _application_target(root, interpreter, modules)
    if target is None:
        return RunResult(False, detail or "this project has no application to run")

    chosen = port or _free_port()
    log = root / RUN_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    command = (interpreter, "-m", "uvicorn", target, "--port", str(chosen), "--log-level", "info")

    with log.open("wb") as sink:
        process = subprocess.Popen(  # noqa: S603 -- the command is ours, built above
            command,
            cwd=root,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return RunResult(
                False,
                f"the application exited immediately ({process.returncode}); see the logs",
                logs=_tail(log),
            )
        if _answers(chosen):
            state = RunState(
                pid=process.pid,
                port=chosen,
                target=target,
                command=command,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            _write_state(root, state)
            _STARTED_HERE[(str(root), RUN_STATE_PATH.name)] = process
            return RunResult(True, f"listening on port {chosen}", state)
        time.sleep(0.1)

    _terminate(process.pid, process)
    return RunResult(
        False, f"the application did not answer within {STARTUP_TIMEOUT_S}s", logs=_tail(log)
    )


def _tail(log: Path, limit: int = 4000) -> str:
    """The end of the log. A badge is not a place to read a megabyte."""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _terminate(
    pid: int, process: subprocess.Popen[bytes] | None = None, grace_s: float = 5.0
) -> bool:
    """Ask the process to stop, then insist -- and reap it if it is ours.

    Reaping matters: a child that was killed but never waited on stays in the table as a
    zombie, and every "is it alive?" answers yes. A process from a previous session is not
    ours to reap; the operating system does that for us once it is gone.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    if process is not None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=grace_s)
            return True
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=grace_s)
        return process.poll() is not None

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        _reap(pid)
        if not _alive(pid):
            return True
        time.sleep(0.1)

    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.1)
    _reap(pid)
    return not _alive(pid)


def run_status(project: Path | str) -> RunResult:
    """Is it running? Asked of the operating system and the port, never of a memory.

    A recorded process that is gone -- the machine restarted, someone killed it -- is not
    running, and the record is cleared rather than believed.
    """
    root = Path(project).resolve()
    state = _read_state(root)
    if state is None:
        return RunResult(False, "not running")

    if not _alive(state.pid):
        _forget(root)
        return RunResult(False, "not running (the recorded process is gone)")
    if not _answers(state.port):
        return RunResult(
            False, f"process {state.pid} is alive but nothing answers on {state.port}", state
        )
    return RunResult(True, f"listening on port {state.port}", state)


def stop_application(project: Path | str) -> RunResult:
    """Stop what was started, whoever started it -- this session or a crashed one."""
    return _stop_recorded(Path(project).resolve(), RUN_STATE_PATH)


def _stop_recorded(root: Path, state_path: Path) -> RunResult:
    """The stopping itself, shared by the application and the worker.

    One implementation because there is one rule: the record on disk is what is acted on,
    so a process this session never started is stopped exactly like one it did.
    """
    state = _read_state(root, state_path)
    if state is None:
        return RunResult(False, "nothing to stop")

    key = (str(root), state_path.name)
    stopped = _terminate(state.pid, _STARTED_HERE.get(key))
    _forget(root, state_path)
    _STARTED_HERE.pop(key, None)
    if not stopped:
        return RunResult(False, f"process {state.pid} would not stop", state)
    return RunResult(True, "stopped")


def read_logs(project: Path | str, offset: int = 0, log_path: Path = RUN_LOG_PATH) -> RunResult:
    """What the application has printed since `offset`.

    Polled, not pushed. The caller keeps the offset and asks again; nothing is buffered in
    the core, so a UI that stops asking costs nothing and a crash loses nothing that was
    already written.
    """
    root = Path(project).resolve()
    log = root / log_path
    if not log.is_file():
        return RunResult(False, "there is no log; nothing has been started here", offset=0)

    try:
        with log.open("rb") as handle:
            handle.seek(max(offset, 0))
            chunk = handle.read()
            return RunResult(
                True, "", logs=chunk.decode("utf-8", errors="replace"), offset=handle.tell()
            )
    except OSError as exc:
        return RunResult(False, f"the log could not be read: {exc}", offset=offset)


def call_endpoint(project: Path | str, path: str = "/", method: str = "GET") -> CallResult:
    """Call the running application and show what came back.

    The verb the product implies and nothing else provides: a person looking at a route node
    wants to press it. It calls the process that is actually running -- not a TestClient, not
    an imported app -- so what comes back is what a client would get.
    """
    status = run_status(project)
    if not status.ok or status.state is None:
        return CallResult(False, status.detail)

    url = f"http://127.0.0.1:{status.state.port}{path if path.startswith('/') else '/' + path}"
    request = urllib.request.Request(url, method=method.upper())  # noqa: S310 -- localhost only
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
            return CallResult(True, f"{method.upper()} {path}", response.status, body[:4000])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return CallResult(True, f"{method.upper()} {path}", exc.code, body[:4000])
    except urllib.error.URLError as exc:
        return CallResult(False, f"the application did not answer: {exc.reason}")


def build_image(project: Path | str) -> RunResult:
    """Build the images the compose file declares -- the button on the `Dockerfile` node."""
    from aibuilder_core.environment import _docker, compose_file

    root = Path(project).resolve()
    file = compose_file(root)
    if file is None:
        return RunResult(False, "this project declares no services to build")

    code, out, error = _docker(root, "compose", "-f", str(file), "build", timeout=900)
    if code != 0:
        return RunResult(False, error or "docker compose build failed", logs=out[-4000:])
    return RunResult(True, "image(s) built", logs=out[-4000:])


# -- running the worker (P14) -----------------------------------------------------
#
# A worker is the same machinery as the application with one thing different, and the
# difference is the whole phase: it publishes no port. P13 could ask a socket whether the
# thing it started was up; here the equivalent question goes to the queue -- has anything
# answered it? -- because a log line saying "ready" is a string a process chose to print.
#
# It also refuses to start when the broker is down instead of bringing it up. Nothing in
# this toolchain starts a service implicitly (P11), and a worker started against a dead
# broker would sit there retrying while looking, from the outside, exactly like one that
# is working.

#: How long to wait for a worker to answer the queue. Longer than the application's window
#: because the first answer travels through the broker and back.
WORKER_TIMEOUT_S = 40


def start_worker(project: Path | str, python: str | None = None) -> RunResult:
    """Start a worker for the project's queue, and return once it answers.

    Refuses rather than improvises: no queue, no worker; no broker, no worker. Both come
    back as results with the reason and the button that would fix them.
    """
    from aibuilder_core.environment import describe_environment

    root = Path(project).resolve()
    existing = _read_state(root, WORKER_STATE_PATH)
    if existing and _alive(existing.pid):
        return RunResult(True, f"a worker is already running for {existing.target}", existing)
    if existing:
        _forget(root, WORKER_STATE_PATH)

    environment = describe_environment(root, python)
    if environment.incomplete:
        # The broker is a declared service that is not up. Starting it on the way past is
        # exactly what P11 forbids, so this says which button to press instead.
        return RunResult(
            False,
            f"{environment.incomplete} -- start them from the compose file's node,"
            " then start the worker",
        )

    interpreter = environment.interpreter
    modules = _project_modules(root)
    answer = _ask_project(root, interpreter, modules, "queue")
    target = answer.get("target")
    if not target:
        return RunResult(False, str(answer.get("detail") or "this project has no queue to work"))

    concurrency = int(answer.get("concurrency") or 0)
    # Celery's worker command, and only celery's: the `queue.*` kinds are celery-shaped and
    # say so in `kinds.TECHNOLOGIES`. A second queue technology is a second registry entry
    # with its own command here -- the cost per technology the registry exists to charge.
    log = root / WORKER_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    command = (
        interpreter,
        "-m",
        "celery",
        "-A",
        str(target),
        "worker",
        "--loglevel",
        "info",
        *(("--concurrency", str(concurrency)) if concurrency else ()),
    )

    with log.open("wb") as sink:
        process = subprocess.Popen(  # noqa: S603 -- the command is ours, built above
            command,
            cwd=root,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    ready = _ask_project(
        root,
        interpreter,
        modules,
        "queue_ready",
        timeout_s=WORKER_TIMEOUT_S + 20,
        wait_s=WORKER_TIMEOUT_S,
    )
    if not ready.get("ready"):
        if process.poll() is not None:
            _terminate(process.pid, process)
            return RunResult(
                False,
                f"the worker exited immediately ({process.returncode}); see the logs",
                logs=_tail(log),
            )
        # Alive but silent is worse than dead: it looks like a running worker and does no
        # work. Stopping it is the honest end to a start that did not succeed.
        _terminate(process.pid, process)
        return RunResult(
            False,
            f"the worker did not answer the queue within {WORKER_TIMEOUT_S}s{_because(ready)}",
            logs=_tail(log),
        )

    state = RunState(
        pid=process.pid,
        port=0,  # a worker publishes nothing; the queue is how it is reached
        target=str(target),
        command=command,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    _write_state(root, state, WORKER_STATE_PATH)
    _STARTED_HERE[(str(root), WORKER_STATE_PATH.name)] = process
    return RunResult(True, f"{ready.get('detail', 'a worker')} answering {target}", state)


def _because(answer: dict[str, Any]) -> str:
    """The project's own reason, in brackets, or nothing at all when it gave none."""
    detail = str(answer.get("detail") or "")
    return f" ({detail})" if detail else ""


def worker_status(project: Path | str, python: str | None = None) -> RunResult:
    """Is a worker running? Asked of the operating system, then of the queue itself.

    Both questions, because either answer alone lies in a way that matters: a process that
    is alive may have lost the broker, and a queue that answers may be answering a worker
    somebody else started.
    """
    from aibuilder_core.environment import project_interpreter

    root = Path(project).resolve()
    state = _read_state(root, WORKER_STATE_PATH)
    if state is None:
        return RunResult(False, "no worker running")

    if not _alive(state.pid):
        _forget(root, WORKER_STATE_PATH)
        return RunResult(False, "no worker running (the recorded process is gone)")

    interpreter, _ = project_interpreter(root, python)
    ready = _ask_project(
        root, interpreter, _project_modules(root), "queue_ready", timeout_s=30, wait_s=2
    )
    if not ready.get("ready"):
        return RunResult(
            False,
            f"process {state.pid} is alive but nothing answers the queue{_because(ready)}",
            state,
        )
    return RunResult(True, f"{ready.get('detail', 'a worker')} answering {state.target}", state)


def stop_worker(project: Path | str) -> RunResult:
    """Stop the worker -- this session's, or one a crashed session left behind."""
    return _stop_recorded(Path(project).resolve(), WORKER_STATE_PATH)


def read_worker_logs(project: Path | str, offset: int = 0) -> RunResult:
    """What the worker has printed since `offset`. Polled, exactly like the application's."""
    return read_logs(project, offset, WORKER_LOG_PATH)


# -- the MCP verbs (P15) ----------------------------------------------------------
#
# Connecting is an **action**, never a side effect of reading (P11). These two exist so
# that the observable checks never have to connect to anything: a stdio server is a third
# party's process and a URL is somebody else's machine, and a graph being drawn must reach
# neither. Both go through the project's own object, in the project's own interpreter --
# the core never speaks MCP, and no coroutine ever reaches the process the UI is talking to.


@dataclass(frozen=True)
class ServerResult:
    """What a consumed server said. `status` is this node's verdict for this connection.

    Never stored. Nothing writes down "the mail server was reachable", so a colleague who
    has not connected sees `unproven` rather than somebody else's yesterday -- which falls
    out of I-1 rather than being a feature of this type.
    """

    ok: bool
    status: str
    detail: str
    tools: tuple[dict[str, str], ...] = ()
    allowed: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail,
            "tools": [dict(tool) for tool in self.tools],
            "allowed": list(self.allowed),
            "missing": list(self.missing),
        }


def _server_carrier(root: Path, node: str) -> tuple[str | None, str]:
    """The declaration a node id names, or why this verb has nothing to act on.

    The kind is checked rather than assumed: `mcp.inspect` on a route would otherwise
    import the project and try to call `connect()` on something that has none, and the
    reason would be about a missing method instead of about the wrong node.
    """
    from aibuilder_core.project import read_project

    for candidate in read_project(root).nodes:
        if candidate.id == node:
            if candidate.kind != "mcp.server":
                return None, f"{node} is a {candidate.kind}, not a server this project consumes"
            return candidate.carrier, ""
    return None, f"this project has no node called {node}"


def inspect_server(project: Path | str, node: str, python: str | None = None) -> dict[str, Any]:
    """Connect, initialize, and list what the server offers."""
    root = Path(project).resolve()
    carrier, why = _server_carrier(root, node)
    if carrier is None:
        return ServerResult(False, "broken", why).as_dict()

    environment = describe_environment(root, python)
    answer = _ask_project(
        root,
        environment.interpreter,
        _project_modules(root),
        "mcp_inspect",
        carrier=carrier,
    )
    return _server_result(answer).as_dict()


def call_server_tool(
    project: Path | str,
    node: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Call one tool on a consumed server with input a person typed (Q7).

    The arguments come from the caller and are passed through untouched. Nothing here
    invents one, defaults one, or retries with a different one: evidence comes from a real
    call with real input, or it is not evidence.
    """
    root = Path(project).resolve()
    carrier, why = _server_carrier(root, node)
    if carrier is None:
        return {"ok": False, "status": "broken", "detail": why, "result": ""}

    environment = describe_environment(root, python)
    answer = _ask_project(
        root,
        environment.interpreter,
        _project_modules(root),
        "mcp_call",
        carrier=carrier,
        tool=tool,
        arguments=dict(arguments or {}),
    )
    return {
        "ok": bool(answer.get("ok", False)),
        "status": str(answer.get("status", "unproven")),
        "detail": str(answer.get("detail") or "the project gave no readable answer"),
        "result": str(answer.get("result", "")),
    }


def _server_result(answer: dict[str, Any]) -> ServerResult:
    tools = answer.get("tools") or []
    return ServerResult(
        ok=bool(answer.get("ok", False)),
        status=str(answer.get("status", "unproven")),
        detail=str(answer.get("detail") or "the project gave no readable answer"),
        tools=tuple(
            {"name": str(tool.get("name", "")), "description": str(tool.get("description", ""))}
            for tool in tools
            if isinstance(tool, dict)
        ),
        allowed=tuple(str(name) for name in answer.get("allowed") or []),
        missing=tuple(str(name) for name in answer.get("missing") or []),
    )


# -- handing a pipeline its documents (P17.5) -------------------------------------
#
# The same relation as a conversation with a different verb (Q18): an action on the
# pipeline's node, not a node of its own. It is a **write into somebody's store**, so it is
# a press and never a consequence of drawing the graph -- and what it reports is what the
# store said afterwards, never the documents that went in.


def index_pipeline(project: Path | str, node: str, python: str | None = None) -> dict[str, Any]:
    """Rebuild the index behind one pipeline node, in the project's own interpreter.

    Refused by **kind** before anything is imported, the way a conversation is (P17.2): a
    verb that ran whatever happened to be callable would build something and call it an
    index. A kind opts in by naming a way in, and a kind that has not shows no button.
    """
    from aibuilder_core.kinds import REGISTRY
    from aibuilder_core.project import read_project

    root = Path(project).resolve()
    found = next((item for item in read_project(root).nodes if item.id == node), None)
    if found is None:
        return {
            "ok": False,
            "status": "broken",
            "detail": f"this project has no node called {node}",
            "held": "",
        }

    kind = REGISTRY.get(found.kind)
    if kind is None or not kind.indexes:
        return {
            "ok": False,
            "status": "unproven",
            "detail": f"a {found.kind} holds no index to hand documents to",
            "held": "",
        }

    environment = describe_environment(root, python)
    answer = _ask_project(
        root,
        environment.interpreter,
        _project_modules(root),
        "index",
        timeout_s=INDEX_TIMEOUT_S,
        carrier=found.carrier,
        how=kind.indexes,
    )
    return {
        "ok": bool(answer.get("ok", False)),
        "status": str(answer.get("status", "unproven")),
        "detail": str(answer.get("detail") or "the project gave no readable answer"),
        "held": str(answer.get("held", "")),
    }


# -- the commands the project already has, and running one (P17.6, P17.7) ---------
#
# A front end is **run, not modelled** (Q20). It goes on no graph, carries no knob and turns
# no colour, because there is no claim about it this toolchain could prove -- and a node that
# cannot be red is decoration. What a person gets instead is the list of commands the project
# already has, and a choice.
#
# **Asked, never read.** `npm pkg get scripts` answers in JSON, which is npm's own account of
# its own file; parsing `package.json` here would be a second opinion about somebody else's
# format, and §5.8 forbids it. It is also one level better than `npm run` with no arguments,
# whose output is prose written for a person to look at.
#
# Running one is the same shape as everything else that runs (P13): a record on disk, output
# polled with an offset the caller keeps, nothing pushed, and nothing started implicitly.
# **Each process is started on its own** -- there is no button that brings the application up,
# because the order and the readiness of somebody else's topology is knowledge we do not have,
# and one fallen link would redden all of it (Q20).

#: The command process's record and log, siblings of `run.json` and `worker.json`.
COMMAND_STATE_PATH = Path(".aibuilder") / "command.json"
COMMAND_LOG_PATH = Path(".aibuilder") / "command.log"

#: How long npm may take to answer what scripts a project has.
NPM_TIMEOUT_S = 30

#: How long a started command is watched before it is called started. Not a readiness check
#: and deliberately not dressed as one: a dev server publishes a port it chose itself and
#: announces it in prose, and asking a log what it means is exactly the parsing §5.8 forbids.
#: What this window proves is the one thing that can be proven without asking anybody -- that
#: the command did not fall over on the spot.
COMMAND_SETTLE_S = 1.5


@dataclass(frozen=True)
class CommandList:
    """The commands a project already has, as the tool that owns them reported them."""

    ok: bool
    detail: str
    #: name -> the command line the project gave that name to. Never edited, never inferred.
    commands: tuple[tuple[str, str], ...] = ()
    #: Where they were asked for, relative to the project. "" is the project root.
    directory: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "commands": [{"name": name, "command": line} for name, line in self.commands],
            "directory": self.directory,
        }


def _within(project: Path, directory: str) -> Path | None:
    """Where to ask, refusing anything outside the project.

    The directory is **passed in, never discovered**: nothing here goes looking for a folder
    because it is called `web` or `frontend`, for the same reason a blueprint catalog is
    never discovered -- what the tool offers must not depend on the shape of somebody's disk.
    """
    root = project.resolve()
    here = (root / directory).resolve() if directory else root
    try:
        here.relative_to(root)
    except ValueError:
        return None
    return here if here.is_dir() else None


def project_commands(project: Path | str, directory: str = "") -> CommandList:
    """What `npm run` would run here, asked of npm itself (P17.6).

    Nothing about this goes on the graph. It is a list and a choice.
    """
    root = Path(project).resolve()
    here = _within(root, directory)
    if here is None:
        return CommandList(False, f"there is no directory {directory!r} in this project")
    if shutil.which("npm") is None:
        return CommandList(False, "npm is not installed, so this project has no commands to ask")

    try:
        completed = subprocess.run(  # noqa: S603 -- the command is ours, built above
            ["npm", "pkg", "get", "scripts"],  # noqa: S607 -- npm is resolved on PATH above
            cwd=here,
            capture_output=True,
            text=True,
            timeout=NPM_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CommandList(False, f"npm could not be asked: {exc}", directory=directory)

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return CommandList(
            False,
            detail[-1] if detail else "npm found nothing to answer about here",
            directory=directory,
        )

    try:
        answered = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return CommandList(False, "npm gave no readable answer", directory=directory)

    if not isinstance(answered, dict) or not answered:
        return CommandList(True, "this project declares no commands", directory=directory)

    commands = tuple(
        (str(name), str(line)) for name, line in sorted(answered.items()) if isinstance(line, str)
    )
    return CommandList(True, f"{len(commands)} command(s)", commands, directory)


def start_command(project: Path | str, command: str, directory: str = "") -> RunResult:
    """Run one of the commands the project already has, and leave it running (P17.7).

    Refused unless the project itself declares it: this verb runs `npm run <name>`, and the
    name has to be one npm just said exists. A verb that ran an arbitrary string would be a
    shell with a button on it, and nothing about the graph would be true of what it started.

    No verdict attaches to what comes back, because 17.6 put nothing on the graph to colour.
    """
    root = Path(project).resolve()
    existing = _read_state(root, COMMAND_STATE_PATH)
    if existing and _alive(existing.pid):
        return RunResult(True, f"{existing.target} is already running", existing)
    if existing:
        _forget(root, COMMAND_STATE_PATH)

    listed = project_commands(root, directory)
    if not listed.ok:
        return RunResult(False, listed.detail)
    if command not in {name for name, _ in listed.commands}:
        offered = ", ".join(name for name, _ in listed.commands) or "none"
        return RunResult(False, f"this project declares no command {command!r} (it has: {offered})")

    here = _within(root, directory)
    assert here is not None  # `project_commands` already refused anything else
    log = root / COMMAND_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm") or "npm"
    line = (npm, "run", command)

    with log.open("wb") as sink:
        process = subprocess.Popen(  # noqa: S603 -- the command is npm plus a name npm listed
            line,
            cwd=here,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    time.sleep(COMMAND_SETTLE_S)
    if process.poll() is not None:
        return RunResult(
            False,
            f"{command} exited immediately ({process.returncode}); see the logs",
            logs=_tail(log),
        )

    state = RunState(
        pid=process.pid,
        port=0,  # what it publishes is its own business, and asking a log would be parsing
        target=f"npm run {command}",
        command=line,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    _write_state(root, state, COMMAND_STATE_PATH)
    _STARTED_HERE[(str(root), COMMAND_STATE_PATH.name)] = process
    return RunResult(True, f"{state.target} is running", state, logs=_tail(log))


def command_status(project: Path | str) -> RunResult:
    """Is it still running? Asked of the operating system, never of a memory.

    Only that question, and deliberately only that one: whether a dev server is *ready* is a
    claim about somebody else's process that nothing here can honestly make.
    """
    root = Path(project).resolve()
    state = _read_state(root, COMMAND_STATE_PATH)
    if state is None:
        return RunResult(False, "nothing is running")
    if not _alive(state.pid):
        _forget(root, COMMAND_STATE_PATH)
        return RunResult(False, "nothing is running (the recorded process is gone)")
    return RunResult(True, f"{state.target} is running", state)


def stop_command(project: Path | str) -> RunResult:
    """Stop it -- this session's, or one a crashed session left behind."""
    return _stop_recorded(Path(project).resolve(), COMMAND_STATE_PATH)


def read_command_logs(project: Path | str, offset: int = 0) -> RunResult:
    """What it has printed since `offset`. Polled, exactly like the application's."""
    return read_logs(project, offset, COMMAND_LOG_PATH)


def stop_everything_started_here() -> None:
    """End of session, end of the processes it started.

    **A session is the sidecar's lifetime**, not any exit of any process. The sidecar calls
    this when its stdin closes -- the window went away, so what it started goes with it. A
    CLI invocation is not a session: `run` from a terminal leaves the application running,
    because a verb a person typed is not undone by the command returning, and `stop` is the
    verb that ends it.

    Either way a hard kill leaves the state file behind, which is how the next session finds
    the orphan -- and why `stop` works on a process this one never started.
    """
    for root, state_name in list(_STARTED_HERE):
        with contextlib.suppress(Exception):
            _stop_recorded(Path(root), Path(".aibuilder") / state_name)
