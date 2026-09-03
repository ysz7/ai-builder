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
    "stop_deploy",
]

#: The file node this verb is about. One name, because the convention names one.
COMPOSE_FILE = "compose.yaml"

#: What the stack prints while it is up.
LOG_PATH = Path(".framestack") / "deploy.log"

#: How long `docker compose down` may take before we stop waiting for it. Generous: it stops
#: containers, and a database with a slow shutdown is ordinary.
DOWN_SECONDS = 120


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "running": self.running,
            "output": self.output,
            "offset": self.offset,
            "available": self.available,
            "version": self.version,
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
    """One stack, ended: the client first, then the containers it was attached to."""
    stack = _STACKS.pop(root, None)
    if stack is None:
        return
    _kill(stack)
    docker, _ = docker_program()
    if docker:
        _down(Path(root), docker)


def close_everything_deployed_here() -> None:
    """Take down every stack this sidecar brought up, on the way out.

    In threads and joined with a limit, because `down` on several projects would otherwise be
    served one at a time while a window waits to close -- and a shutdown that hangs is how a
    stack ends up surviving anyway.
    """
    workers = [
        threading.Thread(target=_take_down, args=(root,), daemon=True) for root in list(_STACKS)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=DOWN_SECONDS)
    _STACKS.clear()
