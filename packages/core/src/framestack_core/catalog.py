"""Input B: the blueprint catalog, read as plain specification text.

A blueprint is documentation (§3). It carries architecture, contracts, failure modes and a
definition of done -- and it carries **no markup**, knows nothing about `bp`, and is not
allowed to teach the agent how to annotate. It works in bare Claude Code without this
application, which is exactly why it must not become a second place where the markup rules
live: the rules are in the system prompt, and a blueprint only makes the request more
precise.

Two consequences are mechanical here rather than left to good intentions:

- **Only `blueprint.md` is loaded.** A blueprint directory also holds `architecture.mmd`,
  and that diagram is an illustration for the human reading it. The application graph is
  built from annotated code and from nothing else (§3), so the diagram is never handed to
  the agent as if it were a target shape.
- **Markup found in a blueprint is reported, not obeyed.** `carries_markup` is a hygiene
  signal about the catalog. The brief's rules do not change because of it.

**The catalog is wherever the application says it is.** Nothing is discovered: no directory
next door is opened because it happens to be named the right thing, and no path is guessed
from where the process was started. A caller passes the location, or sets `CATALOG_ENV`,
or there is no catalog -- and no catalog is an answer ("input B is unavailable here"),
never a crash.

That is a deliberate narrowing. Reading a checkout that merely sits beside the project
would make what the agent is told depend on the shape of someone's disk, which is exactly
the kind of ambient input that is impossible to reason about when it goes wrong.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BLUEPRINT_FILE",
    "CATALOG_ENV",
    "Blueprint",
    "carries_markup",
    "find_catalog",
    "list_blueprints",
    "load_blueprint",
]

#: The one file a blueprint is read from. `architecture.mmd` beside it is deliberately not.
BLUEPRINT_FILE = "blueprint.md"

#: How the location is given when it is not passed in directly -- the frozen sidecar has no
#: repository around it, and there is nothing else for it to fall back on.
CATALOG_ENV = "FRAMESTACK_BLUEPRINTS"

#: The public sections of the catalog. Private ones are not ours to read from here.
SECTIONS = ("blueprints", "project-blueprints")

#: The spellings that mean "someone put our markup into a blueprint". Deliberately textual:
#: a blueprint is prose with code samples in it, not a module we parse.
_MARKUP_MARKERS = (
    "from bp import",
    "import bp",
    "@node(",
    "@editable",
    "@generated",
    "group_node(",
    "Param(",
)


@dataclass(frozen=True)
class Blueprint:
    """One catalog entry. `text` is present only once it has been loaded."""

    id: str
    title: str
    summary: str
    path: str
    section: str
    text: str | None = None
    #: Whether the text mentions the markup layer. Reported so the catalog can be cleaned;
    #: never a reason to take annotation rules from the blueprint (§3).
    carries_markup: bool = False


def find_catalog(explicit: Path | str | None = None) -> Path | None:
    """The catalog the caller named, or the one `CATALOG_ENV` points at, or nothing.

    A pointer that turns out not to hold a catalog answers `None`. It does not fall back to
    somewhere else: a caller that named a directory gets that directory or an honest
    nothing, never a different catalog than the one it asked for.

    `None` means input B is unavailable here. Input A is unaffected, because the two inputs
    differ only in how detailed the request is (§3).
    """
    if explicit is not None:
        return _catalog_or_none(Path(explicit))

    from_env = os.environ.get(CATALOG_ENV)
    return _catalog_or_none(Path(from_env)) if from_env else None


def _catalog_or_none(path: Path) -> Path | None:
    return path.resolve() if _is_catalog(path) else None


def _is_catalog(path: Path) -> bool:
    return any((path / section).is_dir() for section in SECTIONS)


def list_blueprints(catalog: Path | str | None = None) -> list[Blueprint]:
    """Every blueprint the catalog offers, without its text.

    Titles and summaries come from `catalogue.json` when the catalog publishes one, and
    from the document itself when it does not -- the index is a convenience, and a catalog
    without one is still readable.
    """
    root = find_catalog(catalog)
    if root is None:
        return []

    index = _read_index(root)
    found: list[Blueprint] = []
    for section in SECTIONS:
        directory = root / section
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            document = entry / BLUEPRINT_FILE
            if not document.is_file():
                continue
            meta = index.get(entry.name, {})
            found.append(
                Blueprint(
                    id=entry.name,
                    title=meta.get("title") or _title_of(document),
                    summary=meta.get("description") or "",
                    path=str(document),
                    section=section,
                )
            )
    return found


def load_blueprint(blueprint_id: str, catalog: Path | str | None = None) -> Blueprint | None:
    """Read one blueprint's specification text. `None` when the catalog has no such entry.

    Only `BLUEPRINT_FILE` is read. Whatever else the directory holds -- the diagram above
    all -- stays where it is.
    """
    for blueprint in list_blueprints(catalog):
        if blueprint.id != blueprint_id:
            continue
        text = Path(blueprint.path).read_text(encoding="utf-8")
        return Blueprint(
            id=blueprint.id,
            title=blueprint.title,
            summary=blueprint.summary,
            path=blueprint.path,
            section=blueprint.section,
            text=text,
            carries_markup=carries_markup(text),
        )
    return None


def carries_markup(text: str) -> bool:
    """Does this blueprint mention the markup layer at all?

    A blueprint that does is not wrong to load -- it is a catalog hygiene problem, and the
    agent's rules come from the prompt either way.
    """
    return any(marker in text for marker in _MARKUP_MARKERS)


def _read_index(root: Path) -> dict[str, dict[str, str]]:
    """The catalog's own index, if it publishes one. A broken index is simply not used."""
    path = root / "catalogue.json"
    if not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}

    index: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        if isinstance(identifier, str):
            index[identifier] = {
                "title": str(item.get("title") or ""),
                "description": str(item.get("description") or ""),
            }
    return index


def _title_of(document: Path) -> str:
    """The document's own first heading, for a catalog with no index."""
    try:
        with document.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return document.parent.name
