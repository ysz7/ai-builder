"""Colour, and where it comes from.

This is the differentiator, stated as a mechanism. In every flow-document builder a node is
green **because it exists** — the document is the source of truth and the code is an export,
so there is nothing for a colour to be earned against. Here a node is green because a test
that passed executed code inside it, and that is the only way it can become green.

So the rule this module exists to keep is I-3: **green is earned by a run.** A check that
could not run reports `skipped`, never green. There is no path through this file that
invents a verdict, and the absence of one is what the whole product rests on.

## What a run is

`Observe` runs **the project's own test suite**, in the project's own interpreter, under
`coverage.py`, in a subprocess. Nothing is imported into this process; a project that hangs
or crashes costs a subprocess rather than the core the window is talking to. Nothing is
installed and no environment is created (P11) — if the project's interpreter cannot import
`pytest` and `coverage`, that is a `skipped` with the reason said, not a `pip install`
somebody did not ask for.

Two facts are joined to produce a verdict, and both come from the run:

* **coverage.py's dynamic contexts** say which test function executed which file.
* **pytest's JUnit XML** says which test functions passed and which failed.

They meet on the test's name. Nothing else is consulted — not a naming convention, not a
directory layout, not a guess about which test "belongs to" which package. A node is green
because a passing test ran its code, and the coverage database is what says so.

## Package granularity, and no finer

A verdict is about a package. There are no verdicts on functions and there will not be: that
would need a second mechanism beside the convention, and building a second mechanism is what
produced the problem this rebuild is fixing. Coverage is read at file level and unioned over
the package's own files — a parent's own files, never its children's, because the children
are nodes with verdicts of their own.

## Reproducibility, and what is actually enforced

Invariant 4 says three consecutive runs on an unchanged project produce an identical verdict
set. Two things are enforced **mechanically**, in the child process:

* **The network is denied, and touching it voids the run.** A check that reaches the network
  passes or fails for reasons outside the repository, so it cannot be reproduced and must
  not colour anything. The attempt is *recorded* as well as refused — a test that catches
  the refusal and reports success would otherwise earn a green node by swallowing the very
  thing that makes the run worthless. This is also what "must not call a model" means in
  practice: a model call is a network call.
* **The temp directory is fresh for every run**, so no suite can share a path between runs,
  and hash randomisation and the timezone are pinned.

Two are **not** enforced mechanically, and saying so is better than implying otherwise: a
suite may still read the wall clock, and it may still bind a fixed port. Refusing either
would rule out large amounts of reasonable code — a fixed-port bind is how most service
tests are written — and a guard that broke honest projects would be worse than the flake it
prevents. What catches those is the repeat check the plan asks for: Observe three times, and
compare the verdict sets. A project that fails it has a test to fix, and the test says so.

## The shape

The sixth thing in this codebase that starts a process, and it follows the same rules as the
other five: **nothing is pushed** — output is polled with an offset the caller keeps;
**nothing starts implicitly** — a run exists because somebody pressed Observe; **a record on
disk survives a crash** — the last verdict set is in `.framestack/observation.json`, so a
window that reopens knows what it knew. A suite can take minutes, and a verb that blocked
the wire for the duration would freeze the terminal and the chat along with it.
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
from xml.etree import ElementTree

from framestack_core.environment import interpreter_for
from framestack_core.parser import Node, is_system, read_graph

__all__ = [
    "OBSERVATION_PATH",
    "Observation",
    "ObserveResult",
    "Verdict",
    "close_everything_observed_here",
    "last_observation",
    "read_observation",
    "start_observation",
]

#: The last verdict set, beside the layout and the shell logs. Tooling state about a
#: project, never project source: delete it and the only thing lost is the memory of a run.
OBSERVATION_PATH = Path(".framestack") / "observation.json"

#: Everything one run needs and nothing the project keeps: the coverage database, the JUnit
#: report, the guard, and the run's own `TMPDIR`. Emptied at the start of every run, which
#: is how "no suite shares a temp path between runs" is enforced rather than requested.
WORKSPACE_PATH = Path(".framestack") / "observe"

#: What the person watches while it runs.
LOG_PATH = Path(".framestack") / "observe.log"

#: How long a suite may take before the run is abandoned as `skipped`.
#:
#: A limit rather than none, because the alternative to a limit is a verb that never answers:
#: a test that waits on something that will not arrive would leave Observe running for the
#: life of the window, with no verdict and no way to ask for one.
LIMIT_SECONDS = 600

#: The five states a node can be in, and each is a different claim.
#:
#: `grey` is "no test reached it" and `skipped` is "the run did not happen" — the difference
#: matters, because the first is a fact about the project and the second is a fact about the
#: attempt. Collapsing them would let a broken environment read as untested code.
GREEN, RED, AMBER, GREY, SKIPPED = "green", "red", "amber", "grey", "skipped"


# -- what the child is told ---------------------------------------------------------------

#: The guard, as text rather than as a module of ours that the child imports.
#:
#: Text because the child must not import `framestack_core`: the core's package would be on
#: a stranger's `sys.path` for the length of their test run, able to shadow their modules and
#: to be shadowed by them. This is written into the run's own directory instead, where it is
#: the only file, and the directory is thrown away afterwards. It also survives freezing,
#: which a `.py` file of ours read off disk would not.
#:
#: `sitecustomize` rather than a pytest plugin because `site` imports it before anything else
#: the run will do, including collection. A project with a `sitecustomize` of its own is
#: shadowed for the length of the run; that is a real cost, and it is smaller than a network
#: call slipping through during collection.
_GUARD = '''"""Written by Framestack for one Observe run. Not part of this project.

The network is denied here because a check that reaches it is not evidence: it passes or
fails for reasons outside the repository, so a run that touched it cannot be reproduced and
must not colour anything. The attempt is recorded as well as refused -- a test that catches
the refusal and reports success would otherwise earn a green node by swallowing the very
thing that makes the run worthless.

Loopback is allowed. A test talking to something it started itself inside the run is still
self-contained, and denying it would rule out every service test there is.
"""

import os
import socket

_RECORD = os.environ.get("FRAMESTACK_NETWORK_LOG", "")
_LOCAL = {"127.0.0.1", "::1", "localhost", "", "0.0.0.0", "::"}


def _is_local(address):
    # Not an internet address at all -- an AF_UNIX path, say. Nothing leaves the machine.
    if not isinstance(address, (tuple, list)) or not address:
        return True
    host = address[0]
    return isinstance(host, str) and host in _LOCAL


def _refuse(what, address):
    if _RECORD:
        try:
            with open(_RECORD, "a", encoding="utf-8") as sink:
                sink.write("%s %r\\n" % (what, address))
        except OSError:
            pass
    raise OSError("Observe denies the network: %s %r" % (what, address))


_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_getaddrinfo = socket.getaddrinfo


def _guarded_connect(self, address):
    if _is_local(address):
        return _connect(self, address)
    return _refuse("connect", address)


def _guarded_connect_ex(self, address):
    if _is_local(address):
        return _connect_ex(self, address)
    return _refuse("connect", address)


def _guarded_getaddrinfo(host, *args, **kw):
    if host is None or host in _LOCAL:
        return _getaddrinfo(host, *args, **kw)
    return _refuse("resolve", host)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex
socket.getaddrinfo = _guarded_getaddrinfo
'''


# -- the answer ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """What was proven about one node, and by what."""

    node: str
    #: `green`, `red`, `amber`, `grey` or `skipped`.
    verdict: str
    #: Why, in a sentence. Empty on green: there is nothing on the other side of it.
    reason: str
    #: The tests that executed this node's own code, as pytest names them. This is the
    #: evidence itself rather than a summary of it — a person can paste one into a terminal.
    tests: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "verdict": self.verdict,
            "reason": self.reason,
            "tests": list(self.tests),
        }


@dataclass(frozen=True)
class Observation:
    """One run, kept whole.

    The timestamp and the commit are what make it a claim about a *state of the code* rather
    than a floating fact: a verdict set with no commit beside it is one nobody can tell is
    stale, and stale evidence read as current is the failure mode this whole design is
    arranged against.
    """

    #: When, in UTC, ISO-8601. Of the observation, never of anything inside it.
    at: str
    #: What the project was at, as `git` reports it. `""` outside a repository.
    commit: str
    ok: bool
    detail: str
    verdicts: tuple[Verdict, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "commit": self.commit,
            "ok": self.ok,
            "detail": self.detail,
            "verdicts": [verdict.as_dict() for verdict in self.verdicts],
        }


@dataclass(frozen=True)
class ObserveResult:
    """The answer to every verb here. A refusal is a result, never a protocol fault."""

    ok: bool
    detail: str
    running: bool = False
    #: What the run printed since the offset that was asked for.
    output: str = ""
    #: Where the reader got to. Kept by the caller and handed back (P13).
    offset: int = 0
    #: The last verdict set, or `None` where nothing has ever been observed here.
    observation: Observation | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "running": self.running,
            "output": self.output,
            "offset": self.offset,
            "observation": None if self.observation is None else self.observation.as_dict(),
        }


@dataclass
class _Run:
    """One suite, running. Held by the sidecar; the record on disk is what outlives it."""

    project: str
    process: subprocess.Popen[bytes]
    workspace: Path
    log: Path
    started: float
    #: The thread that waits for the process and turns what it left behind into a verdict
    #: set. It runs whether or not anybody polls, so a window closed mid-run still finds the
    #: answer written down when it comes back.
    reader: threading.Thread | None = None


#: Every run this sidecar started, keyed by the project it is about. One per project: two
#: suites in the same directory would write over each other's coverage database, and the
#: second answer would be about a run that never happened.
_RUNS: dict[str, _Run] = {}


# -- finding something to run it with ------------------------------------------------------


def _can_run(python: Path) -> str:
    """`""` when the suite can be run with this interpreter, or why it cannot.

    Asked rather than assumed, and asked of the interpreter itself. Nothing is installed to
    make the answer yes (P11): a missing dependency is a fact about the project's environment
    and the person is owed it plainly, not a `pip install` they did not ask for.
    """
    try:
        probe = subprocess.run(  # noqa: S603 -- an interpreter this function just located
            [str(python), "-c", "import coverage, pytest"],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{python} could not be run: {type(exc).__name__}: {exc}"
    if probe.returncode != 0:
        return (
            f"{python} cannot import pytest and coverage, so the suite cannot be run under "
            "measurement -- install them in the project's environment and observe again"
        )
    return ""


def _commit_of(root: Path) -> str:
    """What the project is at, asked of `git` rather than read out of `.git`.

    The parser learns no file format and neither does this: a reader for somebody else's
    directory layout is a second opinion about a thing that already has a first one.
    """
    try:
        answer = subprocess.run(  # noqa: S603, S607 -- git, by name, on the person's PATH
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return answer.stdout.strip() if answer.returncode == 0 else ""


# -- reading what the run left behind -------------------------------------------------------


def _outcomes(junit: Path) -> dict[str, tuple[str, str]] | None:
    """Every test the run reported: `context key -> (outcome, the name a person would type)`.

    The key is what coverage calls the same test. coverage names a dynamic context
    `<test module basename>.<function>` while JUnit splits it into a dotted `classname` and a
    `name`, so the join is the last segment of the one plus the other. Two test modules with
    the same basename would collide here; pytest already refuses that layout without
    `__init__.py` files, and inventing a second disambiguation would be inventing evidence.

    `None` when the report is absent or unreadable, which is a run that cannot be believed
    rather than a run with no tests in it.
    """
    if not junit.is_file():
        return None
    try:
        tree = ElementTree.parse(junit)
    except (OSError, ElementTree.ParseError):
        return None

    found: dict[str, tuple[str, str]] = {}
    for case in tree.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        if not name:
            continue
        outcome = "passed"
        for child in case:
            if child.tag in ("failure", "error"):
                outcome = "failed"
                break
            if child.tag == "skipped":
                outcome = "skipped"
        # `file` is what pytest writes under `junit_family=xunit1`, and it is the real path
        # rather than a reconstruction of one from the dotted class name.
        where = case.get("file") or classname.replace(".", "/") + ".py"
        found[f"{classname.rsplit('.', 1)[-1]}.{name}"] = (outcome, f"{where}::{name}")
    return found


def _reached(data_file: Path) -> dict[str, set[str]] | None:
    """Which tests executed which file, read from the coverage database.

    Asked of `coverage` rather than of the SQLite behind it, for the reason nothing here
    reads somebody else's file format directly. The empty context is dropped on purpose: it
    is code that ran at *import* time, before any test function was entered, and a module
    that was merely imported during collection has not been proven by anything.
    """
    if not data_file.is_file():
        return None
    try:
        from coverage.sqldata import CoverageData

        data = CoverageData(basename=str(data_file))
        data.read()
    except Exception:  # noqa: BLE001 -- a database we cannot read is a run we cannot believe
        return None

    out: dict[str, set[str]] = {}
    for measured in data.measured_files():
        contexts: set[str] = set()
        for found in data.contexts_by_lineno(measured).values():
            contexts.update(context for context in found if context)
        out[os.path.realpath(measured)] = contexts
    return out


# -- turning that into colour ----------------------------------------------------------------


def _own_files(node: Node, root: Path) -> set[str]:
    """The Python this node is answerable for: its own, never its children's.

    The parser already leaves a nested system's files out of its parent's list, so this is
    the same boundary the graph draws, read once. A parent that counted its children's
    coverage as its own would be green because somebody else's test passed.
    """
    return {os.path.realpath(root / name) for name in node.files if name.endswith(".py")}


def _leaf_verdict(
    node: Node,
    root: Path,
    outcomes: dict[str, tuple[str, str]],
    reached: dict[str, set[str]],
) -> tuple[str, str, tuple[str, ...]]:
    """`(verdict, reason, tests)` for one node's own code.

    Red wins over green, and it is not a tie-break: a package with one passing test and one
    failing test has something wrong with it, and a colour that reported the good news would
    be a colour nobody could act on.
    """
    keys: set[str] = set()
    for file in _own_files(node, root):
        keys |= reached.get(file, set())

    named = sorted(
        {outcomes[key][1] for key in keys if key in outcomes},
    )
    failing = sorted(
        {outcomes[key][1] for key in keys if key in outcomes and outcomes[key][0] == "failed"},
    )
    passing = [key for key in keys if key in outcomes and outcomes[key][0] == "passed"]

    if failing:
        return RED, f"{failing[0]} failed", tuple(named)
    if passing:
        return GREEN, "", tuple(named)
    return GREY, "no test reached it", tuple(named)


def _aggregate(own: str, children: list[str]) -> str:
    """A parent's colour, from its own code and its children's.

    Amber is a **distinct state, not a shade of green**: "everything I could check passed and
    something was never checked" is a different claim from "everything passed", and a design
    that blended them would be spending the earned colour on an unearned one.
    """
    parts = [own, *children]
    if RED in parts:
        return RED
    if all(part == GREEN for part in parts):
        return GREEN
    return AMBER


def _verdicts(
    root: Path,
    junit: Path,
    data_file: Path,
) -> tuple[Observation | None, str]:
    """Every node's verdict, or the reason there is none. Never both, and never a guess."""
    outcomes = _outcomes(junit)
    reached = _reached(data_file)
    if outcomes is None:
        return None, "the run left no test report behind, so nothing about it can be believed"
    if reached is None:
        return None, "the run left no coverage database behind, so nothing was measured"

    graph = read_graph(root)
    systems = [node for node in graph.nodes if is_system(node)]

    own: dict[str, tuple[str, str, tuple[str, ...]]] = {
        node.id: _leaf_verdict(node, root, outcomes, reached) for node in systems
    }

    verdicts: list[Verdict] = []
    for node in systems:
        verdict, reason, tests = own[node.id]
        if node.children:
            children = [own[child][0] for child in node.children if child in own]
            rolled = _aggregate(verdict, children)
            if rolled != verdict:
                grey = [child for child in node.children if child in own and own[child][0] == GREY]
                red = [child for child in node.children if child in own and own[child][0] == RED]
                reason = (
                    f"{red[0]} is red" if red else f"{len(grey)} of its parts were never reached"
                )
            verdict = rolled
        verdicts.append(Verdict(node.id, verdict, reason, tests))

    return (
        Observation(
            at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            commit=_commit_of(root),
            ok=True,
            detail=f"{len(outcomes)} test(s), {len(verdicts)} node(s)",
            verdicts=tuple(verdicts),
        ),
        "",
    )


def _skipped(root: Path, detail: str) -> Observation:
    """Every node `skipped`, with the same reason on each. **Nothing turns green.**

    The one function in this module that produces a verdict without a run, and it produces
    exactly one verdict: the honest one. A check that could not run has proven nothing, and
    the colour for "proven nothing" must never be the colour for "proven fine" (I-3).
    """
    graph = read_graph(root)
    return Observation(
        at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        commit=_commit_of(root),
        ok=False,
        detail=detail,
        verdicts=tuple(
            Verdict(node.id, SKIPPED, detail, ()) for node in graph.nodes if is_system(node)
        ),
    )


# -- storing it ------------------------------------------------------------------------------


def _store(root: Path, observation: Observation) -> None:
    """Write the verdict set down, whole. A failure here costs the memory and nothing else."""
    path = root / OBSERVATION_PATH
    with contextlib.suppress(OSError, TypeError, ValueError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(observation.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def _stored(root: Path) -> Observation | None:
    """What was observed here last, or nothing at all.

    Every failure reads as "nothing observed": absent, unreadable, truncated, or written by a
    version that shaped it differently. A project that has never been observed is the
    ordinary first state, and a corrupt record must never stop the graph from being drawn --
    it must certainly never be repaired into a colour.
    """
    path = root / OBSERVATION_PATH
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return Observation(
            at=str(loaded["at"]),
            commit=str(loaded["commit"]),
            ok=bool(loaded["ok"]),
            detail=str(loaded["detail"]),
            verdicts=tuple(
                Verdict(
                    node=str(item["node"]),
                    verdict=str(item["verdict"]),
                    reason=str(item["reason"]),
                    tests=tuple(str(name) for name in item["tests"]),
                )
                for item in loaded["verdicts"]
            ),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# -- running it --------------------------------------------------------------------------------


def _prepare(root: Path, packages: list[str]) -> Path:
    """The run's own directory, emptied first.

    Emptied rather than reused, and that is a determinism rule made mechanical: a suite
    cannot share a temp path between runs if the path did not exist a moment ago. The
    coverage database goes with it, so no run can be credited with a line an earlier one
    executed.
    """
    workspace = root / WORKSPACE_PATH
    shutil.rmtree(workspace, ignore_errors=True)
    (workspace / "tmp").mkdir(parents=True, exist_ok=True)

    (workspace / "sitecustomize.py").write_text(_GUARD, encoding="utf-8")

    # A configuration file of our own rather than the project's: `dynamic_context` has no
    # command-line flag, and reading the project's `.coveragerc` would let a repository
    # decide how it is measured -- which is a project marking its own homework.
    measured = "\n    ".join(packages)
    (workspace / "coverage.ini").write_text(
        "[run]\n"
        f"data_file = {workspace / 'coverage'}\n"
        "dynamic_context = test_function\n"
        "branch = False\n"
        "parallel = False\n"
        f"source =\n    {measured}\n",
        encoding="utf-8",
    )
    return workspace


def _watch(run: _Run) -> None:
    """Wait for the suite, then turn what it left behind into a verdict set.

    In a thread rather than in `read_observation`, so the answer is written down whether or
    not anybody is looking: a window closed mid-run has to find the verdict when it comes
    back, and a person who never polls has still run their tests.

    **It always writes something and it always stops running.** The `finally` is not
    defensive tidying: a run that ended without leaving a verdict would leave the interface
    polling a thing that will never answer, and that is the one failure mode a person cannot
    get out of from the window.
    """
    root = Path(run.project)
    workspace = run.workspace

    try:
        _store(root, _decide(run, root, workspace))
    except Exception as exc:  # noqa: BLE001 -- a bug here must not cost the answer entirely
        _store(root, _skipped(root, f"the run could not be read: {type(exc).__name__}: {exc}"))
    finally:
        _RUNS.pop(run.project, None)


def _decide(run: _Run, root: Path, workspace: Path) -> Observation:
    """What the finished suite proved, or the reason it proved nothing."""
    try:
        code = run.process.wait(timeout=LIMIT_SECONDS)
    except subprocess.TimeoutExpired:
        _end(run)
        return _skipped(root, f"the suite did not finish within {LIMIT_SECONDS} seconds")

    touched = workspace / "network"
    if touched.is_file() and touched.stat().st_size > 0:
        first = touched.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        return _skipped(
            root,
            "the suite reached the network ("
            + (first[0] if first else "no detail")
            + "), so this run cannot be reproduced and colours nothing",
        )

    # 0 is all passed, 1 is tests failed, 5 is nothing collected -- three different projects
    # and three runs that happened. Everything else (an internal error, a usage error, an
    # interrupted collection) is a run that did not, and a run that did not happen proves
    # nothing rather than proving the code grey.
    if code not in (0, 1, 5):
        return _skipped(root, f"the suite could not be run (pytest exited {code})")

    observation, why = _verdicts(root, workspace / "junit.xml", workspace / "coverage")
    return observation if observation is not None else _skipped(root, why)


def _end(run: _Run) -> None:
    """Stop the suite and everything it started. Its own process group, so nothing survives."""
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(os.getpgid(run.process.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        run.process.wait(timeout=5)


def _running(root: Path) -> bool:
    """Is a run still going here?

    **Membership of `_RUNS`, never `process.poll()`.** The suite exiting is not the end of
    the run: the coverage database and the test report still have to be read, and a caller
    told "idle" in that window would find the *previous* verdict set sitting there and take
    it for the new one. The watcher removes the entry once it has written the answer down,
    which makes this the same question as "is there an answer yet".
    """
    return str(root) in _RUNS


def start_observation(project: Path | str) -> ObserveResult:
    """Run the project's tests and colour the graph from what happened. Never implicit (P11).

    Returns as soon as the suite is running. What it decides arrives through
    `read_observation`, which is also where the output is polled from.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return ObserveResult(False, f"there is no project at {root}")

    if _running(root):
        return ObserveResult(
            False, "a run is already going here -- wait for it rather than starting a second"
        )

    graph = read_graph(root)
    packages = [node.path for node in graph.nodes if is_system(node)]
    if not packages:
        # Nothing to measure, so nothing is started. A project with no system has no node to
        # colour, and spawning a suite to discover that would be a process nobody asked for.
        observation = Observation(
            at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            commit=_commit_of(root),
            ok=True,
            detail="there is no system here to observe",
            verdicts=(),
        )
        _store(root, observation)
        return ObserveResult(True, observation.detail, observation=observation)

    python = interpreter_for(root)
    if python is None:
        observation = _skipped(root, "no Python interpreter could be found to run the suite")
        _store(root, observation)
        return ObserveResult(False, observation.detail, observation=observation)

    refusal = _can_run(python)
    if refusal:
        observation = _skipped(root, refusal)
        _store(root, observation)
        return ObserveResult(False, observation.detail, observation=observation)

    workspace = _prepare(root, packages)
    log = root / LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"")

    # The person's own environment, with the determinism keys overridden. Inherited rather
    # than scrubbed because a suite that needs a `DATABASE_URL` should still work; what makes
    # the run reproducible is the guard and the fresh temp directory, not an empty `environ`.
    env = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([str(workspace), os.environ.get("PYTHONPATH", "")]).rstrip(
            os.pathsep
        ),
        "TZ": "UTC",
        "TMPDIR": str(workspace / "tmp"),
        "FRAMESTACK_NETWORK_LOG": str(workspace / "network"),
    }
    env.pop("PYTHONHOME", None)

    line = [
        str(python),
        "-m",
        "coverage",
        "run",
        "--rcfile",
        str(workspace / "coverage.ini"),
        "-m",
        "pytest",
        "-q",
        # No cache written into somebody's repository, and no plugin that shuffles the order:
        # a suite that ran in a different order is a different run, and I-4 asks for the same
        # answer three times.
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
        "--junitxml",
        str(workspace / "junit.xml"),
        # The one family that records which file a test came from. Without it the test names
        # in a verdict would be reconstructed from a dotted class name rather than reported.
        "-o",
        "junit_family=xunit1",
    ]

    try:
        sink = log.open("wb")
        process = subprocess.Popen(  # noqa: S603 -- an interpreter and flags assembled here
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
        observation = _skipped(root, f"the suite could not be started: {exc}")
        _store(root, observation)
        return ObserveResult(False, observation.detail, observation=observation)

    run = _Run(
        project=str(root),
        process=process,
        workspace=workspace,
        log=log,
        started=time.monotonic(),
    )
    run.reader = threading.Thread(target=_watch, args=(run,), daemon=True)
    run.reader.start()
    _RUNS[str(root)] = run

    return ObserveResult(True, "observing", running=True)


def read_observation(project: Path | str, offset: int = 0) -> ObserveResult:
    """What the run has printed since `offset`, and the verdicts once there are any.

    The caller keeps the offset it was last given (P13). `running` going false and an
    `observation` arriving in the same answer is the ordinary end of a run.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return ObserveResult(False, f"there is no project at {root}")

    log = root / LOG_PATH
    text, where = "", max(offset, 0)
    if log.is_file():
        try:
            raw = log.read_bytes()
            text = raw[where:].decode("utf-8", errors="replace")
            where = len(raw)
        except OSError:
            text = ""

    running = _running(root)
    return ObserveResult(
        True,
        "observing" if running else "idle",
        running=running,
        output=text,
        offset=where,
        # The stored set, always: while a run is going it is still the last thing known, and
        # a canvas that blanked itself for the duration would be claiming the code got worse
        # because somebody pressed a button.
        observation=_stored(root),
    )


def last_observation(project: Path | str) -> ObserveResult:
    """The stored verdict set. A read: it starts nothing and proves nothing new."""
    root = Path(project).resolve()
    if not root.is_dir():
        return ObserveResult(False, f"there is no project at {root}")
    return ObserveResult(
        True,
        "observing" if _running(root) else "idle",
        running=_running(root),
        observation=_stored(root),
    )


def close_everything_observed_here() -> None:
    """End every suite this sidecar started, on the way out.

    A test run left behind is a process still writing into somebody's project with nothing
    left to report to -- and, unlike a shell, nobody opened it on purpose to keep.
    """
    for run in list(_RUNS.values()):
        if run.process.poll() is None:
            _end(run)
    _RUNS.clear()
