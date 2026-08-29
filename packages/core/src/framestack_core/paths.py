"""What counts as project source, and what a file is called in Python terms.

Shared by the strip and the parser so the two always look at the same set of files. A
parser that saw a module the strip skipped would build a graph node whose markup never
comes off -- and I-2 would fail somewhere far away from the cause.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

__all__ = ["SKIP_DIRECTORIES", "iter_python_files", "module_name", "package_name"]

#: Directories that are never project source: caches, environments, version control.
SKIP_DIRECTORIES = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
    }
)


def iter_python_files(root: Path) -> Iterator[Path]:
    """Every `.py` file under `root`, in a stable order.

    Sorted because the graph is compared against snapshots and against itself; a traversal
    whose order depended on the filesystem would produce diffs that mean nothing.
    """
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        yield path


def module_name(path: Path, root: Path) -> str:
    """The dotted module name for a file: `app/api/users.py` -> `app.api.users`."""
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def package_name(path: Path, root: Path) -> str:
    """The package a file lives in -- what its relative imports resolve against."""
    relative = path.relative_to(root)
    return ".".join(relative.parent.parts)
