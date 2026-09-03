"""The routes an `api/` package declares, and where each one sends the request.

## Why this is a list and not a graph

`api -> rag` says nothing. `POST /documents -> worker` and `GET /documents/{id} -> postgres`
say the whole story: uploads are queued and reads go straight to storage. That is the value
of this phase, and the danger in it -- **forty routes must not become forty nodes.** A route
is contents of the api node, read when somebody opens its panel, and there is nothing here
that adds a node or an edge to the graph.

It is also why this is a module beside the graph rather than a field in it. A route list and
a graph answer different questions and go stale at different moments, exactly as a verdict
set does: the graph is what packages exist, and this is what one of them serves. A caller
that never opens the panel never pays for reading five route modules.

## What is read, and what is refused

A route is a decorator that **calls a method named for an HTTP verb with a path literal**:
`@app.post("/documents")`, `@router.get("/documents/{id}")`, and Litestar's bare `@get("/x")`.
The path has to start with `/`, which is what keeps `@cache.get("key")` from being read as a
route. Nothing here imports a web framework, checks a version or branches on a framework
name; a project on something this does not recognise gets an **empty list and no error**,
and renders exactly as it did before. Degrade, never error.

The arrow is the handler's downstream target, and it is read the same way an edge is: the
names the body **calls**, resolved through the file's own imports. A call to something taken
from another system package points at that system; a call to something taken from
`repositories/` points at `postgres`, which is the storage boundary this plan names. Several
targets are listed; one that resolves to nothing is `?`.

**`?` is a real answer here and it is never guessed away.** An honest unknown beats a wrong
arrow: a person can read the handler, but they cannot un-learn a target the panel asserted.
A handler that calls nothing at all is a third state again -- it has no downstream rather
than an unknown one -- and it says nothing rather than claiming uncertainty about a function
that plainly does none.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import libcst as cst

from framestack_core.database import DATABASE_NODE, STORAGE_PACKAGE
from framestack_core.parser import import_map, is_system, read_graph

__all__ = ["Route", "Routes", "read_routes"]

#: The decorator names that mean "this function answers a request".
#:
#: The verbs themselves, which is why no framework is named anywhere in this file. FastAPI
#: and Starlette write them as attributes of an app or a router, Litestar as bare imported
#: names, and both forms are the same fact about the same function.
METHODS: tuple[str, ...] = ("get", "post", "put", "patch", "delete", "websocket")

#: The storage boundary, and what it is called on the canvas -- both from `database.py`.
#:
#: Imported rather than restated: a route's arrow and a graph edge must not be able to
#: disagree about what storage is, and two copies of the word `repositories` is exactly how
#: they would. A handler whose only calls go there is a handler whose downstream is the
#: database; nothing here opens a connection or reads a URL to find out.
STORAGE_NODE = DATABASE_NODE


@dataclass(frozen=True)
class Route:
    """One request the service answers."""

    #: `GET`, `POST`, ... `WEBSOCKET`. The decorator's own verb, uppercased and nothing else.
    method: str
    #: The path literal, exactly as written. Placeholders included: `/documents/{id}`.
    path: str
    #: The decorated function's name. What to look for when opening the file.
    handler: str
    #: Project-relative, POSIX separators. Five route modules need to say which one this is.
    file: str
    #: Where the request goes next: node ids, or `postgres`. Empty when it goes nowhere.
    targets: tuple[str, ...]
    #: The handler called something and none of it resolved. Drawn as `?`, never as a guess.
    unsure: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "handler": self.handler,
            "file": self.file,
            "targets": list(self.targets),
            "unsure": self.unsure,
        }


@dataclass(frozen=True)
class Routes:
    """What one service serves. A refusal is a result, as everywhere else in the core."""

    ok: bool
    detail: str
    node: str
    routes: tuple[Route, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "routes": [route.as_dict() for route in self.routes],
        }


def _parse(path: Path) -> cst.Module | None:
    """The file as a tree, or nothing. Unreadable and unparseable are the same answer.

    Both mean "no route can be shown to be declared here", which is a statement about one
    file rather than an error about the read: a service with one broken module still serves
    the routes in the others.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return cst.parse_module(source)
    except cst.ParserSyntaxError:
        return None


def _dotted(node: cst.BaseExpression) -> str:
    """`a.b.c` as a string. Anything that is not a plain dotted name reads as empty."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr.value}" if head else ""
    return ""


def _verb_of(decorator: cst.Decorator) -> tuple[str, str] | None:
    """`(method, path)` if this decorator declares a route, or `None`.

    Two forms, because two of the three frameworks in the plan write it each way:
    `@router.post("/x")` is an attribute of an app or a router, and `@post("/x")` is a name
    imported from the framework. Both are a call to a verb with a path.

    The path must be a string literal that **starts with a slash**. That single test is what
    separates a route from `@cache.get("key")` and from every other method that happens to
    share a name with an HTTP verb -- and it costs nothing, because a route with a path that
    is not a literal is one nobody could have read anyway.
    """
    call = decorator.decorator
    if not isinstance(call, cst.Call):
        return None

    if isinstance(call.func, cst.Attribute):
        verb = call.func.attr.value
    elif isinstance(call.func, cst.Name):
        verb = call.func.value
    else:
        return None
    if verb not in METHODS:
        return None

    for argument in call.args:
        if argument.keyword is not None:
            continue
        if isinstance(argument.value, cst.SimpleString):
            text = argument.value.evaluated_value
            if isinstance(text, str) and text.startswith("/"):
                return verb.upper(), text
        # Only the first positional argument is the path. A second one that happened to be a
        # string would be a dependency or a name, and reading it would invent a route.
        break
    return None


class _Handlers(cst.CSTVisitor):
    """Every decorated function in one module, in source order.

    All of them, at any depth: Litestar puts routes on a controller class, and a method there
    is as much a route as a module-level function is. Order is the file's own, which is
    deterministic and is the order the author reads their file in -- sorting would shuffle
    somebody's own list under them.
    """

    def __init__(self) -> None:
        self.found: list[cst.FunctionDef] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        if node.decorators:
            self.found.append(node)
        # Into the body as well: a nested function can be decorated, and refusing to look
        # would be a rule about where people are allowed to write code.
        return True


def _head(node: cst.BaseExpression) -> str:
    """The leftmost plain name of whatever is being called.

    The head, because that is the only part a file's imports can resolve: `run(...)` is
    `run`, `agent.run(...)` is `agent`, and `db.execute(...)` is `db` -- which is a local
    variable, resolves to nothing, and is the honest reason a route can end up `?`.

    It descends through a subscript as well as an attribute, because `HANDLERS["reindex"](
    body)` is how a worker's table is called and the name that matters is still `HANDLERS`.
    Anything that is not rooted in a name -- a call on a literal, a lambda -- has no head and
    contributes nothing.
    """
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return _head(node.value)
    if isinstance(node, cst.Subscript):
        return _head(node.value)
    if isinstance(node, cst.Call):
        return _head(node.func)
    return ""


class _Calls(cst.CSTVisitor):
    """The head name of everything one function body calls, in source order."""

    def __init__(self) -> None:
        self.found: list[str] = []

    def visit_Call(self, node: cst.Call) -> bool:
        head = _head(node.func)
        if head and head not in self.found:
            self.found.append(head)
        return True


def _targets_of(
    function: cst.FunctionDef,
    imports: dict[str, str],
    owner: dict[str, str],
) -> tuple[tuple[str, ...], bool]:
    """Where this handler sends the request, and whether it called something unattributable.

    `owner` maps a module path to the node that owns it, longest prefix first, so a call into
    `rag.store` still points at `rag`. What it deliberately cannot do is attribute a call to
    a name the file never imported: that is somebody's local helper or a framework's, and
    claiming a target for it is the wrong arrow this whole design exists to avoid.
    """
    seeker = _Calls()
    function.body.visit(seeker)
    if not seeker.found:
        # It calls nothing. That is no downstream rather than an unknown one, and the two
        # must not be collapsed -- `?` about a function that plainly does none would be this
        # panel manufacturing doubt.
        return (), False

    hit: list[str] = []
    for head in seeker.found:
        module = imports.get(head)
        if module is None:
            continue
        parts = module.split(".")
        for cut in range(len(parts), 0, -1):
            found = owner.get(".".join(parts[:cut]))
            if found is not None:
                if found not in hit:
                    hit.append(found)
                break

    return tuple(sorted(hit)), not hit


def _python_files(package: Path) -> list[Path]:
    """The service's own modules. Sorted, so three reads answer the same (I-4)."""
    out: list[Path] = []
    for item in package.rglob("*.py"):
        parts = item.relative_to(package).parts[:-1]
        # A nested service's routes belong to that node, and a dotted or underscored
        # directory is not a package anybody is serving from.
        if any(part.startswith((".", "_")) or part == "apis" for part in parts):
            continue
        out.append(item)
    return sorted(out)


def read_routes(project: Path | str, node: str) -> Routes:
    """What one service serves. Reads only; imports nothing; runs nothing.

    Only an `api/` package is asked. Every other kind is refused rather than answered with an
    empty list, because "this node has no routes" and "this node cannot have routes" are
    different sentences and a caller told the first one would go looking for the reason.
    """
    root = Path(project).expanduser()
    graph = read_graph(root)
    if not graph.ok:
        return Routes(False, graph.detail, node, ())

    found = [item for item in graph.nodes if item.id == node]
    if not found:
        return Routes(False, f"there is no node {node!r} in this project", node, ())
    system = found[0]
    if not is_system(system) or system.kind != "api":
        return Routes(
            False,
            f"{node} is not a service; only an api/ package declares routes",
            node,
            (),
        )

    # Module path -> node id, the same mapping the edge builder uses, so a handler's calls
    # are attributed by exactly the rule an import edge is. Built from the graph rather than
    # from the directory tree: recognition happens in one place and this is not it.
    owner = {item.path.replace("/", "."): item.id for item in graph.nodes if is_system(item)}
    owner[STORAGE_PACKAGE] = STORAGE_NODE

    package = root / system.path
    routes: list[Route] = []
    for file in _python_files(package):
        module = _parse(file)
        if module is None:
            continue
        imports = import_map(file, ".".join(file.relative_to(root).with_suffix("").parts[:-1]))
        seeker = _Handlers()
        module.visit(seeker)
        for function in seeker.found:
            for decorator in function.decorators:
                verb = _verb_of(decorator)
                if verb is None:
                    continue
                targets, unsure = _targets_of(function, imports, owner)
                routes.append(
                    Route(
                        method=verb[0],
                        path=verb[1],
                        handler=function.name.value,
                        file=file.relative_to(root).as_posix(),
                        targets=targets,
                        unsure=unsure,
                    )
                )

    return Routes(
        ok=True,
        detail=f"{len(routes)} route(s)",
        node=node,
        routes=tuple(routes),
    )
