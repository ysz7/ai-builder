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

from framestack_core.database import DATABASE_NODE, STORAGE_PACKAGE, Database, read_database

__all__ = [
    "FILE_NODES",
    "REQUIRED",
    "Edge",
    "Graph",
    "Node",
    "import_map",
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

#: A server `mcp.json` configures, as a node. **Not a fifth kind**: it has no required
#: export, nothing to satisfy and nothing that could ever prove it, which makes it the same
#: sort of thing a file node is rather than the same sort of thing an agent is.
#:
#: Phase 1 said the servers were not nodes and this reverses that, deliberately. The reason
#: it is allowed: `mcp.json` is a file in the project and this parser already read it to draw
#: the edges. The node is derived from the code, not invented beside it -- which is the only
#: test that matters here.
MCP_KIND = "mcp"

#: The one directory below a package that produces nodes, and what those nodes are called.
#:
#: **The single exception to "no granularity below a package", and it is named rather than
#: derived.** A module in `agent/tools/` is a node because the directory says so -- no
#: decorator, no registration, nothing to satisfy. That is what keeps it from being the
#: annotation layer coming back: the signal is where the file is, which a person can see in
#: their own file tree, and there is exactly one such directory.
#:
#: Read on the top-level `agent/` only. A sub-agent's tools would be a second level of
#: nesting, which this plan puts out of scope, and one level is the rule everywhere else.
TOOLS_DIR = "tools"
TOOL_KIND = "tool"

#: The second class of node in the taxonomy: something the project's code **talks to**.
#:
#: A dependency is not a package and never carries a verdict -- no test executes a Postgres,
#: so no run can prove one. What it carries is a status, which is a different claim from a
#: different mechanism and arrives with the thing that can actually ask. Until then it has
#: neither, which is the honest state and not a placeholder for one.
DEPENDENCY_KIND = "dependency"


def is_system(node: Node) -> bool:
    """Whether this node is a package the convention recognises.

    **Ask this, never `kind != "file"`.** That test meant "is it a package" only for as long
    as `file` was the sole thing that was not one, and it silently stopped meaning that the
    moment MCP servers became nodes: the first symptom would have been Observe trying to
    measure coverage of `mcp.json` and every server turning grey for not being reached by a
    test. A question asked by name cannot rot that way.
    """
    return node.kind in REQUIRED


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
    #: The entry points an edge may land on, in the order the package states them.
    #:
    #: **What the package actually binds, never what it ought to.** A `rag/` that exports
    #: only `search` has one port, not two with one drawn as broken: the missing export is
    #: already said in `missing` and `reason`, and a port for a name nothing binds would be
    #: an attachment point for an import that cannot be written.
    ports: tuple[str, ...]

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
            "ports": list(self.ports),
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
    #: Which of the target's ports this lands on, or `""` for the package itself.
    #:
    #: `from rag import search` is a fact about `search`, and drawing it at the same point as
    #: `import rag` throws that away -- `api -> rag` says nothing, while `worker -> rag.index`
    #: and `agent -> rag.search` say that uploads index and questions retrieve. Set only when
    #: the imported module **is** the target package and the name is one of its ports: a name
    #: taken out of `rag.store` is internal, and the edge is about the package.
    port: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "label": self.label,
            "port": self.port,
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


def _handler_keys(init: Path) -> tuple[str, ...]:
    """The names a worker answers to: the literal keys of its `HANDLERS` dict.

    Read syntactically, like everything else here, so the keys are the ones **written in the
    file** -- a dict built by a call, a comprehension or an update in another module has no
    keys this parser can see, and it reports none rather than a plausible few. That is the
    same refusal `settings.write` makes about a default built by a call, and for the same
    reason: a guess that looks right is worse than an absence somebody can act on.

    File order, not sorted. It is the order the author wrote and it is stable across reads,
    which is all I-4 asks; sorting would reorder a person's own list under them.
    """
    module = _parse(init)
    if module is None:
        return ()

    found: list[str] = []
    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            named = False
            value: cst.BaseExpression | None = None
            if isinstance(small, cst.Assign):
                named = any(
                    isinstance(target.target, cst.Name) and target.target.value == "HANDLERS"
                    for target in small.targets
                )
                value = small.value
            elif isinstance(small, cst.AnnAssign):
                # `HANDLERS: dict[str, Callable]` with no value binds nothing, which is why
                # the annotated form is read through the same test the plain one is.
                named = isinstance(small.target, cst.Name) and small.target.value == "HANDLERS"
                value = small.value
            else:
                continue
            if not named or not isinstance(value, cst.Dict):
                continue
            for element in value.elements:
                if not isinstance(element, cst.DictElement):
                    continue
                key = element.key
                if isinstance(key, cst.SimpleString):
                    text = key.evaluated_value
                    if isinstance(text, str) and text and text not in found:
                        found.append(text)
    return tuple(found)


def _ports_of(kind: str, init: Path, names: frozenset[str]) -> tuple[str, ...]:
    """The entry points of one package: where an edge may land, other than on the package.

    A port is a name the convention already requires, so this adds no syntax and no second
    mechanism -- it reads the same `__init__.py` the node itself was read from.

    Two kinds are not the plain case:

    `worker/` exports one name, `HANDLERS`, and that name is a *table* of entry points. Its
    ports are the keys, because `worker.reindex` is the thing another package enqueues and
    `HANDLERS` is only where the list of them is kept.

    `api/` has none. Its export is an ASGI application: it is served, not called by anything
    in the project, so there is no import that could land on a port. What it offers is its
    routes, and those are listed in the node's panel rather than drawn on the canvas -- forty
    routes must not become forty attachment points.
    """
    if kind == "worker":
        # Only when the name is actually bound. An incomplete worker offers nothing to land
        # on, and reading keys out of a dict the package does not export would invent one.
        return _handler_keys(init) if "HANDLERS" in names else ()
    if kind == "api":
        return ()
    return tuple(name for name in REQUIRED[kind] if name in names)


def _resolve(depth: int, parts: list[str], named: str) -> str:
    """A relative import as the absolute module it names, or `""` if it walks off the top.

    One dot is "this package", two is its parent, and so on -- the same arithmetic Python
    does. It lives here, in one function, because two readers need it: the edge builder and
    `import_map`, which `routes.py` uses to say where a handler's calls come from. Two copies
    of this would be two answers about the same import the day one of them was fixed.
    """
    base = parts[: len(parts) - (depth - 1)]
    if len(base) != len(parts) - (depth - 1):
        return ""
    return ".".join([*base, named]) if named else ".".join(base)


def import_map(path: Path, package: str) -> dict[str, str]:
    """Every name this file binds by importing it, and the module it came from.

    The *local* name is the key -- `from rag import search as look` maps `look` to `rag` --
    because the caller of this is reading a function body, where the local name is the only
    one written down. `_imports_of` answers the other question, what was taken out of which
    package, and the two are kept apart rather than folded into one shape that answers
    neither well.

    Module level only, like every other read here: a name bound inside an `if` or a `try` is
    a name whose existence only running the code can settle.
    """
    module = _parse(path)
    if module is None:
        return {}

    found: dict[str, str] = {}
    parts = package.split(".") if package else []

    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            if isinstance(small, cst.Import):
                for alias in small.names:
                    dotted = _dotted(alias.name)
                    if not dotted:
                        continue
                    if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                        found[alias.asname.name.value] = dotted
                    else:
                        # `import a.b.c` binds `a`, and `a` is the module a call would start
                        # with. The rest of the path is written at the call site.
                        found[dotted.split(".")[0]] = dotted.split(".")[0]
            elif isinstance(small, cst.ImportFrom):
                if isinstance(small.names, cst.ImportStar):
                    continue
                depth = len(small.relative)
                named = _dotted(small.module) if small.module is not None else ""
                where = named if depth == 0 else _resolve(depth, parts, named)
                if not where:
                    continue
                for alias in small.names:
                    if not isinstance(alias.name, cst.Name):
                        continue
                    local = alias.name.value
                    if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                        local = alias.asname.name.value
                    found[local] = where
    return found


def _callables_in(module: cst.Module) -> tuple[str, ...]:
    """The public functions a module defines, at module level, in source order.

    Functions, not every callable: a class is callable too, and counting one would make a
    module with a helper dataclass look like a tool that does two things. A leading
    underscore is the author saying "not this one", which is the only signal here and needs
    no convention of ours.
    """
    found: list[str] = []
    for statement in module.body:
        if isinstance(statement, cst.FunctionDef) and not statement.name.value.startswith("_"):
            found.append(statement.name.value)
    return tuple(found)


def _tools_of(package: Path, root: Path, node_id: str) -> list[Node]:
    """The tool modules one agent contains: `agent/tools/*.py`, one node each.

    A module is a node when it defines at least one public function. One that defines none
    is a helper -- constants, a shared client -- and drawing a node for it would put a box on
    the canvas for a file nobody calls.

    With exactly one function the node is named after **it**; with several it is named after
    the file and lists them. Either way the id is the file's, because the file is the thing on
    disk and a rename of the function must not move a node's identity out from under a
    person's saved layout.

    The callables become the node's **ports**, which is not a special case: a port is an entry
    point an edge may land on, and `from agent.tools.send_email import send_email` lands on
    exactly that.
    """
    nest = package / TOOLS_DIR
    if not nest.is_dir():
        return []

    out: list[Node] = []
    for item in sorted(nest.iterdir(), key=lambda one: one.name):
        if not item.is_file() or item.suffix != ".py" or _ignored(item.name):
            continue
        module = _parse(item)
        if module is None:
            continue
        callables = _callables_in(module)
        if not callables:
            continue
        stem = item.stem
        out.append(
            Node(
                id=f"{node_id}.{TOOLS_DIR}.{stem}",
                name=callables[0] if len(callables) == 1 else stem,
                kind=TOOL_KIND,
                path=item.relative_to(root).as_posix(),
                # There is no contract for a tool to fail. It is a module in a directory,
                # and being in that directory is the whole of what makes it a node.
                complete=True,
                exports=(),
                missing=(),
                reason="",
                parent=node_id,
                children=(),
                # Its path *is* the file. Listing it again under "Files" would say the same
                # thing twice, and the agent already lists it as code it is answerable for.
                files=(),
                ports=callables,
            )
        )
    return out


def _imports_of(path: Path, package: str) -> set[tuple[str, str]]:
    """What one file imports: `(module, name)`, relatives resolved against `package`.

    Relative imports are resolved here rather than left alone because an edge is a fact
    about two packages, and `from ..rag import search` states it exactly as plainly as the
    absolute form does. Resolving it is arithmetic on the containing package's parts, which
    is the same arithmetic Python does.

    The **name** is what makes an edge land on a port, and it is the name in the exporting
    package rather than the local one: `from rag import search as look_up` is still a fact
    about `rag.search`, and the alias is this file's private business. `import rag` names
    nothing, so it carries `""` and lands on the package -- which is exactly what it says.
    """
    module = _parse(path)
    if module is None:
        return set()

    found: set[tuple[str, str]] = set()
    parts = package.split(".") if package else []

    def take(module_path: str, names: Any) -> None:
        """One `from X import a, b` as one pair per name. A star import names nothing."""
        if not module_path:
            return
        if isinstance(names, cst.ImportStar):
            found.add((module_path, ""))
            return
        for alias in names:
            # The exported name, not `asname`: an alias renames it here, not there.
            symbol = alias.name.value if isinstance(alias.name, cst.Name) else ""
            found.add((module_path, symbol))

    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            if isinstance(small, cst.Import):
                for alias in small.names:
                    dotted = _dotted(alias.name)
                    if dotted:
                        found.add((dotted, ""))
            elif isinstance(small, cst.ImportFrom):
                depth = len(small.relative)
                named = _dotted(small.module) if small.module is not None else ""
                if depth == 0:
                    take(named, small.names)
                    continue
                # A depth that walks off the top of the project is a broken import; it
                # names nothing here, and an edge is not the place to report it.
                take(_resolve(depth, parts, named), small.names)
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
    bound: frozenset[str] = frozenset()

    if not init.is_file():
        missing = required
        reason = f"{node_id} has no __init__.py, so it exports nothing"
    else:
        names = _exports_of(init)
        if names is None:
            missing = required
            reason = f"{init.relative_to(root).as_posix()} could not be read"
        else:
            bound = names
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
        ports=_ports_of(kind, init, bound),
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
            # A file promises nothing, so there is nothing on it for an edge to land on.
            ports=(),
        )
        for name in FILE_NODES
        if (root / name).is_file()
    ]


def _servers_in(root: Path) -> list[str]:
    """The names `mcp.json` configures, in order.

    An unreadable or surprising `mcp.json` produces **nothing rather than an error**. It is a
    file a person edits by hand, and a graph that refused to draw because of a trailing comma
    would be a graph that stops working while somebody is typing.

    Sorted, because I-4 asks the same question three times and expects the same answer. The
    file's own key order is a JSON implementation detail, not a fact about the project.
    """
    if not (root / "mcp.json").is_file():
        return []
    try:
        loaded = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    if not isinstance(servers, dict):
        return []
    return sorted(name for name in servers if isinstance(name, str) and name)


def _database_node(database: Database) -> list[Node]:
    """The project's storage, as one node. **One per backend, never one per table.**

    Twelve tables are twelve rows in a panel; twelve boxes would be a hairball, and every
    edge into them would have to choose a table to land on. What the graph answers is "what
    does this project talk to", and for a database that answer is one thing.

    It is in the graph rather than beside it because the facts come from the project's own
    Python, which the parser already reads -- the same test that puts an MCP server in the
    graph and leaves a compose service outside it. What it does *not* carry is the reading:
    the tables and the connection string are asked for separately, because they go stale at
    a different moment and cost a walk of the project to produce.
    """
    if not database.present:
        return []
    return [
        Node(
            id=DATABASE_NODE,
            # `postgres + pgvector` where a model declares a vector column. The label is a
            # reading of the schema, not a second node and not a kind.
            name=database.label,
            kind=DEPENDENCY_KIND,
            # No file declares it. It is what the project's code talks to, stated in several
            # places at once, and naming one of them would make that one look authoritative.
            path="",
            complete=True,
            exports=(),
            missing=(),
            reason="",
            parent="",
            children=(),
            files=(),
            # Nothing to land on. An edge to a table would be an edge to a row in a panel.
            ports=(),
        )
    ]


def _mcp_nodes(root: Path) -> list[Node]:
    """One node per configured server. Never coloured, and never incomplete.

    It promises nothing, so there is nothing for it to fail to promise: no required export,
    no contract, no verdict. `path` is the file that declares it, which is the only thing
    about it that is in the project at all -- the server itself is somebody else's program,
    and nothing here starts it to find out what it offers.

    The id cannot collide with a system's: `mcp` is not one of `REQUIRED`, so no package is
    ever addressed as `mcp.something`.
    """
    return [
        Node(
            id=f"{MCP_KIND}.{name}",
            name=name,
            kind=MCP_KIND,
            path="mcp.json",
            complete=True,
            exports=(),
            missing=(),
            reason="",
            parent="",
            children=(),
            files=(),
            # Somebody else's program. What it offers is a question only an MCP client can
            # ask it, and asking would mean becoming one.
            ports=(),
        )
        for name in _servers_in(root)
    ]


def _mcp_edges(nodes: dict[str, Node]) -> list[Edge]:
    """One edge per configured server, from the agent to the server it can reach.

    It used to land on the `mcp.json` file node, because the servers were not nodes. They are
    now, so the edge lands where the relation actually points: the agent reaches *that
    server*, and the file is where that fact is written down rather than the thing being
    reached.
    """
    if "agent" not in nodes:
        return []
    return [
        Edge(
            id=f"agent->{node.id}",
            source="agent",
            target=node.id,
            kind=MCP_KIND,
            label=node.name,
            port="",
        )
        for node in nodes.values()
        if node.kind == MCP_KIND
    ]


class _Strings(cst.CSTVisitor):
    """Every string literal in one subtree."""

    def __init__(self) -> None:
        self.found: set[str] = set()

    def visit_SimpleString(self, node: cst.SimpleString) -> bool:
        text = node.evaluated_value
        if isinstance(text, str):
            self.found.add(text)
        return False


class _Used(cst.CSTVisitor):
    """String literals a module **uses**: passed to a call, or assigned to a name.

    Prose is excluded by construction rather than by a filter -- a docstring is a bare
    expression statement and is never an argument or a right-hand side, so it is never seen
    here. That matters: a tool whose docstring mentions Gmail must not draw an edge to a
    server, and a rule that had to recognise a docstring would be a rule with an exception.
    """

    def __init__(self) -> None:
        self.found: set[str] = set()

    def _take(self, node: cst.CSTNode) -> None:
        seeker = _Strings()
        node.visit(seeker)
        self.found |= seeker.found

    def visit_Call(self, node: cst.Call) -> bool:
        for argument in node.args:
            self._take(argument.value)
        return True

    def visit_Assign(self, node: cst.Assign) -> bool:
        self._take(node.value)
        return True

    def visit_AnnAssign(self, node: cst.AnnAssign) -> bool:
        if node.value is not None:
            self._take(node.value)
        return True

    def visit_Subscript(self, node: cst.Subscript) -> bool:
        # `HANDLERS["reindex"](payload)` is how a worker's table is called, and the key is
        # not an argument -- it is the index. An index is never prose either, so it belongs
        # here for the same reason the others do.
        for element in node.slice:
            self._take(element.slice)
        return True


def _named_in(path: Path) -> set[str]:
    """The string literals one file **uses**. Cached by nobody: each file is read once."""
    module = _parse(path)
    if module is None:
        return set()
    seeker = _Used()
    module.visit(seeker)
    return seeker.found


def _tool_server_edges(root: Path, tools: list[Node], servers: list[Node]) -> list[Edge]:
    """A tool to the MCP server it names, one edge per pair.

    **This is the one edge in the graph that is not an import**, because there is nothing to
    import: a server is somebody else's program reached over a protocol, and the only thing a
    module can do in Python is name it. So the relation read here is exactly that, and the
    claim is exactly that -- *this module names that server* -- never that it calls it or
    that the call succeeded. Nothing here starts a server or asks it anything.

    The set of names is closed: it is the keys of `mcp.json`, which the parser already read.
    A string only matches a server the project has actually configured, so this cannot invent
    a target, and where it is wrong it is wrong about a module that wrote a configured
    server's name into a call for some other reason.
    """
    by_name = {server.name: server.id for server in servers}
    if not by_name:
        return []

    out: list[Edge] = []
    for tool in tools:
        for name in sorted(_named_in(root / tool.path) & set(by_name)):
            out.append(
                Edge(
                    id=f"{tool.id}->{by_name[name]}",
                    source=tool.id,
                    target=by_name[name],
                    kind=MCP_KIND,
                    label=name,
                    port="",
                )
            )
    return out


def _storage_modules(database: Database) -> set[str]:
    """The module paths that mean "this is where the database is touched".

    The `repositories/` package, which is the storage boundary this plan names, and every
    module that actually declares a table. Both are read rather than configured: one is a
    directory the plan states, the other is a file with a `__tablename__` in it.
    """
    if not database.present:
        return set()
    found = {STORAGE_PACKAGE}
    for table in database.tables:
        parts = table.file.removesuffix(".py").split("/")
        if parts and parts[-1] == "__init__":
            parts.pop()
        if parts:
            found.add(".".join(parts))
    return found


def _import_edges(
    root: Path,
    systems: list[Node],
    packages: dict[str, Path],
    walk: dict[str, list[Path]],
    storage: set[str],
) -> list[Edge]:
    """Edges between system packages, read from the import statements between them.

    The mapping is by **longest module prefix**, which is what makes a nested node work
    without a second rule: `agent.agents.writer.tools` matches the node `agent.writer` if
    that package is one, and falls back to `agent` if it is not. Direction follows the
    import, as the plan states -- the importer depends on the imported.

    An edge lands on a **port** when the import names one: the module has to be the target
    package itself and the name has to be one of its ports. `from rag.store import add`
    resolves to `rag` by prefix and lands on the package, because `add` is inside the
    package rather than on its boundary -- crediting it to a port would invent an entry
    point the convention never promised.
    """
    # Module path -> node id. A nested node's module path (`agent.agents.researcher`) is not
    # its id (`agent.researcher`), so the two are kept apart rather than reconstructed.
    by_module = {_module_path(packages[node.id], root): node.id for node in systems}
    # And back the other way, to ask whether an import named the package itself or something
    # under it. Derived from the same dict so the two can never drift apart.
    module_of = {node_id: module for module, node_id in by_module.items()}
    ports_of = {node.id: frozenset(node.ports) for node in systems}
    parent_of = {node.id: node.parent for node in systems}
    kind_of = {node.id: node.kind for node in systems}
    #: The strings each file uses, read once per file and only where a worker is involved.
    named: dict[Path, set[str]] = {}

    def owner(module: str) -> str:
        parts = module.split(".")
        for cut in range(len(parts), 0, -1):
            found = by_module.get(".".join(parts[:cut]))
            if found is not None:
                return found
        return ""

    seen: set[tuple[str, str, str]] = set()
    for node in systems:
        for file in walk[node.id]:
            for module, symbol in _imports_of(file, _module_path(file.parent, root)):
                # Storage first: a module that declares a table belongs to the database, not
                # to whatever package happens to be its longest prefix. `repositories/` is
                # nobody's node, and a model inside a system would otherwise be read as that
                # system importing itself.
                if any(module == where or module.startswith(f"{where}.") for where in storage):
                    seen.add((node.id, DATABASE_NODE, ""))
                    continue
                target = owner(module)
                # A self-import is a package's own internals -- `agent/__init__.py` reading
                # `agent.tools` -- and an edge from a node to itself states nothing.
                if not target or target == node.id:
                    continue
                # Nor does one between a node and the node that contains it. A parent
                # importing its own tool, or its own sub-agent, is the same statement the
                # frame around them already makes, and an arrow repeating it would put a
                # line on the canvas beside every child there is.
                if target == parent_of.get(node.id) or parent_of.get(target) == node.id:
                    continue
                on_port = module == module_of.get(target) and symbol in ports_of[target]
                if on_port:
                    seen.add((node.id, target, symbol))
                    continue

                # A worker's ports are the **keys of its `HANDLERS` dict**, which are strings
                # in the source. No import can name one, so the only way a caller can is by
                # writing the string -- `enqueue("reindex", ...)` -- and that is what is read
                # here. The edge still exists because of the import; the string only decides
                # which port it lands on, which is the whole job of a port.
                #
                # It is not done for any other kind, and the reason is the asymmetry: a rag's
                # ports are importable names, so `from rag import search` already lands on
                # one, and a bare `"search"` somewhere in a file would be a coincidence read
                # as a fact.
                if kind_of.get(target) == "worker" and ports_of[target]:
                    if file not in named:
                        named[file] = _named_in(file)
                    hit = sorted(named[file] & ports_of[target])
                    if hit:
                        for one in hit:
                            seen.add((node.id, target, one))
                        continue

                seen.add((node.id, target, ""))

    return [
        Edge(
            # The port is in the id because two edges between the same pair are two facts:
            # `worker -> rag.index` and `worker -> rag.search` are different imports and must
            # not collapse into one. `#` rather than a dot, so the id cannot be confused with
            # a nested node's -- `agent->rag.search` would also be an edge to a child of
            # `rag` called `search`, and ids that can mean two things are ids that will.
            id=f"{source}->{target}#{port}" if port else f"{source}->{target}",
            source=source,
            target=target,
            kind="import",
            label="",
            port=port,
        )
        for source, target, port in sorted(seen)
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
    tools: list[Node] = []
    packages: dict[str, Path] = {}
    #: Whose imports each node answers for. Kept apart from `files` on purpose: a tool's
    #: **imports** belong to the tool, and its **coverage** belongs to the agent that
    #: contains it. Those are different questions -- an edge says who depends on what, a
    #: verdict says whose code a test ran -- and the tool's lines are inside the agent
    #: package, so giving them two owners would let one node be green and the other grey
    #: for the same run.
    walk: dict[str, list[Path]] = {}

    for kind in sorted(REQUIRED):
        directory = root / kind
        if not directory.is_dir():
            continue

        children = _children_of(directory, root, kind, kind)
        # Only the top-level agent. A sub-agent's tools would be a second level of nesting,
        # which is out of scope, and one level is the rule everywhere else here.
        own_tools = _tools_of(directory, root, kind) if kind == "agent" else []
        parent = _node_for(directory, root, kind, kind, "")
        # Frozen, so the children are attached by rebuilding rather than by mutating: a node
        # that could be edited after it was read is a node two callers could disagree about.
        systems.append(
            replace(
                parent,
                children=tuple(child.id for child in [*children, *own_tools]),
            )
        )
        packages[kind] = directory

        nest = directory / _plural(kind)
        taken = {root / tool.path for tool in own_tools}
        walk[kind] = [
            file
            for file in _python_files(directory, nest if nest.is_dir() else None)
            if file not in taken
        ]

        for child in children:
            systems.append(child)
            packages[child.id] = root / child.path
            nested = (root / child.path) / _plural(child.kind)
            walk[child.id] = _python_files(root / child.path, nested if nested.is_dir() else None)

        for tool in own_tools:
            tools.append(tool)
            packages[tool.id] = root / tool.path
            walk[tool.id] = [root / tool.path]

    servers = _mcp_nodes(root)
    files = _file_nodes(root)
    database = read_database(root)
    stores = _database_node(database)
    coded = [*systems, *tools]
    nodes = [*coded, *files, *servers, *stores]
    by_id = {node.id: node for node in nodes}
    edges = [
        *_import_edges(root, coded, packages, walk, _storage_modules(database)),
        *_mcp_edges(by_id),
        *_tool_server_edges(root, tools, servers),
    ]

    return Graph(
        ok=True,
        detail=(
            f"{len(systems)} system(s), {len(tools)} tool(s), "
            f"{len(files)} file(s), {len(servers)} server(s), "
            f"{len(stores)} dependency(s)"
        ),
        root=str(root),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
