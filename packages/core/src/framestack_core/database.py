"""The project's storage, read from the project's own Python.

## One node per backend, never one per table

Twelve tables are twelve rows in a panel, not twelve boxes on a canvas. The graph answers
"what does this project talk to", and the answer for a database is one thing; which tables it
holds is a reading of that one thing, taken when somebody asks for it. Edges land on the node
for the same reason -- table-level edges produce a hairball, and the mapping is in the panel
where it can be read on demand.

## What is read, and what is refused

**`__tablename__` is the signal, and the base class is never resolved.** A declarative model
is a class that assigns `__tablename__` a string literal, and that assignment is the whole
test. Working out what a class inherits from would mean knowing SQLAlchemy's declarative
base, which is knowing a library -- and the parser learns no library, ever. A project that
writes raw SQL has no such classes, so `alembic/versions/` is read instead, for
`create_table("name", ...)` calls. Both are Python, read with libcst like everything else.

The connection target comes from a **string default in a `BaseSettings` field** whose scheme
is a Postgres one. It is a literal in the project's own code, not a guess and not a
connection: nothing here opens a socket, resolves a host or reads an environment. What the
database *is* the project states; whether it is up is a question for Phase 7, asked by
something that can actually ask it.

**Nothing here carries a verdict, and nothing ever will.** A database is not the project's
code: no test executes a Postgres, so no run can prove one. It is the second class of node in
the taxonomy -- a dependency, which has a status rather than a verdict -- and the two never
share a colour scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import libcst as cst

__all__ = [
    "DATABASE_NODE",
    "STORAGE_PACKAGE",
    "Database",
    "Table",
    "read_database",
]

#: The node a project's storage is drawn as. One per backend, and today there is one backend.
DATABASE_NODE = "postgres"

#: Where a project keeps the code that talks to storage.
#:
#: A convention this plan states, and the one place it is written down: `routes.py` reads it
#: too, so a route's arrow and a graph edge cannot disagree about what storage is.
STORAGE_PACKAGE = "repositories"

#: The URL schemes that mean "this is the Postgres this project uses".
#:
#: Matched on the scheme of a string literal, which is a fact in the file rather than a
#: reading of somebody's intent. A driver suffix (`+asyncpg`, `+psycopg`) is part of the
#: scheme SQLAlchemy defines, so it is matched by prefix rather than enumerated.
SCHEMES: tuple[str, ...] = ("postgresql", "postgres")

#: The marker of a declarative model. The assignment is the test; the base class is not.
TABLENAME = "__tablename__"

#: What alembic calls it when a migration creates a table.
CREATE_TABLE = "create_table"

#: Where migrations live, by alembic's own default layout.
MIGRATIONS = ("alembic", "versions")

#: Directories the walk never enters. Not a rule about what a project may contain -- a dot or
#: an underscore says "not somebody's package", and the rest are other ecosystems' caches.
SKIP = frozenset({"node_modules", "venv", "env", "site-packages", "dist", "build"})


@dataclass(frozen=True)
class Table:
    """One table the project declares."""

    name: str
    #: The file that declares it, project-relative. Who touches it, as the panel puts it.
    file: str
    #: Whether a column in it is a vector. What makes the backend `postgres + pgvector`.
    vector: bool

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "file": self.file, "vector": self.vector}


@dataclass(frozen=True)
class Database:
    """What the project's storage is, as read. Never whether it is running."""

    #: Whether there is a database to draw at all.
    present: bool
    #: The connection string the project states, or `""` where it states none.
    #:
    #: A literal from the project's own settings, never an environment and never a
    #: connection -- and with any credentials taken out of it, because a password rendered on
    #: a canvas is one console log away from being somewhere permanent.
    target: str
    #: True when a model declares a vector column. The node is labelled for it.
    vector: bool
    tables: tuple[Table, ...]
    #: The files that state a connection target, project-relative.
    #:
    #: **Who touches storage, where the code says so rather than where a convention would.**
    #: `repositories/` and a `__tablename__` are the two the plan names, and a project that
    #: has neither -- a `rag/` holding its own DSN and talking to Postgres directly -- was
    #: getting a database node with no line into it. The evidence that put the node on the
    #: canvas is a literal in one file; this is that file, so the edge is drawn by exactly
    #: the fact the node was. Never a second reading: `target` is still the first one found.
    named_in: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """What to call it on the canvas."""
        return f"{DATABASE_NODE} + pgvector" if self.vector else DATABASE_NODE

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "target": self.target,
            "vector": self.vector,
            "label": self.label,
            "tables": [table.as_dict() for table in self.tables],
        }


def _parse(path: Path) -> cst.Module | None:
    """The file as a tree, or nothing. Unreadable and unparseable are the same answer."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return cst.parse_module(source)
    except cst.ParserSyntaxError:
        return None


def _python_files(root: Path) -> list[Path]:
    """Every Python file in the project, sorted, minus the caches and other ecosystems.

    Sorted because I-4 asks the same question three times and expects the same answer, and
    `rglob` promises no order at all.
    """
    out: list[Path] = []
    for item in root.rglob("*.py"):
        parts = item.relative_to(root).parts[:-1]
        if any(part.startswith((".", "_")) or part in SKIP for part in parts):
            continue
        out.append(item)
    return sorted(out)


def _mentions(path: Path, marker: str) -> str | None:
    """The file's text if it contains `marker`, else nothing.

    A substring test before a parse. libcst is not cheap and most of a project's files
    declare no tables, so this is what keeps reading a large project from costing a walk of
    every syntax tree in it. It is a filter and never a decision: a file that passes is still
    parsed, and a table is still recognised by the assignment rather than by the word.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return source if marker in source else None


class _Vectors(cst.CSTVisitor):
    """Whether anything in a subtree names a vector column type.

    The name, not the import: `Vector`, `VECTOR` and `pgvector.sqlalchemy.Vector` are the
    same declaration written three ways, and which one a project uses is a fact about their
    import style rather than about their schema.
    """

    def __init__(self) -> None:
        self.found = False

    def visit_Name(self, node: cst.Name) -> bool:
        if node.value.lower() == "vector":
            self.found = True
        return True

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        if node.attr.value.lower() == "vector":
            self.found = True
        return True


def _string_of(node: cst.BaseExpression) -> str:
    """A string literal's value, or `""` for anything that is not one."""
    if isinstance(node, cst.SimpleString):
        text = node.evaluated_value
        if isinstance(text, str):
            return text
    return ""


def _tables_in(module: cst.Module) -> list[tuple[str, bool]]:
    """`(name, is_vector)` for every declarative model in one module, in source order.

    A model is a class whose body assigns `__tablename__` a string literal. Nothing about
    the base class is inspected, and that refusal is the point: resolving it would mean
    knowing which library the project uses, and the moment this file knows a library it is
    the kind registry again.
    """
    found: list[tuple[str, bool]] = []
    for statement in module.body:
        if not isinstance(statement, cst.ClassDef):
            continue
        name = ""
        for line in statement.body.body:
            if not isinstance(line, cst.SimpleStatementLine):
                continue
            for small in line.body:
                if not isinstance(small, cst.Assign):
                    continue
                for target in small.targets:
                    if isinstance(target.target, cst.Name) and target.target.value == TABLENAME:
                        name = _string_of(small.value)
        if not name:
            continue
        seeker = _Vectors()
        statement.body.visit(seeker)
        found.append((name, seeker.found))
    return found


def _migrated_in(module: cst.Module) -> list[str]:
    """The table names one alembic migration creates, in source order.

    Read only where there are no models: a project that has both would list every table
    twice, once as it is now and once as it was when somebody wrote the migration.
    """
    found: list[str] = []

    class _Created(cst.CSTVisitor):
        def visit_Call(self, node: cst.Call) -> bool:
            func = node.func
            named = (
                func.attr.value
                if isinstance(func, cst.Attribute)
                else func.value
                if isinstance(func, cst.Name)
                else ""
            )
            if named == CREATE_TABLE and node.args:
                name = _string_of(node.args[0].value)
                if name and name not in found:
                    found.append(name)
            return True

    module.visit(_Created())
    return found


def _redact(url: str) -> str:
    """The connection target with any credentials taken out of it.

    A default in a repository is not a secret this application is leaking, but a password
    rendered on a canvas is one console log from being somewhere permanent -- the same rule
    `mcp.py` follows about a server's `env`. What is useful here is what the project points
    at, which survives the removal intact.
    """
    scheme, _, rest = url.partition("://")
    if "@" not in rest:
        return url
    _, _, host = rest.rpartition("@")
    return f"{scheme}://{host}"


def _target_in(module: cst.Module) -> str:
    """A Postgres connection string stated as a default in this module, or `""`.

    The first one, in source order. A project with two is stating two, and picking between
    them would be this file having an opinion about which database is the real one.
    """

    class _Urls(cst.CSTVisitor):
        found = ""

        def visit_SimpleString(self, node: cst.SimpleString) -> bool:
            if self.found:
                return False
            text = node.evaluated_value
            if not isinstance(text, str) or "://" not in text:
                return False
            scheme = text.split("://", 1)[0].split("+", 1)[0]
            if scheme in SCHEMES:
                self.found = _redact(text)
            return False

    seeker = _Urls()
    module.visit(seeker)
    return seeker.found


def read_database(project: Path | str) -> Database:
    """What the project's storage is. Reads only; imports nothing; connects to nothing.

    Absent is a real answer: most projects have no database, and one drawn because the word
    appeared somewhere would be a node with nothing behind it.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return Database(False, "", False, ())

    files = _python_files(root)

    tables: list[Table] = []
    for file in files:
        source = _mentions(file, TABLENAME)
        if source is None:
            continue
        module = _parse(file)
        if module is None:
            continue
        where = file.relative_to(root).as_posix()
        for name, vector in _tables_in(module):
            tables.append(Table(name=name, file=where, vector=vector))

    # Migrations only where there are no models. Both would list every table twice: once as
    # it is now, and once as it was when somebody wrote the migration that made it.
    if not tables:
        for file in files:
            if not set(MIGRATIONS) <= set(file.relative_to(root).parts):
                continue
            if _mentions(file, CREATE_TABLE) is None:
                continue
            module = _parse(file)
            if module is None:
                continue
            where = file.relative_to(root).as_posix()
            for name in _migrated_in(module):
                tables.append(Table(name=name, file=where, vector=False))

    target = ""
    named_in: list[str] = []
    for file in files:
        if file.name != "settings.py":
            continue
        module = _parse(file)
        if module is None:
            continue
        stated = _target_in(module)
        if not stated:
            continue
        # Every file that states one, because each is a node naming the database. `target`
        # stays the first, in source order: two connection strings are a project stating
        # two, and choosing between them would be this file having an opinion about which
        # database is the real one -- but both files are still touching storage.
        named_in.append(file.relative_to(root).as_posix())
        if not target:
            target = stated

    return Database(
        # A table or a connection string. Either is the project saying it has a database;
        # neither is a guess, and without one there is nothing to draw.
        present=bool(tables or target),
        target=target,
        vector=any(table.vector for table in tables),
        tables=tuple(tables),
        named_in=tuple(named_in),
    )
