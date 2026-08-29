"""Where the person put things on the canvas.

The fifth file in `.framestack/`, and it belongs to the same family as the other four: the
snapshot, the run record, the worker record and the agent log are all state the toolchain
keeps *about* a project without the project depending on any of it. Delete this one and
nothing changes except that the nodes come back in different places.

**The core stores it and refuses to understand it.** What is in here is `id -> whatever the
canvas needs` -- coordinates today, a collapsed flag beside them, something else in a year --
and the core never looks inside. That refusal is the protection, not laziness: the moment
this module knows what a coordinate is, the next reasonable-sounding request is for the core
to *produce* a layout, and a graph laid out by the toolchain is a graph the toolchain has an
opinion about. It has none. Nodes come from code (I-1); this says where to draw them and
cannot add one, remove one or rename one.

Why it is here at all rather than in the shell (Q13, amended): the webview may call
`core_request` and nothing else, and a new capability is a new method here -- never a new
Tauri command. Putting it in a filesystem plugin would mean a second implementation the
moment a second client exists, and two implementations of one thing drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["LAYOUT_PATH", "LayoutWrite", "create_project", "read_layout", "write_layout"]

#: Beside the snapshot and the run records. Tooling state, never project source.
LAYOUT_PATH = Path(".framestack") / "layout.json"


@dataclass(frozen=True)
class LayoutWrite:
    """Whether it was stored. A refusal is a result, like every other write here."""

    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail}


def read_layout(project: Path | str) -> dict[str, Any]:
    """What was stored, or nothing at all.

    Every failure reads as "nothing stored": an absent file, an unreadable one, a truncated
    one. A canvas with no saved positions is an ordinary state -- it is what a project looks
    like the first time it is opened -- so there is no failure here worth reporting as one,
    and a corrupt cache must never stop a graph from being drawn.
    """
    path = Path(project) / LAYOUT_PATH
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return stored if isinstance(stored, dict) else {}


def write_layout(project: Path | str, layout: dict[str, Any]) -> LayoutWrite:
    """Store it, whole. The previous contents are replaced, never merged.

    Merging would be the core having an opinion about what an entry means -- which key wins,
    what a missing one implies -- and it has none. The client holds the whole layout and
    sends the whole layout.
    """
    path = Path(project) / LAYOUT_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Serialised first: a payload that will not serialise must not leave a truncated
        # file behind where a readable one was.
        text = json.dumps(layout, indent=2, sort_keys=True)
        path.write_text(text + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        return LayoutWrite(False, f"the layout could not be stored: {type(exc).__name__}: {exc}")
    return LayoutWrite(True, f"{len(layout)} entry(s) stored")


def create_project(parent: Path | str, name: str) -> LayoutWrite:
    """Make an empty directory for a project the agent has not written yet.

    Empty on purpose. A scaffold would be the toolchain deciding what a project is before
    anybody said what it is for -- and the graph would then show nodes nobody asked for. The
    directory is the whole of it; the first thing in it comes from a generation.

    Refuses to touch a directory that already has something in it. Opening an existing
    project is what the other button is for, and quietly adopting one here would be a
    surprise with somebody's files in it.
    """
    root = Path(parent).expanduser() / name.strip()
    if not name.strip():
        return LayoutWrite(False, "a project needs a name")
    if root.exists() and any(root.iterdir()):
        return LayoutWrite(False, f"{root} already has something in it -- open it instead")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return LayoutWrite(False, f"the project could not be created: {exc}")
    return LayoutWrite(True, str(root))
