"""`Deploy`: bring the project's compose stack up, and take it down again.

The eighth instance of the P13 shape, and the one with the shortest description: `docker
compose up` in the project's own directory, its log polled with an offset the caller keeps,
and `docker compose down` when somebody stops it or the window goes away.

**The compose file is never read here.** Not a line of it. Which services exist is asked of
`docker compose config --services`, because a YAML reader of ours would be a second opinion
about a format that already has a first one, and it would be wrong in ways that look right.
The same rule that keeps the parser out of `Dockerfile` keeps this out of `compose.yaml`.

**There is one deployment target and it is compose.** Not a first target with more to follow:
a second one would need credentials, a remote, and a notion of an environment, and none of
those is in this plan.

## One service, started on its own

`Deploy` is the whole stack, and it is what a person presses when they want the project
running. What they press far more often while building is "bring the database up so I can
work" -- one service, the one whose card they are looking at. That is `start_service`, and
it is the same program answering: `docker compose up -d <name>`, with the name checked
against `config --services` first, because a name that reached a shell unchecked would be
this toolchain running whatever it was handed.

**It is `Start`, never `Run`.** `Run` in this product means calling one system's export, and
two verbs under one word is how a person stops trusting either.

Detached, and that is the difference from `Deploy`: there is no client to attach to one
service of a stack, and a log per container is `docker compose logs`, which the stack's own
panel already offers. So what is kept instead is **ownership** -- which services this
application brought up -- and on the way out those are stopped and nothing else is. A
container somebody started before the app opened is not ours to stop.

Stopping one service is `stop`, never `down`: `down` removes the whole stack, and a person
who pressed Stop on a Postgres card asked for that Postgres to stop, not for their volumes
and their five other containers to go.

## Why `down` and not only a kill

`docker compose up` in the foreground is a client attached to containers the daemon owns.
Killing the client leaves the containers running — which would make "closing the app stops
what it started" false, and it is the one promise a local-first tool cannot afford to break.
So stopping means killing the client *and* running `down`, and the sidecar does the same on
its way out.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "COMPOSE_FILE",
    "DeployResult",
    "close_everything_deployed_here",
    "deploy_status",
    "docker_program",
    "read_deploy",
    "start_deploy",
    "start_service",
    "stop_deploy",
    "stop_service",
]

#: The file node this verb is about. One name, because the convention names one.
COMPOSE_FILE = "compose.yaml"

#: What the stack prints while it is up.
LOG_PATH = Path(".framestack") / "deploy.log"

#: How long `docker compose down` may take before we stop waiting for it. Generous: it stops
#: containers, and a database with a slow shutdown is ordinary.
DOWN_SECONDS = 120

#: How long one service may take to come up. It is generous because the first `up` of an
#: image pulls it, and a pull over somebody's connection is minutes rather than seconds. A
#: timeout here is reported as one -- the container may still be coming up, and saying it
#: failed would be a claim about the daemon that this call did not check.
UP_SECONDS = 600


@dataclass(frozen=True)
class DeployResult:
    """The answer to every verb here. A refusal is a result, never a protocol fault."""

    ok: bool
    detail: str
    running: bool = False
    output: str = ""
    offset: int = 0
    #: Whether `docker` is on this machine at all, and the version it reports. Asked, so the
    #: panel can say why the button will not work before somebody presses it.
    available: bool = False
    version: str = ""
    #: What the stack is made of, **as `docker compose config` reports it**. Empty from a
    #: poll, which does not ask: the answer costs a process and does not change while it runs.
    services: tuple[str, ...] = ()
    #: The one service a per-service verb was about. `""` for every verb about the stack, so
    #: a caller can never mistake an answer about one container for an answer about all of
    #: them -- they are different claims and they end at different moments.
    service: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "running": self.running,
            "output": self.output,
            "offset": self.offset,
            "available": self.available,
            "version": self.version,
            "service": self.service,
            "services": list(self.services),
        }


@dataclass
class _Stack:
    """One compose stack, up. Held by the sidecar; the containers outlive it unless told not to."""

    project: str
    process: subprocess.Popen[bytes]
    log: Path


#: Every stack this sidecar brought up, keyed by the project. One per project: `docker
#: compose` already treats a directory as one project, and a second `up` in it is the same
#: stack being reconfigured rather than a new one.
_STACKS: dict[str, _Stack] = {}

#: Which services this application brought up, keyed by the project.
#:
#: **Ownership, never a reading of what is running.** What is up is `docker compose ps`'s
#: answer and is asked when somebody looks; this is the much smaller question of what *we*
#: started, and it exists for one purpose -- stopping those and nothing else on the way out.
#: A Postgres somebody had running before this window opened is not ours to stop, and a set
#: that drifted into meaning "what is up" would stop exactly that container.
_OURS: dict[str, set[str]] = {}


def docker_program() -> tuple[str, str]:
    """`(the docker on this machine, its version)`, or `("", why not)`.

    Asked of the program itself. A `docker` on `PATH` that cannot talk to a daemon is a
    different failure from no `docker` at all, and a person is owed which one it is.
    """
    found = shutil.which("docker")
    if not found:
        return "", "docker is not on this machine's PATH"
    try:
        answer = subprocess.run(  # noqa: S603 -- docker, as just located
            [found, "compose", "version", "--short"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"docker could not be run: {type(exc).__name__}: {exc}"
    if answer.returncode != 0:
        return "", "this docker has no `compose` subcommand -- Compose v2 is what Deploy uses"
    return found, answer.stdout.strip()


def _services(docker: str, root: Path) -> tuple[str, ...]:
    """What the stack is made of, asked of compose rather than read out of the file."""
    try:
        answer = subprocess.run(  # noqa: S603 -- docker, located above
            [docker, "compose", "-f", COMPOSE_FILE, "config", "--services"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if answer.returncode != 0:
        return ()
    return tuple(line.strip() for line in answer.stdout.splitlines() if line.strip())


def _running(root: Path) -> bool:
    stack = _STACKS.get(str(root))
    return stack is not None and stack.process.poll() is None


def _read_log(root: Path, offset: int) -> tuple[str, int]:
    log = root / LOG_PATH
    where = max(offset, 0)
    if not log.is_file():
        return "", where
    try:
        raw = log.read_bytes()
        return raw[where:].decode("utf-8", errors="replace"), len(raw)
    except OSError:
        return "", where


def _down(root: Path, docker: str) -> None:
    """Take the stack down. What makes stopping mean stopped, rather than detached."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(  # noqa: S603 -- docker, located by `docker_program`
            [docker, "compose", "-f", COMPOSE_FILE, "down"],
            cwd=root,
            capture_output=True,
            timeout=DOWN_SECONDS,
        )


def _kill(stack: _Stack) -> None:
    """Detach the client. Its own process group, so nothing it started is left behind."""
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(os.getpgid(stack.process.pid), signal.SIGTERM)
    try:
        stack.process.wait(timeout=30)
    except (subprocess.SubprocessError, OSError):
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(os.getpgid(stack.process.pid), signal.SIGKILL)


def deploy_status(project: Path | str) -> DeployResult:
    """Whether this project can be deployed, and whether it already is. A read: it starts nothing.

    It does spawn `docker compose config`, and that is not a contradiction of P11: asking a
    file what it says is not bringing anything up, and it is the only way to answer without
    learning YAML.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return DeployResult(False, f"there is no project at {root}")
    if not (root / COMPOSE_FILE).is_file():
        return DeployResult(False, f"there is no {COMPOSE_FILE} here to bring up")

    docker, version = docker_program()
    if not docker:
        return DeployResult(False, version, running=_running(root))

    return DeployResult(
        True,
        "up" if _running(root) else "down",
        running=_running(root),
        available=True,
        version=version,
        services=_services(docker, root),
    )


def start_deploy(project: Path | str) -> DeployResult:
    """Bring the stack up. Never implicit (P11) -- somebody pressed `Deploy`.

    Returns as soon as compose is running. What it prints arrives through `read_deploy`.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return DeployResult(False, f"there is no project at {root}")
    if not (root / COMPOSE_FILE).is_file():
        return DeployResult(False, f"there is no {COMPOSE_FILE} here to bring up")
    if _running(root):
        return DeployResult(True, "this stack is already up", running=True, available=True)

    docker, version = docker_program()
    if not docker:
        return DeployResult(False, version)

    log = root / LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"")

    try:
        sink = log.open("wb")
        process = subprocess.Popen(  # noqa: S603 -- docker, located by `docker_program`
            [docker, "compose", "-f", COMPOSE_FILE, "up"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env={**os.environ},
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        return DeployResult(False, f"compose could not be started: {exc}", available=True)

    _STACKS[str(root)] = _Stack(project=str(root), process=process, log=log)
    return DeployResult(
        True, "bringing the stack up", running=True, available=True, version=version
    )


def _compose(root: Path, docker: str, verb: str, service: str, seconds: int) -> tuple[bool, str]:
    """Run one compose verb against one service. `(it worked, what it said)`.

    The name has already been checked against `config --services` by the caller, which is
    the whole of the guard: compose is handed a service it declared, or it is not run.
    """
    try:
        answer = subprocess.run(  # noqa: S603 -- docker, located by `docker_program`
            [docker, "compose", "-f", COMPOSE_FILE, *verb.split(), service],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=seconds,
        )
    except subprocess.TimeoutExpired:
        # Not a failure. The daemon may well still be pulling, and reporting `up` as failed
        # would be a claim about a container this call stopped watching.
        return False, f"{service} is still starting -- compose has not finished in {seconds}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"compose could not be run: {type(exc).__name__}: {exc}"
    if answer.returncode != 0:
        detail = (answer.stderr or answer.stdout).strip().splitlines()
        return False, detail[-1] if detail else f"compose refused to {verb} {service}"
    return True, (answer.stdout or answer.stderr).strip()


def _one_service(project: Path | str, service: str) -> tuple[Path, str, DeployResult | None]:
    """Everything both verbs check first: a project, a compose file, a docker, a real name.

    The name is checked against `config --services` rather than trusted, because it arrives
    over the wire and ends up in an argument list. Compose is asked what it declares; a name
    it does not know is refused here rather than handed to a subprocess to find out.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return root, "", DeployResult(False, f"there is no project at {root}", service=service)
    if not (root / COMPOSE_FILE).is_file():
        return (
            root,
            "",
            DeployResult(False, f"there is no {COMPOSE_FILE} here", service=service),
        )
    docker, version = docker_program()
    if not docker:
        return root, "", DeployResult(False, version, service=service)
    if service not in _services(docker, root):
        return (
            root,
            docker,
            DeployResult(
                False,
                f"{COMPOSE_FILE} declares no service called {service!r}",
                available=True,
                version=version,
                service=service,
            ),
        )
    return root, docker, None


def start_service(project: Path | str, service: str) -> DeployResult:
    """Bring one service up, detached. Never implicit (P11) -- somebody pressed `Start`.

    `up -d` rather than an attached client: there is nothing to attach to one service of a
    stack that the stack's own `Deploy` does not already do better, and what a container
    prints is `docker compose logs`, which is somebody else's answer to give.
    """
    root, docker, refused = _one_service(project, service)
    if refused is not None:
        return refused

    ok, said = _compose(root, docker, "up -d", service, UP_SECONDS)
    if ok:
        # Ours now, and only now. The set is what gets stopped on the way out, so a service
        # we failed to start must never enter it -- stopping a container this application
        # did not start is the one thing this registry exists to prevent.
        _OURS.setdefault(str(root), set()).add(service)
    return DeployResult(
        ok,
        said or (f"{service} is up" if ok else f"{service} did not start"),
        running=ok,
        available=True,
        service=service,
    )


def stop_service(project: Path | str, service: str) -> DeployResult:
    """Stop one service. `stop`, never `down`.

    `down` removes the stack, and somebody who pressed Stop on a Postgres card asked for that
    Postgres to stop -- not for their five other containers and their volumes to go with it.
    """
    root, docker, refused = _one_service(project, service)
    if refused is not None:
        return refused

    ok, said = _compose(root, docker, "stop", service, DOWN_SECONDS)
    if ok:
        _OURS.get(str(root), set()).discard(service)
    return DeployResult(
        ok,
        said or (f"{service} is stopped" if ok else f"{service} did not stop"),
        running=not ok,
        available=True,
        service=service,
    )


def read_deploy(project: Path | str, offset: int = 0) -> DeployResult:
    """What compose has printed since `offset`. The caller keeps the offset (P13).

    `running` false with output behind it is the ordinary end: compose exited, because the
    stack stopped or because it could not start. The log says which, in its own words.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return DeployResult(False, f"there is no project at {root}")
    text, where = _read_log(root, offset)
    running = _running(root)
    if not running:
        _STACKS.pop(str(root), None)
    return DeployResult(
        True, "up" if running else "down", running=running, output=text, offset=where
    )


def stop_deploy(project: Path | str) -> DeployResult:
    """Take the stack down: detach the client, then `down` the containers it left.

    Both, always. See the module docstring -- a kill on its own leaves the daemon holding
    everything, and "closing the app stops what it started" would be false.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return DeployResult(False, f"there is no project at {root}")

    stack = _STACKS.pop(str(root), None)
    if stack is not None:
        _kill(stack)

    docker, version = docker_program()
    if not docker:
        return DeployResult(False, version)
    _down(root, docker)
    return DeployResult(True, "the stack is down", running=False, available=True, version=version)


def _take_down(root: str) -> None:
    """One project, ended: the stack's client, its containers, then the services we started.

    Both, because they are two different things this application brought up. A stack it
    attached to is taken `down`; services it started one at a time are `stop`ped by name, and
    a container it never started is not touched at all -- which is what `_OURS` is for.
    """
    stack = _STACKS.pop(root, None)
    ours = _OURS.pop(root, set())
    if stack is None and not ours:
        return
    if stack is not None:
        _kill(stack)
    docker, _ = docker_program()
    if not docker:
        return
    if stack is not None:
        # `down` takes the whole stack with it, so anything we started by name is already
        # stopped and naming it again would be a second call for nothing.
        _down(Path(root), docker)
        return
    for service in sorted(ours):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _compose(Path(root), docker, "stop", service, DOWN_SECONDS)


def close_everything_deployed_here() -> None:
    """Stop everything this sidecar brought up, on the way out.

    In threads and joined with a limit, because `down` on several projects would otherwise be
    served one at a time while a window waits to close -- and a shutdown that hangs is how a
    stack ends up surviving anyway.
    """
    workers = [
        threading.Thread(target=_take_down, args=(root,), daemon=True)
        for root in {*_STACKS, *_OURS}
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=DOWN_SECONDS)
    _STACKS.clear()
    _OURS.clear()
