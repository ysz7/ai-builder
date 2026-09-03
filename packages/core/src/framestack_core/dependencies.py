"""What the project's code talks to, and how each one is recognised.

## The second class of node, and why it exists

A system is your code and carries a **verdict** — a test entered it and passed. A dependency
is something outside the project and carries a **status** — a connection reached it, or did
not. The two are different claims from different mechanisms, they go stale at different
moments, and **they never share a colour scale**. A dependency is never green: nothing in a
test run executes a Postgres, and a green Postgres would be the flow-document defect arriving
by another door.

## There is no manual add

Every node here exists because **the code references it**: an import of a client, a literal in
a settings default, a file at the project root. Pressing `+` on a dependency in the palette
does not draw a box — it sends a task to the agent to write the code that uses the thing, and
the node then appears because the code now names it. Same click for the person, honest
mechanism underneath, and it is invariant 7 in practice: everything on the canvas is derived.

## What is read

An **import root** and a **string literal**, nothing else. `import redis` is a fact in a file;
so is `"claude-sonnet-4-6"` sitting in a settings default. Neither is a connection, neither
resolves an environment variable, and nothing here learns a library: an import is matched by
its top-level name, which is a token in the source, not a package this codebase depends on.

A model name is matched by **prefix**, and the prefixes are the vendors' own naming — a string
that starts with `claude-` names an Anthropic model in the same way a string that starts with
`postgresql://` names a Postgres. Where a project names a model it has not configured, the
node says the credential is absent rather than guessing that it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import libcst as cst

from framestack_core.database import DATABASE_NODE, Database, read_database

__all__ = [
    "CREDENTIALS",
    "Dependency",
    "read_dependencies",
]

#: Directories the walk never enters, shared with the database reader's reasoning: a dot or
#: an underscore says "not somebody's package", and the rest are other ecosystems' caches.
SKIP = frozenset({"node_modules", "venv", "env", "site-packages", "dist", "build"})


@dataclass(frozen=True)
class Sign:
    """How one dependency is recognised, and what to call it.

    A table rather than a function per kind, because the recognitions are the same shape --
    an import root or a string prefix -- and a function each would invite the fifth one to be
    a special case. The moment a dependency needs its own logic to be *found*, it is a
    different sort of thing and belongs in its own reader, as the database does.
    """

    node: str
    #: Top-level import names that mean this dependency is used. `import redis` is the fact.
    imports: tuple[str, ...]
    #: String-literal prefixes that mean the same. A model name, a base URL, a port.
    literals: tuple[str, ...]
    #: The env-var names that would configure it, and whose **presence** is its status.
    credentials: tuple[str, ...]
    #: Whether reaching it costs money. A paid API is never called to find out if it is up.
    paid: bool


#: Every dependency this build can recognise, in the order the canvas draws them.
#:
#: `postgres` is not here: it has its own reader, because a database is recognised by
#: something an import root cannot express -- a `__tablename__`, a migration, a connection
#: string -- and it carries a table list nothing else has.
#:
#: `docker` is not here either: it is recognised by a file at the project root rather than by
#: anything inside the Python, and the file nodes already say where it comes from.
SIGNS: tuple[Sign, ...] = (
    Sign(
        node="redis",
        imports=("redis", "aioredis"),
        literals=("redis://", "rediss://"),
        credentials=("REDIS_URL",),
        paid=False,
    ),
    Sign(
        node="ollama",
        imports=("ollama",),
        # Ollama's own default port. A literal in a settings default is a fact about the
        # file; resolving a host would be a connection, which recognition never makes.
        literals=(":11434",),
        credentials=("OLLAMA_HOST",),
        paid=False,
    ),
    Sign(
        node="anthropic",
        imports=("anthropic",),
        literals=("claude-",),
        credentials=("ANTHROPIC_API_KEY",),
        paid=True,
    ),
    Sign(
        node="openai",
        imports=("openai",),
        literals=("gpt-", "o1-", "o3-"),
        credentials=("OPENAI_API_KEY",),
        paid=True,
    ),
)

#: The node ids that are checked by looking for a credential rather than by connecting.
#:
#: **A paid API is never called to find out whether it is up.** A status that costs money is
#: a status nobody can afford to poll, and the useful answer is the one that is free: whether
#: this project has been given a key at all.
CREDENTIALS: frozenset[str] = frozenset(sign.node for sign in SIGNS if sign.paid)

#: The two files that mean the project asks for containers around it.
DOCKER_FILES: tuple[str, ...] = ("compose.yaml", "Dockerfile")
DOCKER_NODE = "docker"


@dataclass(frozen=True)
class Dependency:
    """One thing outside the project that the project's code names."""

    id: str
    #: What to call it on the canvas. `postgres + pgvector` where the schema says so.
    name: str
    #: Which node ids reference it, so an edge can be drawn from each. Sorted.
    used_by: tuple[str, ...]
    #: True where its status is a credential rather than a connection.
    paid: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "used_by": list(self.used_by),
            "paid": self.paid,
        }


def _parse(path: Path) -> cst.Module | None:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return cst.parse_module(source)
    except cst.ParserSyntaxError:
        return None


class _Signals(cst.CSTVisitor):
    """The import roots and the used string literals of one module.

    Module-level imports only, and strings that are **used** rather than written as prose --
    an argument, a right-hand side, an index. A docstring is a bare expression statement and
    is never any of those, so a tool documented in English cannot name a dependency into
    existence.
    """

    def __init__(self) -> None:
        self.roots: set[str] = set()
        self.strings: set[str] = set()

    def _root(self, node: cst.BaseExpression | None) -> None:
        """The leftmost name of a dotted module path. `import a.b.c` names `a`."""
        at: cst.BaseExpression | None = node
        while isinstance(at, cst.Attribute):
            at = at.value
        if isinstance(at, cst.Name):
            self.roots.add(at.value)

    def visit_Import(self, node: cst.Import) -> bool:
        for alias in node.names:
            self._root(alias.name)
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        # A relative import is the project's own code, never a dependency: nothing outside
        # the project can be reached by counting dots up from a file inside it.
        if not node.relative:
            self._root(node.module)
        return False

    def _take(self, node: cst.CSTNode) -> None:
        found: list[str] = []

        class _Strings(cst.CSTVisitor):
            def visit_SimpleString(self, item: cst.SimpleString) -> bool:
                text = item.evaluated_value
                if isinstance(text, str):
                    found.append(text)
                return False

        node.visit(_Strings())
        self.strings |= set(found)

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


def _module_of(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _owner(module: str, by_module: dict[str, str]) -> str:
    """Which node a file belongs to, by longest module prefix. `""` for project-level code."""
    parts = module.split(".")
    for cut in range(len(parts), 0, -1):
        found = by_module.get(".".join(parts[:cut]))
        if found is not None:
            return found
    return ""


def read_dependencies(
    root: Path,
    by_module: dict[str, str],
    database: Database | None = None,
) -> list[Dependency]:
    """Everything outside the project that the project's own code names.

    `by_module` maps a module path to the node that owns it, so a dependency can say which
    nodes reference it and an edge can be drawn from each. It is passed in rather than
    derived here: recognition of packages happens in the parser, and a second copy of that
    walk would be a second opinion about what a node is.
    """
    if not root.is_dir():
        return []

    found: dict[str, set[str]] = {sign.node: set() for sign in SIGNS}

    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts[:-1]
        if any(part.startswith((".", "_")) or part in SKIP for part in parts):
            continue
        module = _parse(path)
        if module is None:
            continue
        seeker = _Signals()
        module.visit(seeker)
        owner = _owner(_module_of(path, root), by_module)
        for sign in SIGNS:
            named = bool(seeker.roots & set(sign.imports)) or any(
                prefix in text for text in seeker.strings for prefix in sign.literals
            )
            if named:
                found[sign.node].add(owner)

    out: list[Dependency] = []

    store = database if database is not None else read_database(root)
    if store.present:
        out.append(
            Dependency(
                id=DATABASE_NODE,
                name=store.label,
                # Left empty: storage imports are resolved in the parser, where a module that
                # declares a table is already known, and two answers to that would disagree.
                used_by=(),
                paid=False,
            )
        )

    for sign in SIGNS:
        if not found[sign.node]:
            continue
        out.append(
            Dependency(
                id=sign.node,
                name=sign.node,
                used_by=tuple(sorted(item for item in found[sign.node] if item)),
                paid=sign.paid,
            )
        )

    if any((root / name).is_file() for name in DOCKER_FILES):
        out.append(
            Dependency(
                id=DOCKER_NODE,
                name=DOCKER_NODE,
                # No import can point at Docker. What it runs is declared in a file, and the
                # file node is where a person goes to change it.
                used_by=(),
                paid=False,
            )
        )

    return out
