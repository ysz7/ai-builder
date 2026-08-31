"""`Open`: put a file in front of the person, in their own editor, at the line.

The fourth of the four commands, and the smallest. It exists because the settings panel
promises it: every control points at the line it edits, so a person can always leave the
interface and look at the code it is talking about. **That escape hatch is not a
convenience.** The claim of this whole product is that the code is the source of truth, and a
panel with no way through to the file would be asking somebody to take that on faith.

Two rules.

**Ask rather than read.** Which editor a person uses is their business and the answer is on
their machine — an environment variable they set, a command on their `PATH`, or the
association their operating system already holds. Nothing here keeps a list of editors it
prefers or a setting for choosing one; it tries what is there, in the order a person's own
configuration implies, and reports what it did.

**Only inside the project.** A path that climbs out of the project directory is refused. This
verb takes a path from a caller and hands it to a program, and the caller is a webview.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["Opened", "open_in_editor"]

#: Editors that can be told a line, and how they want to be told.
#:
#: `{path}` and `{line}` are filled in. Tried in this order **only when the person has not
#: said** which editor they use -- `$VISUAL` and `$EDITOR` come first, because somebody who
#: set one has already answered this question and a preference of ours would override it.
LINE_AWARE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cursor", ("--goto", "{path}:{line}")),
    ("code", ("--goto", "{path}:{line}")),
    ("zed", ("{path}:{line}",)),
    ("subl", ("{path}:{line}",)),
    ("idea", ("--line", "{line}", "{path}")),
    ("pycharm", ("--line", "{line}", "{path}")),
)


@dataclass(frozen=True)
class Opened:
    """Whether it opened, and with what. A refusal is a result, as everywhere else."""

    ok: bool
    detail: str
    #: The program that was run, so the answer says what happened rather than only that it did.
    editor: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "editor": self.editor}


def _system_opener() -> tuple[str, ...] | None:
    """The operating system's own association. It cannot be told a line, and that is fine.

    A file open at the top is still the file. Refusing to open anything because the line
    cannot be honoured would trade the whole feature for the last five percent of it.
    """
    if platform.system() == "Darwin":
        return ("open",)
    found = shutil.which("xdg-open")
    return ("xdg-open",) if found else None


def _chosen() -> tuple[str, tuple[str, ...]] | None:
    """What the person said to use, if they said anything.

    Taken as a **command line, not a program name**, because that is how these variables are
    written in the world -- `code -w`, `emacsclient -nw`. The line number is not appended: an
    editor we were handed by name is one whose flags we do not know, and inventing a `+123`
    for a program that reads it as a filename would be worse than opening at the top.
    """
    for name in ("FRAMESTACK_EDITOR", "VISUAL", "EDITOR"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        parts = raw.split()
        if shutil.which(parts[0]):
            return parts[0], tuple(parts[1:])
    return None


def open_in_editor(project: Path | str, path: str, line: int = 0) -> Opened:
    """Open one of the project's files, at `line` where the editor can be told one."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        return Opened(False, f"there is no project at {root}")

    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        # The path came from a caller and is about to be handed to another program. A file
        # outside the project is not this verb's to open, whatever the caller meant by it.
        return Opened(False, "that path is outside the project")
    if not target.exists():
        return Opened(False, f"there is no file at {path}")

    at = max(line, 1)

    said = _chosen()
    if said is not None:
        program, flags = said
        return _run([program, *flags, str(target)], program)

    for name, pattern in LINE_AWARE:
        found = shutil.which(name)
        if not found:
            continue
        arguments = [piece.format(path=str(target), line=at) for piece in pattern]
        return _run([found, *arguments], name)

    opener = _system_opener()
    if opener is None:
        return Opened(
            False,
            "no editor was found -- set $EDITOR to the one you use and it will be used",
        )
    return _run([*opener, str(target)], opener[0])


def _run(line: list[str], editor: str) -> Opened:
    """Start it and let go.

    Not waited on, and deliberately: a terminal editor started this way would hold the call
    open until the person closed it, and a graphical one usually returns at once but is not
    obliged to. What is reported is that it was started, which is the honest claim.
    """
    try:
        subprocess.Popen(  # noqa: S603 -- a program the person's own machine offered
            line,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return Opened(False, f"{editor} could not be started: {exc}", editor)
    return Opened(True, f"opened in {editor}", editor)
