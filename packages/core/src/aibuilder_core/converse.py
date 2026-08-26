"""Talking to what the project built, in the project's own interpreter.

Everything before this module builds an application. This one **uses** one: a person asks
the agent they just assembled a question and reads the answer, without leaving for a
terminal (P17).

Four decisions were taken before a line of it was written, and each one closed off a shape
that looked reasonable (Q18, Q19):

* **A conversation is an action on a node, never a node of its own.** A chat surface has no
  carrier, so by I-3 it is not a node, and a node the canvas draws rather than the code
  declares is the second source of truth I-1 forbids. The precedent is P15's `mcp.inspect`
  and `mcp.call`: buttons on the server's node.
* **The message goes through the project's interpreter**, as a new `ask` in `probe.py` --
  not by spawning the project's CLI and reading its output, which is parsing somebody
  else's format (§5.8), and not over HTTP, which would make an agent with no web layer
  require one and require *us* to start it (P11).
* **`probe.py` stays the only module that imports the user's project.** That rule has
  exactly one exception and is going to keep having exactly one, so this is a longer-lived
  spawn of the same script rather than a second script beside it.
* **The project remembers the conversation.** Its checkpointer, its `thread_id`. Nothing
  is stitched together here, because a history of ours would be a second opinion about what
  the dialogue *is* -- and it would behave differently in production than on the canvas.

The last of those is why the process **lives between questions** instead of being spawned
per turn: an in-memory checkpointer only works if the memory is still there. Which makes
this the fourth instance of the P13 shape, after `run.*`, `work.*` and `agent.*`, and not a
new mechanism: nothing is pushed, answers are polled with an offset the caller keeps, a
record on disk survives a crash, and nothing starts implicitly.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "TALKS_PATH",
    "TALK_STATE_PATH",
    "TalkResult",
    "close_everything_started_here",
    "conversations_held",
    "poll_talk",
    "say_to",
    "start_talk",
    "stop_talk",
    "talk_status",
]

#: Where a conversation's stream is kept, one file per node talked to.
TALKS_PATH = Path(".aibuilder") / "talks"

#: The conversations open in this project, keyed by node id. Tooling state, beside
#: `run.json` and `session.json`: delete it and the project is unchanged.
TALK_STATE_PATH = Path(".aibuilder") / "talks.json"

#: How long to wait for the project to import and say it is listening.
#:
#: Importing a project that pulls in a model client, a vector store and a graph is not
#: instant, and giving up early would report "cannot be talked to" about something that was
#: still waking up.
READY_TIMEOUT_S = 60

#: How often the log is looked at while waiting for that first line.
READY_POLL_S = 0.05

#: The live processes, held for the sidecar's lifetime and keyed by project and node.
#:
#: Like a session and unlike a web server, one of these has to be **written to**, and a pipe
#: cannot be reopened from a pid. So a conversation inherited from a crashed sidecar can be
#: stopped but not continued, and this module says so rather than pretending otherwise.
_LIVE: dict[tuple[str, str], subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class TalkResult:
    """The answer to every verb here. Refusals are results, never protocol faults."""

    ok: bool
    detail: str
    node: str = ""
    running: bool = False
    #: What was said since the offset the caller last held.
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: Where the reader got to, so the next poll asks for what came after it.
    offset: int = 0
    #: Which nodes have a conversation open here.
    open: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "running": self.running,
            "events": [dict(event) for event in self.events],
            "offset": self.offset,
            "open": list(self.open),
        }


def _state_path(project: Path) -> Path:
    return project / TALK_STATE_PATH


def _read_state(project: Path) -> dict[str, dict[str, Any]]:
    path = _state_path(project)
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {str(key): value for key, value in stored.items() if isinstance(value, dict)}


def _write_state(project: Path, records: dict[str, dict[str, Any]]) -> None:
    path = _state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        if records:
            path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


def _log_for(project: Path, key: str) -> Path:
    return project / TALKS_PATH / f"{key}.log"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _open_here(project: Path) -> tuple[str, ...]:
    """The nodes with a conversation on record that is still running."""
    return tuple(
        sorted(
            node
            for node, record in _read_state(project).items()
            if _alive(int(record.get("pid", 0) or 0))
        )
    )


@dataclass(frozen=True)
class WayIn:
    """What is needed to talk to one node: its carrier, its modules, and how it is asked."""

    carrier: str
    modules: tuple[str, ...]
    how: str


def _way_to(project: Path, node: str) -> tuple[WayIn | None, str]:
    """How to talk to this node, or why it cannot be talked to.

    Read out of the graph, which already knows the carrier -- a conversation addresses a
    node, and what a node *is* is a carrier object (I-3). **Whether** it can be talked to
    comes from the kind, which opts in by naming a way in; a kind that has not opted in is
    refused here rather than being handed to the probe to call and see what happens.
    """
    from aibuilder_core.kinds import REGISTRY
    from aibuilder_core.observe import build_plan
    from aibuilder_core.project import read_project

    graph = read_project(project)
    found = next((item for item in graph.nodes if item.id == node), None)
    if found is None:
        return None, f"no node {node!r} in this project"

    kind = REGISTRY.get(found.kind)
    if kind is None or not kind.converses:
        return None, f"a {found.kind} is not something this build can talk to"

    listed = build_plan(graph, project).get("modules", [])
    modules = tuple(str(name) for name in listed) if isinstance(listed, list) else ()
    return WayIn(carrier=found.carrier, modules=modules, how=kind.converses), ""


def _first_line(log: Path, deadline: float) -> dict[str, Any] | None:
    """The project's first word, waited for rather than assumed.

    What is being waited for is a line the probe wrote *after* importing the project, which
    is the only thing that proves the conversation can happen at all. A process that exists
    proves nothing -- an import that raises leaves one behind for as long as it takes to
    unwind.
    """
    while time.monotonic() < deadline:
        if log.is_file():
            with contextlib.suppress(OSError):
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    with contextlib.suppress(json.JSONDecodeError):
                        parsed = json.loads(line)
                        if isinstance(parsed, dict):
                            return parsed
        time.sleep(READY_POLL_S)
    return None


def start_talk(project: Path | str, node: str, python: str | None = None) -> TalkResult:
    """Open a conversation with one node. Never implicit -- somebody pressed a button (P11).

    Returns once the project has said it is listening, the way `run.start` returns once the
    application answers: what is waited for is the project's own word, not the existence of
    a process, which proves nothing.
    """
    from aibuilder_core.environment import project_interpreter
    from aibuilder_core.observe import probe_script

    root = Path(project).resolve()
    records = _read_state(root)

    existing = records.get(node)
    if existing and _alive(int(existing.get("pid", 0) or 0)) and (str(root), node) in _LIVE:
        return TalkResult(
            True,
            "a conversation with this node is already open",
            node=node,
            running=True,
            offset=int(existing.get("offset", 0) or 0),
            open=_open_here(root),
        )
    if existing:
        stop_talk(root, node)
        records = _read_state(root)

    way, refusal = _way_to(root, node)
    if way is None:
        return TalkResult(False, refusal, node=node, open=_open_here(root))

    key = f"{uuid.uuid4()}"
    log = _log_for(root, key)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch()

    interpreter, _ = project_interpreter(root, python)
    plan = {
        "project": str(root),
        "modules": list(way.modules),
        "ask": "converse",
        "carrier": way.carrier,
        # Which conversation this is, decided by the node's kind and never by the probe
        # looking at what the carrier happens to be (P17.2).
        "how": way.how,
        "node": node,
    }

    try:
        with log.open("ab") as sink, (log.with_suffix(".err")).open("ab") as complaints:
            process = subprocess.Popen(  # noqa: S603 -- the command is ours, built above
                [interpreter, str(probe_script())],
                cwd=root,
                stdin=subprocess.PIPE,
                stdout=sink,
                # Kept apart, and that is the same rule one level down: the project's own
                # `print` would otherwise land in the middle of the event stream and make it
                # unreadable. Its output is not thrown away, because a crash on import is
                # exactly what somebody will need to read.
                stderr=complaints,
                start_new_session=True,
            )
    except OSError as exc:
        return TalkResult(False, f"the project could not be started: {exc}", node=node)

    try:
        assert process.stdin is not None
        process.stdin.write((json.dumps(plan) + "\n").encode("utf-8"))
        process.stdin.flush()
    except (OSError, ValueError) as exc:
        with contextlib.suppress(OSError):
            process.kill()
        return TalkResult(False, f"the project stopped listening: {exc}", node=node)

    spoke = _first_line(log, time.monotonic() + READY_TIMEOUT_S)
    if spoke is None or spoke.get("type") != "ready":
        with contextlib.suppress(OSError):
            process.kill()
            process.wait(timeout=5)
        detail = (
            str(spoke.get("detail", "")) or "the project refused the conversation"
            if spoke is not None
            else "the project did not answer in time"
        )
        return TalkResult(False, detail, node=node, open=_open_here(root))

    _LIVE[(str(root), node)] = process
    records[node] = {
        "pid": process.pid,
        "log": key,
        "carrier": way.carrier,
        "how": way.how,
        "started_at": _now(),
    }
    _write_state(root, records)
    return TalkResult(
        True,
        str(spoke.get("detail", "")) or "the project is listening",
        node=node,
        running=True,
        open=_open_here(root),
    )


def say_to(project: Path | str, node: str, text: str) -> TalkResult:
    """Ask one thing. What comes back arrives through `poll_talk`, never through here."""
    root = Path(project).resolve()
    process = _LIVE.get((str(root), node))
    if process is None or process.poll() is not None:
        _LIVE.pop((str(root), node), None)
        return TalkResult(
            False,
            "no conversation is open with this node -- start one first",
            node=node,
            open=_open_here(root),
        )

    try:
        assert process.stdin is not None
        process.stdin.write((json.dumps({"say": text}) + "\n").encode("utf-8"))
        process.stdin.flush()
    except (OSError, ValueError) as exc:
        return TalkResult(False, f"the project stopped listening: {exc}", node=node)
    return TalkResult(True, "asked", node=node, running=True, open=_open_here(root))


def poll_talk(project: Path | str, node: str, offset: int = 0) -> TalkResult:
    """What the node has said since `offset`. Polled; nothing is ever pushed (P13)."""
    root = Path(project).resolve()
    record = _read_state(root).get(node)
    if record is None:
        return TalkResult(False, "no conversation has been opened with this node", node=node)

    log = _log_for(root, str(record.get("log", "")))
    if not log.is_file():
        return TalkResult(False, "the conversation left no record", node=node, offset=offset)

    try:
        with log.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
            here = handle.tell()
    except OSError as exc:
        return TalkResult(False, f"the record could not be read: {exc}", node=node, offset=offset)

    events: list[dict[str, Any]] = []
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line; the next poll gets it whole
        if isinstance(parsed, dict):
            events.append(_event(parsed))

    process = _LIVE.get((str(root), node))
    running = process is not None and process.poll() is None
    return TalkResult(
        True,
        "",
        node=node,
        running=running,
        events=tuple(events),
        offset=here,
        open=_open_here(root),
    )


def _event(raw: dict[str, Any]) -> dict[str, Any]:
    """One line of the probe's stream, in the shape the wire declares.

    Normalised rather than passed through, for the same reason `session.py` normalises the
    agent's stream: the probe's wire is between two halves of this toolchain and is free to
    change, while what a client is promised must not. Every event has all four fields, so a
    reader never has to ask whether a key is there before looking at it.
    """
    kind = str(raw.get("type", "")) or "said"
    return {
        "type": kind,
        "text": str(raw.get("text", "")),
        "detail": str(raw.get("detail", "")),
        # Kept, because the one thing somebody debugging a broken agent actually wants is
        # where it broke -- and it is already in hand at the moment it is thrown away.
        "trace": str(raw.get("traceback", "")),
    }


def talk_status(project: Path | str) -> TalkResult:
    """Which nodes have a conversation open. Reads; starts nothing."""
    root = Path(project).resolve()
    open_now = _open_here(root)
    return TalkResult(
        True,
        f"{len(open_now)} conversation(s) open" if open_now else "no conversation open",
        running=bool(open_now),
        open=open_now,
    )


def stop_talk(project: Path | str, node: str) -> TalkResult:
    """Close one conversation -- this sidecar's, or one a crashed sidecar left behind."""
    root = Path(project).resolve()
    records = _read_state(root)
    record = records.pop(node, None)
    process = _LIVE.pop((str(root), node), None)

    if process is not None and process.stdin is not None:
        # Closing the pipe is how the probe is told there is nothing more to answer: it is
        # reading lines, and end of input is the end of the conversation.
        with contextlib.suppress(OSError):
            process.stdin.close()

    pid = int(record.get("pid", 0) or 0) if record else 0
    if pid and _alive(pid):
        # Started in its own group, so it takes its children with it. Failing to signal is
        # not a failure to stop: the record is cleared either way, and a process nobody can
        # signal is not one this session is going to talk to again.
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(pid), signal.SIGTERM)

    if process is not None:
        # Reaped, not merely killed: a child nobody waited on answers "yes" to being alive.
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover -- the probe ignored SIGTERM
            process.kill()
            process.wait(timeout=5)

    _write_state(root, records)
    return TalkResult(True, "conversation closed", node=node, open=_open_here(root))


def close_everything_started_here() -> None:
    """Close every conversation this sidecar opened. Called when the sidecar goes away."""
    for project, node in list(_LIVE):
        with contextlib.suppress(Exception):
            stop_talk(Path(project), node)


# -- a conversation as evidence (P17.4) -------------------------------------------
#
# A person asked a real question, a real process ran the real code, and something real came
# back: that is exactly what I-5 asks for, and it is the rank `run.call` already has (Q19).
# Two rules keep it honest and neither is negotiable.
#
# **Test evidence still outranks it**, and that ranking lives in `probe.run_plan` and nowhere
# else -- which is why nothing here decides anything. This side reads what was said and hands
# it to the plan; the probe is where it is weighed against the run.
#
# **A conversation nobody had proves nothing.** Nothing is synthesised, nothing is remembered
# past the conversation it belongs to: closing one takes its record with it, so a node goes
# back to being unproven rather than keeping somebody's yesterday. That is the same rule
# `ServerResult` follows -- an answer is evidence about the run that produced it, and a
# toolchain that wrote it down would be showing a colleague a claim they never tested.


def conversations_held(project: Path | str) -> dict[str, dict[str, str]]:
    """What each open conversation proved about the node it addresses.

    Read out of the transcript rather than tallied as it goes: the log is already the record
    of what happened, and a counter kept beside it would be a second account of the same
    thing that could disagree with it.
    """
    root = Path(project).resolve()
    held: dict[str, dict[str, str]] = {}
    for node, record in _read_state(root).items():
        verdict = _what_was_said(_log_for(root, str(record.get("log", ""))))
        if verdict is not None:
            held[node] = verdict
    return held


def _what_was_said(log: Path) -> dict[str, str] | None:
    """The verdict one transcript supports, or `None` when it supports none.

    A question that broke the node is evidence of breakage, the same way a failing test is:
    the exchange ran, and something in the node went wrong in it. A conversation that was
    opened and never asked anything is `None` -- an open pipe is not an answer.
    """
    if not log.is_file():
        return None
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    answers = 0
    last: dict[str, Any] | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or parsed.get("type") not in ("answer", "failed"):
            continue
        # `ready` and `asked` are not exchanges: only what came back is.
        last = parsed
        if parsed.get("type") == "answer":
            answers += 1

    if last is None:
        return None
    if last.get("type") == "failed":
        return {
            "status": "failed",
            "detail": f"the last question broke it: {last.get('detail', '')}",
        }
    return {
        "status": "passed",
        "detail": f"answered {answers} question(s) asked from its node",
    }
