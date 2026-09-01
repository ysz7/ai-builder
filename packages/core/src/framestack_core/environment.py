"""Which Python a project's own code runs in.

One question, asked in one place, because three things now need the same answer: Observe runs
the suite, `Run` calls an export, and each of them must do it in **the project's** interpreter
rather than ours. Two copies of this rule would eventually disagree, and the disagreement
would show up as a run that proved something about the toolchain's environment and reported
it as a fact about somebody's code.

Nothing here installs anything (P11). A missing interpreter is an answer.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

__all__ = ["interpreter_for"]


def interpreter_for(root: Path) -> Path | None:
    """The Python this project's own code should run in, or `None` if there is none.

    The project's own environment first, because that is where its dependencies are. Ours is
    a fallback and not a preference: running somebody's code against the toolchain's packages
    would prove something about our environment and call it a fact about their code.
    """
    candidates: list[Path] = [
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    ]
    active = os.environ.get("VIRTUAL_ENV")
    if active:
        candidates += [Path(active) / "bin" / "python", Path(active) / "Scripts" / "python.exe"]
    # Never when frozen: `sys.executable` is then this sidecar's own binary, and running a
    # module against it runs the core rather than the project.
    if not getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable))
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
