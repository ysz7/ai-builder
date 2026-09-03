"""Whether a dependency can be reached, asked once per request and never guessed.

## A status is not a verdict

A verdict comes from a test and belongs to code you own. A status comes from a connection and
belongs to something outside the project. They are different claims from different mechanisms
and **they never share a colour scale**: a reachable Postgres is not a proven one, and the day
those two greens look alike is the day a node is green because it exists.

## Nothing here costs money

**A paid API is never called to find out whether it is up.** A status that costs money is one
nobody can afford to poll, and it would make an idle window bill somebody. For a provider the
free and useful question is a different one -- has this project been given a key at all -- and
that is the question asked, with the answer stated in those words rather than dressed up as
reachability.

Only the **names** of the environment variables are read, never a value. A key in a payload is
one console log from being somewhere permanent, which is the rule `mcp.py` follows for the same
reason.

## The checks run in the project's interpreter, not in ours

`SELECT 1` needs a Postgres driver and `PING` needs a Redis client. This codebase has neither
and will not acquire them: a connector written is a connector maintained, and the project
already has the ones it uses. So a check is a **script written as text and run as a child
process** in the project's own environment -- the same shape `run.py` uses, for the same
reason. A project whose environment lacks the driver gets `unknown` with the reason said out
loud, which is a true answer and not a failure.

Ollama is the exception and needs no driver: it is an HTTP endpoint, asked with the standard
library.

## Nothing starts implicitly

A check connects; it never brings anything up. `docker compose ps` asks what is running and
starts nothing, which is the same restraint `deploy.status` shows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from framestack_core.database import DATABASE_NODE, read_database
from framestack_core.dependencies import CREDENTIALS, DOCKER_NODE, SIGNS
from framestack_core.environment import interpreter_for

__all__ = ["CHECKING", "REACHABLE", "UNKNOWN", "UNREACHABLE", "Status", "read_status"]

#: A connection was made. **Never green in the verdict's sense**: reached is not proven.
REACHABLE = "reachable"
#: A connection was attempted and refused. Actionable, and the reason says how.
UNREACHABLE = "unreachable"
#: Never checked, or not checkable from here. The absence of an answer, said as one.
UNKNOWN = "unknown"
#: A key is present in the project's `.env`. Only for the nodes a check would bill somebody.
CONFIGURED = "configured"
#: No key. The project names the provider and has not been given one.
UNCONFIGURED = "unconfigured"
#: The request is in flight. The caller's state, declared here so both sides use one word.
CHECKING = "checking"

#: How long any one check may take. Short on purpose: a status is polled, and a check that
#: hung would hold a window's worth of them behind it.
SECONDS = 5

#: Ollama's own default, and the one endpoint that answers without a client library.
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"

#: Where a project's keys live. Read for **names only**, never for a value.
ENV_FILE = ".env"


@dataclass(frozen=True)
class Status:
    """What one dependency answered, and when."""

    ok: bool
    node: str
    status: str
    #: Why, in a sentence. The whole point of `unreachable`: a colour nobody can act on is
    #: decoration, so the refusal carries the reason the connection did not happen.
    detail: str
    #: When it was asked, so a caller can tell a fresh answer from one it is still holding.
    at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "node": self.node,
            "status": self.status,
            "detail": self.detail,
            "at": self.at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _answer(node: str, status: str, detail: str) -> Status:
    return Status(ok=True, node=node, status=status, detail=detail, at=_now())


def _env_names(root: Path) -> set[str]:
    """The variable **names** a project's `.env` sets. No value is ever read out of it.

    A key rendered anywhere is a key one console log from being permanent. What the question
    needs is whether the line exists, and the name alone answers it.
    """
    path = root / ENV_FILE
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    found: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name.startswith("export "):
            name = name[len("export ") :].strip()
        if name:
            found.add(name)
    return found


def _credential(root: Path, node: str) -> Status:
    """Whether the project has been given a key. **The provider is never called.**"""
    sign = next((one for one in SIGNS if one.node == node), None)
    if sign is None:
        return _answer(node, UNKNOWN, f"nothing here knows how to check {node}")

    names = _env_names(root) | {name for name in sign.credentials if os.environ.get(name)}
    present = sorted(name for name in sign.credentials if name in names)
    if present:
        return _answer(
            node,
            CONFIGURED,
            f"{', '.join(present)} is set. Whether the provider is up is not asked: "
            "a check that costs money is one nobody can afford to poll",
        )
    return _answer(
        node,
        UNCONFIGURED,
        f"{' or '.join(sign.credentials)} is not set in {ENV_FILE}",
    )


def _in_project(root: Path, script: str) -> tuple[bool, str]:
    """Run one line of Python in the project's own interpreter. `(ok, detail)`.

    The script is text and the core imports none of it, which is the rule everywhere: drawing
    or checking must never load a stranger's module into this process.
    """
    python = interpreter_for(root)
    if python is None:
        return False, "this project has no interpreter to run a check in"
    try:
        answer = subprocess.run(  # noqa: S603 -- an interpreter located by `environment.py`
            [str(python), "-c", script],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"the check did not answer within {SECONDS}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the check could not be run: {type(exc).__name__}: {exc}"
    if answer.returncode == 0:
        return True, ""
    said = answer.stderr.strip() or answer.stdout.strip() or "the check failed"
    # The last line: a driver's traceback ends with the sentence a person can act on, and
    # the frames above it are about this toolchain's subprocess rather than their database.
    return False, said.splitlines()[-1]


#: `SELECT 1`, written as a script because the core has no driver and will not acquire one.
#:
#: The project's own `psycopg` is used, which is the point: where the project has none, the
#: honest answer is that this cannot be checked from here rather than a red node.
POSTGRES_CHECK = """
import sys
try:
    import psycopg
except ImportError:
    sys.stderr.write("this project's environment has no psycopg to check with")
    raise SystemExit(2)
with psycopg.connect({url!r}, connect_timeout=3) as connection:
    connection.execute("SELECT 1")
"""

#: `PING`, on the same terms.
REDIS_CHECK = """
import sys
try:
    import redis
except ImportError:
    sys.stderr.write("this project's environment has no redis to check with")
    raise SystemExit(2)
redis.Redis.from_url({url!r}, socket_connect_timeout=3).ping()
"""


def _postgres(root: Path) -> Status:
    database = read_database(root)
    if not database.target:
        return _answer(
            DATABASE_NODE,
            UNKNOWN,
            "this project states no connection string, so there is nothing to connect to",
        )
    ok, detail = _in_project(root, POSTGRES_CHECK.format(url=database.target))
    if ok:
        return _answer(DATABASE_NODE, REACHABLE, "SELECT 1 answered")
    if "no psycopg" in detail:
        return _answer(DATABASE_NODE, UNKNOWN, detail)
    return _answer(DATABASE_NODE, UNREACHABLE, detail)


def _redis(root: Path) -> Status:
    url = _redis_url(root)
    ok, detail = _in_project(root, REDIS_CHECK.format(url=url))
    if ok:
        return _answer("redis", REACHABLE, "PING answered")
    if "no redis" in detail:
        return _answer("redis", UNKNOWN, detail)
    return _answer("redis", UNREACHABLE, detail)


#: What a Redis is when the project has not said. Unlike a Postgres, it has a default
#: everybody means -- and the check is free, so trying it costs a refused connection at worst.
REDIS_DEFAULT = "redis://127.0.0.1:6379/0"


def _redis_url(root: Path) -> str:
    """The URL the project states in `.env`, or Redis's own default.

    The one place a **value** is read out of `.env`, and it is read for the thing it points
    at rather than for a secret: a Redis URL is an address. A password inside one would be
    passed to the project's own client in its own process and never put in a payload.
    """
    path = root / ENV_FILE
    if not path.is_file():
        return REDIS_DEFAULT
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return REDIS_DEFAULT
    for line in text.splitlines():
        stripped = line.strip().removeprefix("export ").strip()
        if stripped.startswith("REDIS_URL=") and "://" in stripped:
            return stripped.split("=", 1)[1].strip().strip("\"'")
    return REDIS_DEFAULT


def _ollama(root: Path) -> Status:
    """`GET /api/tags`. The one check with no driver behind it, so the stdlib does it."""
    request = urllib.request.Request(OLLAMA_URL, method="GET")  # noqa: S310 -- a fixed http URL
    try:
        with urllib.request.urlopen(request, timeout=SECONDS) as answer:  # noqa: S310
            body = json.loads(answer.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _answer("ollama", UNREACHABLE, f"{OLLAMA_URL} did not answer: {exc}")
    except (ValueError, json.JSONDecodeError):
        return _answer("ollama", UNREACHABLE, f"{OLLAMA_URL} answered with something else")
    models = body.get("models") if isinstance(body, dict) else None
    count = len(models) if isinstance(models, list) else 0
    return _answer("ollama", REACHABLE, f"{count} model(s) pulled")


def _docker(root: Path) -> Status:
    """What is running, asked of the program that owns the format. It starts nothing."""
    found = shutil.which("docker")
    if not found:
        return _answer(DOCKER_NODE, UNKNOWN, "docker is not on this machine's PATH")
    try:
        answer = subprocess.run(  # noqa: S603 -- docker, as just located
            [found, "compose", "ps", "--format", "json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=SECONDS * 2,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _answer(DOCKER_NODE, UNKNOWN, f"docker could not be run: {type(exc).__name__}")
    if answer.returncode != 0:
        return _answer(
            DOCKER_NODE,
            UNREACHABLE,
            (answer.stderr.strip() or "docker compose ps failed").splitlines()[-1],
        )
    running = sum(1 for line in answer.stdout.splitlines() if line.strip().startswith("{"))
    if running == 0:
        return _answer(DOCKER_NODE, UNREACHABLE, "nothing from this project is running")
    return _answer(DOCKER_NODE, REACHABLE, f"{running} container(s) running")


def read_status(project: Path | str, node: str) -> Status:
    """Whether one dependency can be reached. Connects; never starts anything.

    One node per request, because the polling policy is per node: a local check is cheap and
    asked often, a network one is not. A verb that checked everything at once would make the
    caller choose one interval for both.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return Status(False, node, UNKNOWN, f"there is no project at {root}", _now())

    if node in CREDENTIALS:
        return _credential(root, node)
    if node == DATABASE_NODE:
        return _postgres(root)
    if node == "redis":
        return _redis(root)
    if node == "ollama":
        return _ollama(root)
    if node == DOCKER_NODE:
        return _docker(root)

    # An MCP server's status is `list_tools`, which means speaking the protocol to it -- and
    # the client that can is built in Phase 10, where connecting is the subject. Until then
    # this says it does not know, which is exactly true: only the server knows, and nothing
    # here has asked it.
    return Status(
        False,
        node,
        UNKNOWN,
        f"nothing here can check {node}",
        _now(),
    )
