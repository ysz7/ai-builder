"""Whether the project has changed since the caller last looked (Phase 13).

The graph updates as the code changes, without a button. What makes that possible without
breaking the wire's one rule — **nothing is pushed** — is that this is a *question*: the
caller holds a revision number, asks whether it still stands, and re-parses when it does not.
The same shape as every log offset in this codebase, pointed at a directory tree.

## What counts as a change

Files the parser actually reads: Python, and the four config files the convention names. A
README saving is not a change to the graph, and re-parsing for one would be answering a
question nobody asked.

`.git/`, `__pycache__/`, `.venv/`, `node_modules/` and `.framestack/` are skipped, and so is
**every directory whose name starts with a dot** — one rule instead of a list that grows.
Nothing importable lives in one, and tooling state is exactly what fills them.

## Settled, not merely changed

A save is reported once the tree has stopped moving for `SETTLE` — the plan's 300ms, spent
where it matters. An editor writes a file in two steps and a formatter writes it again a
moment later; a re-parse between them reads half a file and draws a node with an export
missing. Waiting is what makes "the graph follows the code" true rather than jumpy.

**A turn's writes are not this module's problem.** The agent writes several files per task,
and the caller already re-parses when the turn ends; it simply does not ask while one is
running. That keeps the rule in the one place that knows a turn exists, rather than teaching
a directory scanner about the chat.

## Why a scan and not a watcher library

A file-system event API is a dependency, three platform backends and a permission prompt on
one of them. A scan of the files the parser reads — a few hundred `stat` calls, skipping the
directories above — costs a fraction of a millisecond of CPU each second, which is the
acceptance criterion ("does not pin a core") met by doing almost nothing rather than by
tuning something. It is also the same walk the parser does, so a project that is cheap to
parse is cheap to watch.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "IGNORED",
    "SETTLE",
    "Watched",
    "forget_watch",
    "read_watch",
    "stop_watching_everything",
]

#: Directories that never hold code the parser reads. The plan names five; the dot rule in
#: `_skip` covers three of them and every future one of that shape.
IGNORED = frozenset({"__pycache__", "node_modules", "dist", "build"})

#: The four files the convention names, beside every `.py`. A change to anything else is not
#: a change to the graph.
WATCHED_FILES = frozenset({".env", "compose.yaml", "Dockerfile", "mcp.json"})

#: How long the tree has to stop moving before a change is reported. The plan's 300ms:
#: perceived as immediate, and long enough not to read a file an editor is halfway through.
SETTLE = 0.3

#: How often the tree is looked at. Under the settle time, so a save is noticed within it.
BEAT = 0.25


@dataclass(frozen=True)
class Watched:
    """Whether anything the parser reads has changed since `revision`."""

    ok: bool
    detail: str
    #: An opaque number the caller keeps and sends back. It only ever moves forward.
    revision: int
    #: Whether it moved since the one the caller sent. `False` on the first ask, which is
    #: how a caller gets a revision without being told the project changed the moment it
    #: opened — a graph it has just read is not stale.
    changed: bool
    #: The paths that differ, so a caller can say what moved. Capped: this is a hint for a
    #: person, not a change set, and the answer to it is always the same — re-read the graph.
    files: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "revision": self.revision,
            "changed": self.changed,
            "files": list(self.files),
        }


#: How many changed paths are named. More than a handful is "a lot changed", which is one
#: fact rather than forty.
NAMED = 8


@dataclass
class _Tree:
    """One project, watched. Held by the sidecar; it describes a directory, not a project."""

    root: Path
    signature: dict[str, float]
    revision: int
    #: What the last scan saw, before it settled. A change is taken up into `signature` only
    #: once two scans agree — see the module docstring.
    pending: dict[str, float] | None = None
    since: float = 0.0
    changed: tuple[str, ...] = ()
    thread: threading.Thread | None = None
    stop: threading.Event | None = None


_TREES: dict[str, _Tree] = {}
_LOCK = threading.Lock()


def _skip(name: str) -> bool:
    """Whether to walk into a directory. One rule and a short list, in that order."""
    return name.startswith(".") or name in IGNORED


def _watched(name: str) -> bool:
    return name.endswith(".py") or name in WATCHED_FILES


def _scan(root: Path) -> dict[str, float]:
    """The modification time of every file the parser would read, keyed by path.

    Times rather than contents: a hash of the tree would be correct and would read every
    byte of the project once a second, which is the thing this is written to avoid. A save
    that does not change the time is a save no editor makes.
    """
    found: dict[str, float] = {}
    stack = [root]
    while stack:
        here = stack.pop()
        try:
            with os.scandir(here) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not _skip(entry.name):
                                stack.append(Path(entry.path))
                        elif _watched(entry.name):
                            found[entry.path] = entry.stat().st_mtime
                    except OSError:
                        # A file that vanished between the listing and the stat. Ordinary
                        # while an editor writes, and not worth a whole scan.
                        continue
        except OSError:
            continue
    return found


def _differences(before: dict[str, float], after: dict[str, float]) -> tuple[str, ...]:
    moved = [path for path, when in after.items() if before.get(path) != when]
    gone = [path for path in before if path not in after]
    return tuple(sorted(moved + gone))


def _loop(tree: _Tree) -> None:
    """Scan, wait for it to settle, then move the revision on. One thread per project."""
    stop = tree.stop
    assert stop is not None
    while not stop.wait(BEAT):
        seen = _scan(tree.root)
        with _LOCK:
            if seen == tree.signature:
                tree.pending = None
                continue
            if tree.pending != seen:
                # Still moving. Start the settle window again rather than reporting a file
                # an editor has not finished writing.
                tree.pending = seen
                tree.since = time.monotonic()
                continue
            if time.monotonic() - tree.since < SETTLE:
                continue
            tree.changed = _differences(tree.signature, seen)[:NAMED]
            tree.signature = seen
            tree.pending = None
            tree.revision += 1


def read_watch(project: Path | str, revision: int = 0) -> Watched:
    """Has anything the parser reads changed since `revision`?

    The first ask starts the watch and answers `changed: false` with the current revision:
    a caller that has just read the graph is not stale, and telling it otherwise would make
    every window re-parse the moment it opened.

    Starting a thread here is not a contradiction of "nothing starts implicitly" — that rule
    is about somebody else's programs and somebody's money. This is a `stat` loop over a
    directory the caller is already looking at, and it stops when the project is closed.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return Watched(False, f"there is no project at {root}", 0, False)

    where = str(root)
    with _LOCK:
        tree = _TREES.get(where)
        if tree is None:
            tree = _Tree(root=root, signature=_scan(root), revision=1)
            tree.stop = threading.Event()
            tree.thread = threading.Thread(target=_loop, args=(tree,), daemon=True)
            _TREES[where] = tree
            tree.thread.start()
            return Watched(True, "watching", tree.revision, False)

        if revision <= 0 or revision >= tree.revision:
            return Watched(True, "unchanged", tree.revision, False)
        return Watched(
            True,
            f"{len(tree.changed)} file(s) changed",
            tree.revision,
            True,
            tree.changed,
        )


def forget_watch(project: Path | str) -> Watched:
    """Stop watching one project. Its thread ends; nothing it saw is kept."""
    where = str(Path(project).resolve())
    with _LOCK:
        tree = _TREES.pop(where, None)
    if tree is None:
        return Watched(True, "nothing was being watched here", 0, False)
    if tree.stop is not None:
        tree.stop.set()
    return Watched(True, "stopped watching", tree.revision, False)


def stop_watching_everything() -> None:
    """On the way out. A thread per project is a thread per project left running otherwise."""
    with _LOCK:
        trees = list(_TREES.values())
        _TREES.clear()
    for tree in trees:
        if tree.stop is not None:
            tree.stop.set()
