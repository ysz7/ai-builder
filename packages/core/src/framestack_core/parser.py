"""The graph, derived from the project's own directories and imports.

This is the mechanism the rebuild exists for. The old parser read an annotation layer, so a
node existed because somebody had decorated it correctly and the agent had four constraints
to satisfy at once. This one reads a **convention**: a directory at the project root that
exports what its kind requires is a node, and nothing else is inspected.

    rag/      exports `search` and `index`   ->  RAG
    agent/    exports `run`                  ->  Agent
    api/      exports `app`                  ->  Service
    worker/   exports `HANDLERS`             ->  Worker

Three properties are load-bearing and every choice below is made to keep them:

**It is deterministic (I-2).** The answer is a function of the directory tree and the import
statements in it. No model, no heuristic, no guess about what a package "probably" is. A
directory that looks like a system but is missing its export is reported as incomplete with
the missing name said out loud, never repaired into something plausible.

**It never runs the project (P-static).** Everything here is `libcst.parse_module` over text
the core read itself. Drawing a graph must not execute a stranger's code, and a project that
hangs or raises on import must cost nothing at all -- so a package's exports are the names
its `__init__.py` *binds*, read syntactically, and never the contents of a real module
object.

**It has no opinion about a stack.** A node is defined by its export. An `agent/` exporting
`run` is an Agent whether it is LangGraph, Pydantic AI or a thirty-line loop; nothing here
imports a third-party package, reads a requirements file or branches on a framework name.
That is the whole reason there are four kinds here rather than the twenty-seven there were.

The walk is **recursive by exactly one level**, and it is written that way from the start
even though the canvas draws children collapsed: retrofitting nesting later would mean
rewriting the walk, the edge builder and the id scheme together.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import libcst as cst

__all__ = [
    "FILE_NODES",
    "REQUIRED",
    "Edge",
    "Graph",
    "Node",
    "read_graph",
]

#: The whole protocol. A directory named for a kind is a node when its `__init__.py` binds
#: every name listed here.
#:
#: RAG needs **both**: a package that can be queried but never filled is useless in
#: practice, and requiring `index` is what makes document ingestion a first-class action
#: rather than a special case somewhere in the UI.
REQUIRED: dict[str, tuple[str, ...]] = {
    "agent": ("run",),
    "api": ("app",),
    "rag": ("index", "search"),
    "worker": ("HANDLERS",),
}

#: Four files at the project root that are nodes with **no verdict** -- they are shown,
#: opened and edited, and never coloured. Nothing runs them, so nothing can prove them.
FILE_NODES: tuple[str, ...] = (".env", "compose.yaml", "Dockerfile", "mcp.json")


# What a directory of children is called: the plural of the kind, and nothing else is
# recognised. Derived rather than tabulated because the rule *is* "the plural of the kind" --
# a table would invite a special case, and a special case is a second mechanism.
def _plural(kind: str) -> str:
    return kind + "s"


# Directories the walk never treats as a candidate child. Not a filter on what a project may
# contain -- a leading dot or underscore says "not a package somebody is exporting", and
# `__pycache__` is the one that would otherwise show up in every project on earth.
def _ignored(name: str) -> bool:
    return name.startswith(".") or name.startswith("_")


@dataclass(frozen=True)
class Node:
    """One node of the graph: a system package, or one of the four root files.

    `missing` and `reason` are the incomplete case stated rather than hidden. A directory
    that looks like a system and is not one is the single most useful thing this parser can
    say, because it is the state a half-written package is in -- and guessing what it meant
    to be is exactly the behaviour the rebuild removed.
    """

    id: str
    #: What to call it on the canvas. The directory's own name; `researcher`, not
    #: `agent.researcher` -- the path says where it is, and the parent frame says whose.
    name: str
    #: One of `REQUIRED`, or `"file"`. Never a framework, never an implementation.
    kind: str
    #: Project-relative, POSIX separators. The core answers about a project it was handed;
    #: an absolute path here would put this machine's home directory into a payload.
    path: str
    #: True when every required export was found. File nodes are always complete: there is
    #: no contract for them to fail.
    complete: bool
    #: What this kind requires. Sent even when it is satisfied, because the node panel says
    #: what the contract *is*, not only when it is broken.
    exports: tuple[str, ...]
    #: The subset of `exports` the `__init__.py` does not bind.
    missing: tuple[str, ...]
    #: Why it is incomplete, in a sentence. `""` when it is not.
    reason: str
    #: The node that contains this one, or `""` at the top level.
    parent: str
    children: tuple[str, ...]
    #: Everything in the package except a nested system's own files, so the panel can list
    #: what this node is made of without listing its children twice.
    files: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "complete": self.complete,
            "exports": list(self.exports),
            "missing": list(self.missing),
            "reason": self.reason,
            "parent": self.parent,
            "children": list(self.children),
            "files": list(self.files),
        }


@dataclass(frozen=True)
class Edge:
    """A relation the project already states, never one drawn in the UI.

    There are two, and both are read rather than declared: `import`, which exists because
    one system package imports from another, and `mcp`, which exists because `mcp.json`
    configures a server. **No edge is ever created by hand** -- connecting two nodes means
    writing an import, which is a code edit made through the chat.
    """

    id: str
    source: str
    target: str
    #: `"import"` or `"mcp"`.
    kind: str
    #: The MCP server's name. `""` on an import edge: the fact is the import, and labelling
    #: it with one imported symbol would misreport a file that imports three.
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "label": self.label,
        }


@dataclass(frozen=True)
class Graph:
    """What a project is, as read. A refusal is a result, as everywhere else in the core."""

    ok: bool
    detail: str
    #: The project this is about, absolute, so a client holding several can tell them apart.
    root: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "root": self.root,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
        }


# -- reading a module ------------------------------------------------------------------


def _parse(path: Path) -> cst.Module | None:
    """The file as a tree, or nothing at all.

    Unreadable and unparseable are the same answer on purpose. Both mean "this package
    cannot be shown to export anything", which is a statement about the node rather than an
    error about the run -- a project with one broken file still has a graph.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return cst.parse_module(source)
    except cst.ParserSyntaxError:
        return None


def _bindings(statement: cst.BaseStatement, names: set[str]) -> None:
    """The module-level names one statement binds.

    Top-level statements only -- nothing inside an `if`, a `try` or a function. A name bound
    under `if TYPE_CHECKING:` does not exist at runtime, and one bound in an `except
    ImportError:` branch depends on which branch ran, which is a question only running the
    code can answer. Reading them would be this parser guessing, and it does not guess.

    A star import binds nothing here for the same reason: what `from .store import *` brings
    in is decided by the module it names and by that module's `__all__`. A package that
    re-exports its contract by star is asking the reader to run code, and the node says so
    -- with the missing export named -- rather than being credited with a symbol nobody in
    this process has seen.
    """
    if isinstance(statement, cst.FunctionDef | cst.ClassDef):
        names.add(statement.name.value)
        return

    if not isinstance(statement, cst.SimpleStatementLine):
        return

    for small in statement.body:
        if isinstance(small, cst.Assign):
            for target in small.targets:
                _targets(target.target, names)
        elif isinstance(small, cst.AnnAssign):
            # `x: int` on its own is an annotation, not a binding: the name does not exist.
            if small.value is not None:
                _targets(small.target, names)
        elif isinstance(small, cst.Import):
            for alias in small.names:
                if alias.asname is not None:
                    _targets_from_asname(alias.asname, names)
                else:
                    # `import a.b.c` binds `a`, not `a.b.c`.
                    names.add(_dotted(alias.name).split(".")[0])
        elif isinstance(small, cst.ImportFrom):
            if isinstance(small.names, cst.ImportStar):
                continue
            for alias in small.names:
                if alias.asname is not None:
                    _targets_from_asname(alias.asname, names)
                else:
                    names.add(_dotted(alias.name))


def _targets(node: cst.BaseExpression, names: set[str]) -> None:
    """A name, or the names inside a tuple or list unpacking. Attributes bind nothing."""
    if isinstance(node, cst.Name):
        names.add(node.value)
    elif isinstance(node, cst.Tuple | cst.List):
        for element in node.elements:
            _targets(element.value, names)


def _targets_from_asname(asname: cst.AsName, names: set[str]) -> None:
    _targets(asname.name, names)


def _dotted(node: cst.BaseExpression) -> str:
    """`a.b.c` as a string. Anything that is not a plain dotted name reads as empty."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr.value}" if head else ""
    return ""


def _exports_of(init: Path) -> frozenset[str] | None:
    """Every name the `__init__.py` binds at module level, or `None` if it cannot be read."""
    module = _parse(init)
    if module is None:
        return None
    names: set[str] = set()
    for statement in module.body:
        _bindings(statement, names)
    return frozenset(names)


def _imports_of(path: Path, package: str) -> set[str]:
    """The absolute module paths one file imports, relatives resolved against `package`.

    Relative imports are resolved here rather than left alone because an edge is a fact
    about two packages, and `from ..rag import search` states it exactly as plainly as the
    absolute form does. Resolving it is arithmetic on the containing package's parts, which
    is the same arithmetic Python does.
    """
    module = _parse(path)
    if module is None:
        return set()

    found: set[str] = set()
    parts = package.split(".") if package else []

    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            if isinstance(small, cst.Import):
                for alias in small.names:
                    dotted = _dotted(alias.name)
                    if dotted:
                        found.add(dotted)
            elif isinstance(small, cst.ImportFrom):
                depth = len(small.relative)
                named = _dotted(small.module) if small.module is not None else ""
                if depth == 0:
                    if named:
                        found.add(named)
                    continue
                # One dot is "this package", two is its parent, and so on. A depth that
                # walks off the top of the project is a broken import; it names nothing
                # here, and an edge is not the place to report it.
                base = parts[: len(parts) - (depth - 1)]
                if len(base) != len(parts) - (depth - 1):
                    continue
                found.add(".".join([*base, named]) if named else ".".join(base))
    return found


# -- the walk --------------------------------------------------------------------------


def _files_of(package: Path, root: Path, skip: Path | None) -> tuple[str, ...]:
    """What the package is made of, project-relative and sorted.

    `skip` is the nesting directory, left out because its contents belong to the child
    nodes: a panel that listed them here would show the same file under two nodes and make
    a parent look like it contains its children's code as its own.
    """
    out: list[str] = []
    for item in package.rglob("*"):
        if not item.is_file():
            continue
        if skip is not None and skip in item.parents:
            continue
        if any(_ignored(part) for part in item.relative_to(package).parts[:-1]):
            continue
        if item.name.endswith(".pyc"):
            continue
        out.append(item.relative_to(root).as_posix())
    return tuple(sorted(out))


def _python_files(package: Path, skip: Path | None) -> list[Path]:
    """The `.py` files whose imports belong to this node."""
    out: list[Path] = []
    for item in package.rglob("*.py"):
        if skip is not None and skip in item.parents:
            continue
        if any(_ignored(part) for part in item.relative_to(package).parts[:-1]):
            continue
        out.append(item)
    return sorted(out)


def _node_for(
    package: Path,
    root: Path,
    node_id: str,
    kind: str,
    parent: str,
) -> Node:
    """One system node, complete or not. It is never omitted for being incomplete.

    A directory that looks like a system and is missing its export is the state a
    half-written package is in, and hiding it would leave a person looking at a canvas that
    disagrees with their file tree. It is shown, grey, with the reason said.
    """
    skip = package / _plural(kind)
    required = REQUIRED[kind]
    init = package / "__init__.py"

    missing: tuple[str, ...] = ()
    reason = ""

    if not init.is_file():
        missing = required
        reason = f"{node_id} has no __init__.py, so it exports nothing"
    else:
        names = _exports_of(init)
        if names is None:
            missing = required
            reason = f"{init.relative_to(root).as_posix()} could not be read"
        else:
            missing = tuple(name for name in required if name not in names)
            if missing:
                lacking = " or ".join(missing)
                reason = f"{init.relative_to(root).as_posix()} does not export {lacking}"

    return Node(
        id=node_id,
        name=package.name,
        kind=kind,
        path=package.relative_to(root).as_posix(),
        complete=not missing,
        exports=required,
        missing=missing,
        reason=reason,
        parent=parent,
        children=(),
        files=_files_of(package, root, skip if skip.is_dir() else None),
    )


def _children_of(package: Path, root: Path, node_id: str, kind: str) -> list[Node]:
    """The systems one level down, in the directory named for the plural of the kind.

    Candidacy is different here than at the root, and deliberately so. At the root the
    *name* is the signal -- `rag/` is in the table -- while in here the name is the author's
    choice, so the signal is being a package at all. A directory in `agents/` with no
    `__init__.py` is ordinary code, not a broken agent.

    Only one level. A third (`agents/researcher/agents/`) is never opened, which is why it
    produces no nodes and no error: there is nothing there to fail on.
    """
    nest = package / _plural(kind)
    if not nest.is_dir():
        return []

    out: list[Node] = []
    for child in sorted(nest.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or _ignored(child.name):
            continue
        if not (child / "__init__.py").is_file():
            continue
        out.append(_node_for(child, root, f"{node_id}.{child.name}", kind, node_id))
    return out


def _module_path(path: Path, root: Path) -> str:
    """The dotted name Python would import this file by, from the project root."""
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _file_nodes(root: Path) -> list[Node]:
    """The four root files. Never coloured, and never incomplete: they promise nothing."""
    return [
        Node(
            id=name,
            name=name,
            kind="file",
            path=name,
            complete=True,
            exports=(),
            missing=(),
            reason="",
            parent="",
            children=(),
            files=(),
        )
        for name in FILE_NODES
        if (root / name).is_file()
    ]


def _mcp_edges(root: Path, nodes: dict[str, Node]) -> list[Edge]:
    """One edge per configured MCP server, from the agent to the `mcp.json` node.

    The servers are not nodes. They are somebody else's process, reached over a protocol,
    and the project's fact about them is the file that configures them -- so the file node
    is where the edges land, one per server, each carrying its name.

    An unreadable or surprising `mcp.json` produces no edges rather than an error. It is a
    file a person edits by hand; a graph that refused to draw because of a trailing comma
    would be a graph that stops working while somebody is typing.
    """
    if "agent" not in nodes or "mcp.json" not in nodes:
        return []
    try:
        loaded = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    if not isinstance(servers, dict):
        return []
    return [
        Edge(
            id=f"agent->mcp.json:{name}",
            source="agent",
            target="mcp.json",
            kind="mcp",
            label=name,
        )
        for name in sorted(servers)
        if isinstance(name, str)
    ]


def _import_edges(root: Path, systems: list[Node], packages: dict[str, Path]) -> list[Edge]:
    """Edges between system packages, read from the import statements between them.

    The mapping is by **longest module prefix**, which is what makes a nested node work
    without a second rule: `agent.agents.writer.tools` matches the node `agent.writer` if
    that package is one, and falls back to `agent` if it is not. Direction follows the
    import, as the plan states -- the importer depends on the imported.
    """
    # Module path -> node id. A nested node's module path (`agent.agents.researcher`) is not
    # its id (`agent.researcher`), so the two are kept apart rather than reconstructed.
    by_module = {_module_path(packages[node.id], root): node.id for node in systems}

    def owner(module: str) -> str:
        parts = module.split(".")
        for cut in range(len(parts), 0, -1):
            found = by_module.get(".".join(parts[:cut]))
            if found is not None:
                return found
        return ""

    seen: set[tuple[str, str]] = set()
    for node in systems:
        package = packages[node.id]
        skip = package / _plural(node.kind)
        for file in _python_files(package, skip if skip.is_dir() else None):
            for module in _imports_of(file, _module_path(file.parent, root)):
                target = owner(module)
                # A self-import is a package's own internals -- `agent/__init__.py` reading
                # `agent.tools` -- and an edge from a node to itself states nothing.
                if target and target != node.id:
                    seen.add((node.id, target))

    return [
        Edge(id=f"{source}->{target}", source=source, target=target, kind="import", label="")
        for source, target in sorted(seen)
    ]


def read_graph(project: Path | str) -> Graph:
    """The project as a graph. Reads only; imports nothing; runs nothing.

    Colour is deliberately absent. A node's verdict is earned by a run (I-3) and there is no
    run here -- this answers what exists and what depends on what, and Observe answers
    whether any of it works.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return Graph(False, f"there is no project at {root}", str(root), (), ())

    systems: list[Node] = []
    packages: dict[str, Path] = {}

    for kind in sorted(REQUIRED):
        directory = root / kind
        if not directory.is_dir():
            continue

        children = _children_of(directory, root, kind, kind)
        parent = _node_for(directory, root, kind, kind, "")
        # Frozen, so the children are attached by rebuilding rather than by mutating: a node
        # that could be edited after it was read is a node two callers could disagree about.
        systems.append(replace(parent, children=tuple(child.id for child in children)))
        packages[kind] = directory
        for child in children:
            systems.append(child)
            packages[child.id] = root / child.path

    nodes = [*systems, *_file_nodes(root)]
    by_id = {node.id: node for node in nodes}
    edges = [*_import_edges(root, systems, packages), *_mcp_edges(root, by_id)]

    return Graph(
        ok=True,
        detail=f"{len(systems)} system(s), {len(nodes) - len(systems)} file(s)",
        root=str(root),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
