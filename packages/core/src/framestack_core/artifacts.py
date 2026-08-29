"""Nodes carried by a file rather than by a Python object (architecture §5.7).

A `Dockerfile` declares nothing, cannot hold a decorator, and is still part of the project.
It becomes a node here -- and the first rule is what keeps the rest of the system intact:

**The parser never sees this.** `parser.py` reads Python source into the IR and knows no
library and no file format. This module opens no Python, imports nothing from the project,
and **parses no file content at all**: it looks for the paths the registry declares and
reports what it found. Everything about what is *inside* those files is asked of the tool
that owns the format (§5.8) -- `docker compose config`, never a YAML reader of ours.

Three consequences of a file being the carrier, each one deliberate:

* **Identity is the path.** A Python node's id is declared (`@node(id=...)`); a file declares
  nothing, so the id is the project-relative path. It is stable across edits to the content,
  unique by construction, and a declared node that collides with it is a diagnostic rather
  than a silent overwrite.
* **Discovery is a registry, not a name match.** A kind names the paths that carry it, in
  the order the owning tool would consider them. There is no rule anywhere that says "a file
  with a familiar name becomes a node".
* **Nothing here is generated.** The file is the source of truth about itself. A node that
  wrote one out would make the file an output and the node the source -- I-1 inverted, in a
  place where no write of ours could be addressed or reconciled.
"""

from __future__ import annotations

from pathlib import Path

from framestack_core.ir import Location, Node
from framestack_core.kinds import REGISTRY, CarrierType

__all__ = ["read_artifacts"]


def read_artifacts(project: Path | str) -> tuple[Node, ...]:
    """Every artifact node the project has, found by path and by nothing else."""
    root = Path(project)
    found: list[Node] = []

    for kind in sorted(REGISTRY.values(), key=lambda entry: entry.name):
        if CarrierType.FILE not in kind.carriers or not kind.artifact:
            continue

        path = _first_present(root, kind.artifact)
        if path is None:
            continue

        relative = path.relative_to(root).as_posix()
        found.append(
            Node(
                id=relative,
                kind=kind.name,
                title=path.name,
                carrier=relative,
                carrier_type=CarrierType.FILE.value,
                location=Location(
                    file=relative,
                    object=path.name,
                    start_line=1,
                    end_line=_line_count(path),
                ),
            )
        )
    return tuple(found)


def _first_present(root: Path, candidates: tuple[str, ...]) -> Path | None:
    """The first candidate that exists, in the order the owning tool would consider them.

    One node per kind: a project with both `compose.yaml` and `docker-compose.yml` has one
    set of services, because docker reads one of those files and ignores the other. Showing
    two nodes would show a subsystem that does not exist.
    """
    return next((root / name for name in candidates if (root / name).is_file()), None)


def _line_count(path: Path) -> int:
    """The file's extent, for the address every node carries. Not an inspection of it.

    Counting newlines is not reading the format: nothing here decides anything from what the
    line says, and a file we cannot decode at all still has a node and an address.
    """
    try:
        with path.open("rb") as handle:
            return max(sum(1 for _ in handle), 1)
    except OSError:
        return 1
