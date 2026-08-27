"""The environment a project runs in: its interpreter, and the services it declares.

Until now the toolchain had no notion of this at all. The probe was spawned with
`sys.executable`, so the run that produced a node's evidence happened in **our** environment
with **our** installed versions -- and a project that needs a database had no database. Both
make the same claim false, and it is the most convincing kind of false: the checks pass, and
what they proved is not what anyone thinks they proved (I-5).

Two rules shape everything here.

**Nothing in this module runs without being asked.** Reading a graph, or observing it, never
brings a service up, never creates a virtual environment and never installs a package. The
checks run in whatever environment already exists, and when that environment is missing a
piece, the honest answer is `skipped` with the reason. Starting the services is a separate
action a person takes -- in the UI, the button on the node whose carrier is the compose file
(§5.7). The consequence is worth stating: because nothing is ever started implicitly, there
is nothing to leak, and the teardown problem an implicit `up` would have created does not
exist.

**We never parse the compose file.** We ask `docker compose` what it says. It resolves
includes, profiles, `.env` interpolation and its own file-name precedence -- reimplementing
any of that would be a second, worse opinion about a file that is not ours (Q10). No YAML
parser, no new dependency, and when docker is absent the answer is "unavailable, here is
why" rather than a guess.

**Readiness is a connection, not a report.** Docker is asked what the project *declares*;
whether a service is actually usable is answered by connecting to the port it publishes.
That is the same question the application asks, and it has one answer instead of three:
reading docker's own status meant reconciling `State` with `Health` across output shapes
that changed between versions, and treating "running but still starting" as ready is how a
node earns a red badge for a database that had not finished booting. A port either answers
or it does not.

A service that publishes no port is not checked, and deliberately: nothing on this side of
the compose network can reach it either, so there is no claim to make about it.

**Docker's own status answers a different question, and only that one** (Q24). `running` says
a container is up, which is what `env.up` started and therefore what the button on that node
has to reflect; `reachable` says something answers on the port, which is what a caller cares
about. Reading `State` for the *first* is asking the thing that owns the fact; using it for
the second is what the paragraph above refuses, and nothing here does. The two are kept apart
because the gap between them is exactly where "I started it and nothing works" lives.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "COMPOSE_FILENAMES",
    "Environment",
    "Service",
    "ServiceResult",
    "compose_file",
    "describe_environment",
    "project_interpreter",
    "start_services",
    "stop_services",
]

#: Docker's own precedence order for the file it picks when none is named.
COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)

#: Where a project keeps its virtual environment. Convention, not configuration -- the same
#: reasoning as `tests/`: this is what a Python project does, and a project that does
#: something else gets the toolchain's interpreter with that fact reported, not guessed at.
VENV_DIRECTORY = ".venv"

#: How long any single docker command may take before it is a failure with a reason.
DOCKER_TIMEOUT_S = 20

#: How long `up` may take. Longer, because it waits for the services to become healthy.
UP_TIMEOUT_S = 300

#: How long to wait for a port to accept a connection. Short: this runs before a check and
#: a machine that is not answering in half a second is not answering.
CONNECT_TIMEOUT_S = 0.5


@dataclass(frozen=True)
class Service:
    """One service the project declares, and whether anything answers where it publishes."""

    name: str
    ports: tuple[int, ...] = ()
    reachable: bool = False
    #: Docker says this service's container is up. **Not the same claim as `reachable`**,
    #: and the two must never stand in for each other: a container that is running and a
    #: program inside it that answers are different facts, and the gap between them is
    #: exactly where "I started it and nothing works" lives. `running` is asked of
    #: `docker compose ps`; `reachable` is a connection to the port it publishes.
    running: bool = False
    #: The Dockerfile this service builds from, when it builds rather than pulls. Asked of
    #: docker like everything else here; it is what lets a `Dockerfile` node say which
    #: service builds it.
    dockerfile: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ports": list(self.ports),
            "reachable": self.reachable,
            "running": self.running,
            "dockerfile": self.dockerfile,
        }


@dataclass(frozen=True)
class Environment:
    """What is actually there, and where each part of it came from."""

    #: The interpreter the checks will run under.
    interpreter: str
    #: "project" or "toolchain". Never inferred silently: a run under our own interpreter is
    #: a weaker claim than a run under the project's, and the difference has to be visible.
    interpreter_origin: str
    compose_file: str | None = None
    #: The services the compose file declares, each with what answers on its ports.
    services: tuple[Service, ...] = ()
    #: Why docker could not be consulted, when it could not. `None` means it was.
    docker_unavailable: str | None = None

    @property
    def up(self) -> bool:
        """Is anything this project declares actually running?

        **Asked of docker, not inferred from a port.** The first version of this answered by
        reachability, and a person who had pressed Up watched the button go on saying "Up":
        their container was running and the program in it published nothing we could connect
        to, so by that measure nothing had happened. What the button reflects has to be the
        same question the button asked -- `docker compose up` starts containers, so whether
        containers are up is what says it worked.
        """
        return any(service.running for service in self.services)

    @property
    def services_missing(self) -> tuple[str, ...]:
        """Declared, publishing a port, and nothing answers there."""
        return tuple(
            service.name for service in self.services if service.ports and not service.reachable
        )

    @property
    def incomplete(self) -> str | None:
        """Why this is not the environment the project asked for, if it is not.

        One judgement in one place, because two situations mean the same thing to the
        evidence: services declared and not running, and services declared that we could
        not even ask about because docker is absent. In both, a failing test cannot be
        blamed on the code -- and in neither is a passing test worth less.
        """
        if self.compose_file and self.docker_unavailable:
            return (
                f"the services this project declares could not be checked "
                f"({self.docker_unavailable})"
            )
        if self.services_missing:
            return (
                "nothing answers where these declared services publish: "
                f"{', '.join(self.services_missing)}"
            )
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "interpreter": self.interpreter,
            "interpreter_origin": self.interpreter_origin,
            "compose_file": self.compose_file,
            "up": self.up,
            "services": [service.as_dict() for service in self.services],
            "missing": list(self.services_missing),
            "docker_unavailable": self.docker_unavailable,
            "incomplete": self.incomplete,
        }


@dataclass(frozen=True)
class ServiceResult:
    """The outcome of an action a person asked for."""

    ok: bool
    detail: str
    services: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "services": list(self.services)}


# -- the interpreter --------------------------------------------------------------


def project_interpreter(project: Path | str, python: str | None = None) -> tuple[str, str]:
    """The interpreter to run the project's code with, and where it came from.

    Falling back to our own is allowed and **reported**, because the dishonesty was never
    using our interpreter -- it was not saying so. A project without a virtual environment
    of its own is an ordinary situation (every example in this repository is one), and
    refusing to observe it would trade a small inaccuracy for a large hole.
    """
    if python:
        return python, "explicit"

    root = Path(project)
    for relative in (
        Path(VENV_DIRECTORY) / "bin" / "python",
        Path(VENV_DIRECTORY) / "Scripts" / "python.exe",
    ):
        candidate = root / relative
        if candidate.is_file():
            return str(candidate), "project"

    return sys.executable, "toolchain"


# -- the services -----------------------------------------------------------------


def compose_file(project: Path | str) -> Path | None:
    """The compose file a project declares its services in, if it has one."""
    # Absolute: every docker command runs with the project as its working directory, and a
    # relative path would then be resolved against it a second time.
    root = Path(project).resolve()
    return next((root / name for name in COMPOSE_FILENAMES if (root / name).is_file()), None)


def _docker(
    project: Path, *arguments: str, timeout: int = DOCKER_TIMEOUT_S
) -> tuple[int, str, str]:
    """One docker command, with every failure turned into data."""
    if shutil.which("docker") is None:
        return 127, "", "docker is not installed"

    try:
        completed = subprocess.run(
            ["docker", *arguments],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"docker did not answer within {timeout}s"

    return completed.returncode, completed.stdout, completed.stderr.strip()


def _published_ports(service: dict[str, Any]) -> tuple[int, ...]:
    """The host ports a service exposes, however compose spelled them."""
    ports: list[int] = []
    for entry in service.get("ports") or []:
        published = entry.get("published") if isinstance(entry, dict) else None
        if published in (None, ""):
            continue
        # `config --format json` normalises this to the host port alone, but the short
        # form can survive as "6379:6379" or "127.0.0.1:6379:6379". Dropping the parts that
        # are not numbers leaves the address, and the **first** number in it is the host
        # port -- the last one is the container's, which is nothing we could connect to.
        numbers = [part for part in str(published).split(":") if part.isdigit()]
        if numbers:
            ports.append(int(numbers[0]))
    return tuple(sorted(set(ports)))


def _declared(project: Path, file: Path) -> tuple[tuple[Service, ...], str | None]:
    """What the compose file declares -- asked of docker, never read by us."""
    code, out, error = _docker(project, "compose", "-f", str(file), "config", "--format", "json")
    if code != 0:
        return (), error or f"docker compose could not read {file.name}"

    try:
        payload = json.loads(out or "{}")
    except json.JSONDecodeError:
        return (), "docker compose produced no readable configuration"

    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, dict):
        return (), None

    up = _running(project, file)

    declared = []
    for name in sorted(services):
        definition = services[name] if isinstance(services[name], dict) else {}
        ports = _published_ports(definition)
        build = definition.get("build")
        dockerfile = build.get("dockerfile") if isinstance(build, dict) else None
        declared.append(
            Service(
                name=name,
                ports=ports,
                reachable=_answers(ports),
                running=name in up,
                dockerfile=None if dockerfile is None else str(dockerfile),
            )
        )
    return tuple(declared), None


def _running(project: Path, file: Path) -> frozenset[str]:
    """Which services docker says are up right now -- asked of docker, like everything here.

    `docker compose ps` and not `docker ps` plus a guess at the naming: which containers
    belong to this project is compose's own question, and the answer includes the project
    name it derived from the directory, which is not ours to reconstruct.
    """
    code, out, _ = _docker(project, "compose", "-f", str(file), "ps", "--format", "json")
    if code != 0:
        return frozenset()

    # One object per line in current versions, a list in older ones. Both are docker's own
    # answer about its own state; neither is a file of somebody else's that we are parsing.
    entries: list[Any] = []
    text = (out or "").strip()
    if text.startswith("["):
        with contextlib.suppress(json.JSONDecodeError):
            loaded = json.loads(text)
            entries = loaded if isinstance(loaded, list) else []
    else:
        for line in text.splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))

    return frozenset(
        str(entry.get("Service", ""))
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("State", "")).lower() == "running"
    )


def _answers(ports: tuple[int, ...]) -> bool:
    """Does something accept a connection on every port this service publishes?

    The check the application itself would make. No docker, no status field, no version to
    keep up with -- and it cannot say "ready" about a service that is still starting up.
    """
    if not ports:
        return False
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT_S):
                pass
        except OSError:
            return False
    return True


def describe_environment(project: Path | str, python: str | None = None) -> Environment:
    """Look at the project's environment. Reads only; starts nothing."""
    root = Path(project)
    interpreter, origin = project_interpreter(root, python)

    file = compose_file(root)
    if file is None:
        return Environment(interpreter=interpreter, interpreter_origin=origin)

    services, problem = _declared(root, file)
    if problem is not None:
        return Environment(
            interpreter=interpreter,
            interpreter_origin=origin,
            compose_file=str(file),
            docker_unavailable=problem,
        )

    return Environment(
        interpreter=interpreter,
        interpreter_origin=origin,
        compose_file=str(file),
        services=services,
    )


def start_services(project: Path | str, python: str | None = None) -> ServiceResult:
    """Bring up what the project declares. Only ever called because a person asked.

    Waits for the services to report healthy rather than merely started: "the container
    exists" is the container's answer to a question nobody asked. What it cannot wait for --
    a service with no healthcheck -- it says so about, rather than calling started healthy.
    """
    root = Path(project)
    file = compose_file(root)
    if file is None:
        return ServiceResult(False, "this project declares no services (no compose file)")

    environment = describe_environment(root, python)
    if environment.docker_unavailable:
        return ServiceResult(False, environment.docker_unavailable)
    names = tuple(service.name for service in environment.services)

    code, _, error = _docker(
        root, "compose", "-f", str(file), "up", "--detach", "--wait", timeout=UP_TIMEOUT_S
    )
    if code != 0:
        return ServiceResult(False, error or "docker compose up failed", names)

    declared, _ = _declared(root, file)
    up = tuple(service.name for service in declared if service.reachable)
    return ServiceResult(True, f"{len(up)} service(s) answering", up)


def stop_services(project: Path | str) -> ServiceResult:
    """Take down what the compose file declares. Also only ever asked for."""
    root = Path(project)
    file = compose_file(root)
    if file is None:
        return ServiceResult(False, "this project declares no services (no compose file)")

    code, _, error = _docker(root, "compose", "-f", str(file), "down", timeout=UP_TIMEOUT_S)
    if code != 0:
        return ServiceResult(False, error or "docker compose down failed")
    return ServiceResult(True, "services stopped")
