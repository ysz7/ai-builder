"""`Run`: call one system's export, in the project's own interpreter, once.

**This is not the graph being executed, and the distinction is the whole reason it is
allowed.** There is no traversal here, no order, no wiring: a person opened one node and
asked for the one function the convention says that node exports. Execution order lives in
Python, and if this file ever grew a notion of "and then the next node", the canvas would
have started deciding what runs when.

It is the seventh instance of the P13 shape and follows the same four rules as the shell,
the session and Observe:

* **Nothing is pushed.** Output is polled with an offset the caller keeps.
* **Nothing starts implicitly** (P11). A run exists because somebody pressed `Run`.
* What is started can be found again, and is ended on the way out.
* A refusal is a result, never a protocol fault.

## Why a subprocess, and why a driver written as text

The core imports no user code, ever. Calling `search` in this process would put a stranger's
package on the sidecar's `sys.path`, and a project that hangs or calls `sys.exit` would cost
the window rather than a process. So the call happens in a child, driven by a script written
into the run's own directory — text rather than a module of ours, for the same reason
Observe's network guard is text: the child must not be able to import `framestack_core`, and
a `.py` file of ours read off disk would not survive freezing.

## What a run is not

**A run colours nothing.** Green is earned by a test that passed under measurement (I-3), and
this is not that: it is one call, with input a person typed, proving only that it returned.
Nothing here writes an observation, and a caller that folded a successful run into a verdict
would have reinvented the thing this rebuild exists to remove.

For the same reason the network is **not** guarded here, where Observe guards it absolutely:
Observe must be reproducible (I-4) so a run that reached the network proves nothing, whereas
an agent that cannot call a model is an agent that cannot be tried at all. A run makes no
claim, so it may do what it likes.

## The document list

`.framestack/documents.json` records the paths a person handed to `index` **from this
window**. It is tooling state beside the layout and the observation, not a claim about what
the index contains: the convention gives a RAG package two exports and neither of them lists
anything, and inventing a third would be adding to the contract. Delete the file and the only
thing lost is the memory of which files were uploaded here.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from framestack_core.environment import interpreter_for
from framestack_core.parser import Node, is_system, read_graph
from framestack_core.usage import METER, record_ledger

__all__ = [
    "DOCUMENTS_PATH",
    "LIMIT_SECONDS",
    "RunOutcome",
    "RunResult",
    "close_everything_run_here",
    "last_run",
    "read_run",
    "start_run",
    "stop_run",
]

#: Everything one run needs: the driver, the request it was given, the answer it left.
WORKSPACE_PATH = Path(".framestack") / "run"

#: What a person handed to `index`, per node. See the module docstring: a memory of uploads,
#: never a statement about the index.
DOCUMENTS_PATH = Path(".framestack") / "documents.json"

#: How long one call may take before it is abandoned.
#:
#: A limit rather than none, for the reason Observe has one: a verb that never answers leaves
#: the panel polling something that will not reply, with no way to ask again. Generous,
#: because an agent talking to a model is slow and that is the ordinary case here.
LIMIT_SECONDS = 300

#: What each kind may be asked to do, and which export answers. Derived from the convention
#: and nothing else -- there is no action here that is not one of the exports in the table,
#: because an action that called something the convention does not require would be this
#: toolchain inspecting an implementation.
ACTIONS: dict[str, dict[str, str]] = {
    "rag": {"search": "search", "index": "index"},
    "agent": {"run": "run"},
    "api": {"request": "app"},
    "worker": {"handle": "HANDLERS", "handlers": "HANDLERS"},
}


# -- what the child is told ------------------------------------------------------------------

#: The driver, as text. Written into the run's own directory, which is the only file in it.
#:
#: It reads a request, imports the node's package, calls the one export the action names, and
#: writes what came back. It never prints to stdout: stdout belongs to the project's own code,
#: which is what the person watches while it runs, and a line of ours in there would be this
#: toolchain putting words in somebody's program's mouth.
_DRIVER = '''"""Written by Framestack for one Run. Not part of this project."""

import asyncio
import dataclasses
import importlib
import json
import sys
import traceback

_ROOT, _REQUEST, _ANSWER = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, _ROOT)


def _plain(value, depth=0):
    """What can cross a JSON boundary, with the object's own words as the fallback.

    `str(value)` rather than a refusal, because the point of showing a result is to show what
    came back. A repr is a poorer answer than a structure and a better one than nothing.
    """
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = dataclasses.fields(value)
        return {one.name: _plain(getattr(value, one.name), depth + 1) for one in fields}
    if isinstance(value, dict):
        return {str(k): _plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item, depth + 1) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


async def _drive(app, method, path, query, body):
    """One HTTP request through a plain ASGI application.

    Written against the ASGI specification and against no framework: the export is `app`, and
    what it was built with is nobody's business here. Lifespan is offered because the
    specification says an application may want it, and ignored when the application does not.
    """
    with_lifespan = None
    try:
        events = asyncio.Queue()
        await events.put({"type": "lifespan.startup"})
        answered = asyncio.Queue()

        async def receive_lifespan():
            return await events.get()

        async def send_lifespan(message):
            await answered.put(message)

        scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
        with_lifespan = asyncio.ensure_future(app(scope, receive_lifespan, send_lifespan))
        await asyncio.wait_for(answered.get(), timeout=20)
    except Exception:
        # An application with no lifespan handler raises or returns; both mean "not offered",
        # and neither is a reason not to make the request.
        if with_lifespan is not None:
            with_lifespan.cancel()
        with_lifespan = None

    got = []
    sent = [body.encode("utf-8")]

    async def receive():
        return {"type": "http.request", "body": sent.pop() if sent else b"", "more_body": False}

    async def send(message):
        got.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.1"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query.encode("utf-8"),
            "root_path": "",
            "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 0),
            "server": ("localhost", 80),
        },
        receive,
        send,
    )

    if with_lifespan is not None:
        with_lifespan.cancel()

    status, headers, chunks = 0, [], b""
    for message in got:
        if message.get("type") == "http.response.start":
            status = message.get("status", 0)
            headers = [
                [k.decode("latin-1", "replace"), v.decode("latin-1", "replace")]
                for k, v in message.get("headers", [])
            ]
        elif message.get("type") == "http.response.body":
            chunks += message.get("body", b"")

    if status == 0:
        raise RuntimeError("the application answered nothing -- it may not handle this scope")
    return {"status": status, "headers": headers, "body": chunks.decode("utf-8", errors="replace")}


def _export(module, name):
    if not hasattr(module, name):
        raise AttributeError(module.__name__ + " does not export " + name)
    return getattr(module, name)


def _call(module, action, given):
    if action == "search":
        keywords = {}
        if isinstance(given.get("top_k"), int):
            keywords["top_k"] = given["top_k"]
        return _export(module, "search")(str(given.get("query", "")), **keywords)

    if action == "index":
        paths = [str(one) for one in given.get("paths") or []]
        if not paths:
            raise ValueError("index takes a list of paths, and none were given")
        _export(module, "index")(paths)
        return {"indexed": paths}

    if action == "run":
        return _export(module, "run")(str(given.get("message", "")))

    if action == "request":
        path = str(given.get("path", "/"))
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        return asyncio.run(
            _drive(
                _export(module, "app"),
                str(given.get("method", "GET")).upper(),
                path if path.startswith("/") else "/" + path,
                query,
                str(given.get("body", "")),
            )
        )

    if action == "handlers":
        return sorted(_export(module, "HANDLERS"))

    if action == "handle":
        handlers = _export(module, "HANDLERS")
        name = str(given.get("handler", ""))
        if name not in handlers:
            known = ", ".join(sorted(handlers))
            raise KeyError(name + " is not one of this worker's handlers: " + known)
        payload = given.get("payload")
        return handlers[name](payload if isinstance(payload, dict) else {})

    raise ValueError("unknown action " + repr(action))


def main():
    with open(_REQUEST, "r", encoding="utf-8") as handle:
        request = json.load(handle)

    try:
        module = importlib.import_module(request["module"])
        value = _call(module, request["action"], request.get("input") or {})
        answer = {"ok": True, "value": _plain(value), "error": ""}
    except BaseException:
        answer = {"ok": False, "value": None, "error": traceback.format_exc()}

    with open(_ANSWER, "w", encoding="utf-8") as handle:
        json.dump(answer, handle)
'''


# -- the answer ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOutcome:
    """What one call returned, or the traceback it raised. Never a verdict.

    `value` is opaque on purpose: it is the export's own return, and a shape declared for it
    here would be this toolchain having an opinion about what somebody's `search` returns.
    """

    node: str
    action: str
    #: When it finished, in UTC. Of the call, never of anything inside it.
    at: str
    ok: bool
    value: Any
    #: The child's traceback, verbatim. `""` when it returned.
    error: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "action": self.action,
            "at": self.at,
            "ok": self.ok,
            "value": self.value,
            "error": self.error,
        }


@dataclass(frozen=True)
class RunResult:
    """The answer to every verb here. A refusal is a result, never a protocol fault."""

    ok: bool
    detail: str
    node: str = ""
    action: str = ""
    running: bool = False
    #: What the project's own code printed since the offset that was asked for.
    output: str = ""
    #: Where the reader got to. Kept by the caller and handed back (P13).
    offset: int = 0
    #: The last call this node answered, or `None` where it has never been run.
    outcome: RunOutcome | None = None
    #: What was handed to `index` from here. Empty for every kind but RAG.
    documents: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "action": self.action,
            "running": self.running,
            "output": self.output,
            "offset": self.offset,
            "outcome": None if self.outcome is None else self.outcome.as_dict(),
            "documents": list(self.documents),
        }


@dataclass
class _Call:
    """One export, running. Held by the sidecar; the record on disk is what outlives it."""

    project: str
    node: str
    action: str
    process: subprocess.Popen[bytes]
    workspace: Path
    log: Path
    started: float
    #: What the ledger files this run's calls under. Unique per press rather than a
    #: timestamp: two runs in the same second are two runs, and a panel showing "the last
    #: run" has to be able to tell them apart.
    ticket: str = ""
    watcher: threading.Thread | None = None


#: Every call this sidecar started, keyed by the project and the node it is about. One per
#: node rather than one per project: two systems answering at once is ordinary, and two calls
#: into the *same* system would write over each other's answer.
_CALLS: dict[tuple[str, str], _Call] = {}


# -- where a run keeps things --------------------------------------------------------------


def _safe(node: str) -> str:
    """A node id as a file name. Ids are dotted paths, so only a separator can surprise us."""
    return node.replace("/", "-").replace("\\", "-") or "node"


def _workspace(root: Path, node: str) -> Path:
    return root / WORKSPACE_PATH / _safe(node)


def _log_for(root: Path, node: str) -> Path:
    return _workspace(root, node) / "output.log"


def _answer_for(root: Path, node: str) -> Path:
    """Beside the workspace rather than inside it.

    The workspace is emptied at the start of every call, and the answer must not be: a panel
    that blanked the last result the instant a new call started would say the node had never
    been run, which is a different claim from "it is running again".
    """
    return root / WORKSPACE_PATH / f"{_safe(node)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stored(root: Path, node: str) -> RunOutcome | None:
    """The last call this node answered, read back from disk.

    Read rather than remembered, so a window that was closed mid-run finds the answer when it
    comes back -- the same reason Observe stores its verdict set.
    """
    path = _answer_for(root, node)
    if not path.is_file():
        return None
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict):
        return None
    return RunOutcome(
        node=str(held.get("node", node)),
        action=str(held.get("action", "")),
        at=str(held.get("at", "")),
        ok=bool(held.get("ok", False)),
        value=held.get("value"),
        error=str(held.get("error", "")),
    )


def _store(root: Path, outcome: RunOutcome) -> None:
    path = _answer_for(root, outcome.node)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(outcome.as_dict(), indent=2), encoding="utf-8")


def _documents(root: Path) -> dict[str, list[str]]:
    path = root / DOCUMENTS_PATH
    if not path.is_file():
        return {}
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(held, dict):
        return {}
    return {
        str(node): [str(one) for one in paths]
        for node, paths in held.items()
        if isinstance(paths, list)
    }


def _remember_documents(root: Path, node: str, paths: list[str]) -> None:
    """Add what was just indexed, keeping the order it was added in and adding nothing twice."""
    held = _documents(root)
    known = held.get(node, [])
    for one in paths:
        if one not in known:
            known.append(one)
    held[node] = known
    path = root / DOCUMENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(held, indent=2), encoding="utf-8")


# -- deciding whether a call can be made ----------------------------------------------------


def _node_of(root: Path, node: str) -> tuple[Node | None, str]:
    """The node, or why there is nothing to run.

    Read from the graph rather than from the path a caller sent: a run is a call into a
    system the parser recognises, and taking a directory name on trust would let the panel
    ask for a package the convention has never heard of.
    """
    for found in read_graph(root).nodes:
        if found.id == node:
            if not is_system(found):
                # A file and an MCP server are both "not a package", and each is told so in
                # its own words: a shared sentence would have to be vague enough to fit both,
                # and a vague refusal is one a person cannot act on.
                if found.kind == "file":
                    return None, f"{node} is a file, and a file has no export to call"
                return None, (
                    f"{node} is an MCP server, which is somebody else's program — "
                    "nothing here starts it"
                )
            return found, ""
    return None, f"there is no system called {node!r} here"


def _module_of(node: Node) -> str:
    """The dotted name the child imports. The path, which is what the convention makes it."""
    return node.path.replace("/", ".")


def _running(root: Path, node: str) -> bool:
    """Is a call still going?

    Membership of `_CALLS`, never `process.poll()` -- for the reason Observe uses the same
    rule: the child exiting is not the end of the run, because its answer still has to be
    read, and a caller told "idle" in that window would take the *previous* result for this
    one.
    """
    return (str(root), node) in _CALLS


# -- running one --------------------------------------------------------------------------


def _bank(root: Path, call: _Call) -> None:
    """Move the meter's lines into the ledger. Never a reason a run reports failure."""
    ledger = call.workspace / "usage.jsonl"
    try:
        lines = ledger.read_text(encoding="utf-8") if ledger.is_file() else ""
    except OSError:
        return
    if lines.strip():
        record_ledger(root, call.node, call.ticket, lines)


def _watch(call: _Call) -> None:
    """Wait for the child and write down what it left.

    In a thread rather than in `read_run`, so the answer exists whether or not anybody is
    looking. It always writes something and it always stops running: a call that ended
    without leaving a result would leave the panel polling a thing that will never answer.
    """
    root = Path(call.project)
    try:
        try:
            call.process.wait(timeout=LIMIT_SECONDS)
        except subprocess.TimeoutExpired:
            _end(call)
            # Measured all the same: a call that ran for five minutes and was abandoned
            # spent whatever it spent, and a ledger that only recorded successes would
            # understate the bill in exactly the case a person is looking it up for.
            _bank(root, call)
            _store(
                root,
                RunOutcome(
                    call.node,
                    call.action,
                    _now(),
                    False,
                    None,
                    f"the call did not finish within {LIMIT_SECONDS} seconds",
                ),
            )
            return

        answer = call.workspace / "answer.raw.json"
        outcome: RunOutcome
        if answer.is_file():
            held = json.loads(answer.read_text(encoding="utf-8"))
            outcome = RunOutcome(
                call.node,
                call.action,
                _now(),
                bool(held.get("ok")),
                held.get("value"),
                str(held.get("error", "")),
            )
        else:
            # The child left nothing, which means it did not reach the end of the driver:
            # `os._exit`, a segfault, or a kill. Said as what it is rather than guessed at.
            outcome = RunOutcome(
                call.node,
                call.action,
                _now(),
                False,
                None,
                f"the call left no answer (the process exited {call.process.returncode})",
            )

        # What the meter counted, taken into the ledger here rather than in `read_run`, for
        # the reason the outcome is: the record has to exist whether or not anybody is
        # looking. A failed run is measured too — a call that cost money and then raised
        # cost money.
        _bank(root, call)

        if outcome.ok and call.action == "index":
            given = outcome.value
            paths = given.get("indexed") if isinstance(given, dict) else None
            if isinstance(paths, list):
                _remember_documents(root, call.node, [str(one) for one in paths])

        _store(root, outcome)
    except Exception as exc:  # noqa: BLE001 -- a bug here must not cost the answer entirely
        _store(
            root,
            RunOutcome(
                call.node,
                call.action,
                _now(),
                False,
                None,
                f"the call could not be read: {type(exc).__name__}: {exc}",
            ),
        )
    finally:
        _CALLS.pop((call.project, call.node), None)


def _end(call: _Call) -> None:
    """Stop the call and everything it started. Its own process group, so nothing survives."""
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(os.getpgid(call.process.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        call.process.wait(timeout=5)


def start_run(
    project: Path | str, node: str, action: str, given: dict[str, Any] | None = None
) -> RunResult:
    """Call one export, once. Never implicit (P11).

    Returns as soon as the child is running. What it returned arrives through `read_run`,
    which is also where the output is polled from.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return RunResult(False, f"there is no project at {root}", node, action)

    if _running(root, node):
        return RunResult(
            False, f"{node} is already running -- wait for it rather than starting a second", node
        )

    found, why = _node_of(root, node)
    if found is None:
        return RunResult(False, why, node, action)

    allowed = ACTIONS.get(found.kind, {})
    if action not in allowed:
        answers = ", ".join(sorted(allowed)) or "nothing"
        return RunResult(
            False,
            f"a {found.kind} node answers {answers}, not {action!r}",
            node,
            action,
        )

    # The export the action needs, checked before a process is spawned. An incomplete node is
    # the ordinary half-written case and it is named rather than attempted: importing it to
    # find out would cost a process to learn what the parser already read.
    needed = allowed[action]
    if needed in found.missing:
        return RunResult(
            False,
            f"{node} does not export {needed} yet, so there is nothing to call",
            node,
            action,
        )

    python = interpreter_for(root)
    if python is None:
        return RunResult(False, "no Python interpreter could be found to run this", node, action)

    workspace = _workspace(root, node)
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    # The driver, then the meter, then the call. In that order for a reason: the meter
    # patches a provider's client class, and a class patched after the project has already
    # imported and used it would count nothing. Neither half is in the project -- both are
    # written into `.framestack/` and deleted on the next run (I-6).
    (workspace / "driver.py").write_text(_DRIVER + METER + "\nmain()\n", encoding="utf-8")
    (workspace / "request.json").write_text(
        json.dumps({"module": _module_of(found), "action": action, "input": given or {}}),
        encoding="utf-8",
    )

    log = _log_for(root, node)
    log.write_bytes(b"")

    # The person's own environment, inherited whole. **No network guard, unlike Observe**:
    # a run proves nothing and colours nothing, so there is no reproducibility to protect,
    # and an agent that cannot reach a model is one nobody can try.
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        # Where the meter writes what a provider answered. One JSON line per call, taken
        # into the ledger by the watcher once the run is over.
        "FRAMESTACK_USAGE": str(workspace / "usage.jsonl"),
    }
    env.pop("PYTHONHOME", None)

    line = [
        str(python),
        # Unbuffered, so what the project prints arrives while it runs rather than in one
        # block at the end. The point of polling output is to watch it happen.
        "-u",
        str(workspace / "driver.py"),
        str(root),
        str(workspace / "request.json"),
        str(workspace / "answer.raw.json"),
    ]

    try:
        sink = log.open("wb")
        process = subprocess.Popen(  # noqa: S603 -- an interpreter and paths assembled here
            line,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        return RunResult(False, f"the call could not be started: {exc}", node, action)

    call = _Call(
        project=str(root),
        node=node,
        action=action,
        process=process,
        workspace=workspace,
        log=log,
        started=time.monotonic(),
        ticket=f"{_now()}-{uuid4().hex[:8]}",
    )
    call.watcher = threading.Thread(target=_watch, args=(call,), daemon=True)
    _CALLS[(str(root), node)] = call
    call.watcher.start()

    return RunResult(True, f"running {action}", node, action, running=True)


def read_run(project: Path | str, node: str, offset: int = 0) -> RunResult:
    """What the call has printed since `offset`, and what it returned once it has.

    The caller keeps the offset it was last given (P13). `running` going false and an
    `outcome` arriving in the same answer is the ordinary end of a call.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return RunResult(False, f"there is no project at {root}", node)

    log = _log_for(root, node)
    text, where = "", max(offset, 0)
    if log.is_file():
        try:
            raw = log.read_bytes()
            text = raw[where:].decode("utf-8", errors="replace")
            where = len(raw)
        except OSError:
            text = ""

    running = _running(root, node)
    held = _CALLS.get((str(root), node))
    return RunResult(
        True,
        "running" if running else "idle",
        node,
        held.action if held is not None else "",
        running=running,
        output=text,
        offset=where,
        outcome=_stored(root, node),
        documents=tuple(_documents(root).get(node, ())),
    )


def last_run(project: Path | str, node: str) -> RunResult:
    """What this node last returned, and what was uploaded to it. A read: it starts nothing."""
    root = Path(project).resolve()
    if not root.is_dir():
        return RunResult(False, f"there is no project at {root}", node)
    running = _running(root, node)
    return RunResult(
        True,
        "running" if running else "idle",
        node,
        running=running,
        outcome=_stored(root, node),
        documents=tuple(_documents(root).get(node, ())),
    )


def stop_run(project: Path | str, node: str) -> RunResult:
    """End a call somebody started. The watcher writes down that it was stopped."""
    root = Path(project).resolve()
    call = _CALLS.get((str(root), node))
    if call is None:
        return RunResult(False, f"nothing is running on {node}", node)
    _end(call)
    return RunResult(True, f"stopped {call.action}", node, call.action)


def close_everything_run_here() -> None:
    """End every call this sidecar started, on the way out.

    Nobody opened one of these to keep, unlike a shell: a call with nothing left to report to
    is a process running somebody's code for no reader, and it holds whatever that code
    started.
    """
    for call in list(_CALLS.values()):
        if call.process.poll() is None:
            _end(call)
    _CALLS.clear()
