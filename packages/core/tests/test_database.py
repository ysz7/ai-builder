"""The project's storage, read from the project's own Python (Phase 6).

The reference has no database at all, which is the case that matters most here: a node drawn
because the word "postgres" appeared somewhere would be a box with nothing behind it. So
every test that wants one builds it, one file at a time, and asserts the one thing that moves.

**One node per backend, never one per table.** Twelve tables are twelve rows in a panel;
twelve boxes would be a hairball whose every edge had to choose a table to land on.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import DATABASE_SCHEMA, database_read
from framestack_core.database import read_database
from framestack_core.parser import read_graph

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"

MODEL = (
    "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n\n"
    "class Base(DeclarativeBase):\n    pass\n\n\n"
    "class Document(Base):\n"
    '    __tablename__ = "documents"\n\n'
    "    id: Mapped[int] = mapped_column(primary_key=True)\n"
)


#: An example with no storage at all. Most projects have none, and the tests below are about
#: what *makes* one — so they start from a project where nothing does.
NO_STORAGE = Path(__file__).resolve().parents[3] / "examples" / "rag"


def project(tmp_path: Path) -> Path:
    """A copy with no storage in it.

    `examples/full` has a real one, which is exactly why it cannot be the fixture here: a
    test asking "does adding a model add a row" has to start from no rows.
    """
    root = tmp_path / "project"
    shutil.copytree(NO_STORAGE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def store(root: Path, name: str, body: str) -> None:
    """Write `repositories/<name>.py`, making the package if it is not there yet."""
    where = root / "repositories"
    where.mkdir(exist_ok=True)
    (where / "__init__.py").touch()
    (where / f"{name}.py").write_text(body, encoding="utf-8")


def names(root: Path) -> list[str]:
    return [table.name for table in read_database(root).tables]


def reader(root: Path, body: str) -> None:
    """Write a module in `api/` that does — or does not — import a model.

    The importer is the api because this fixture has one; which system does the importing is
    not what any of these tests is about, and the edge is drawn by the same rule either way.
    """
    (root / "api" / "reader.py").write_text(body, encoding="utf-8")


# -- absent is a real answer -----------------------------------------------------------


def test_an_example_with_no_storage_has_no_node_for_one() -> None:
    """Most projects have none. A node drawn anyway would be a box with nothing behind it.

    `examples/rag` keeps its index in a file, and it does have a `docker` dependency -- it
    has a `compose.yaml` -- so this asks about the storage node by name rather than about the
    family it belongs to.
    """
    assert read_database(NO_STORAGE).present is False
    assert not [node for node in read_graph(NO_STORAGE).nodes if node.id == "postgres"]


def test_the_example_that_does_store_things_names_its_tables() -> None:
    """The other half, on a project that has one: two tables, read from the models
    themselves, and the connection string out of the settings default with nothing secret
    left in it."""
    found = read_database(EXAMPLE)

    assert found.present is True
    assert [table.name for table in found.tables] == ["conversations", "turns"]
    assert found.target.startswith("postgresql")
    assert "reference:reference" not in found.target


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert read_database(tmp_path / "nowhere").present is False


# -- how tables are found --------------------------------------------------------------


def test_adding_a_model_class_adds_a_table_row(tmp_path: Path) -> None:
    """The plan's first criterion, and no graph code is touched to make it happen."""
    root = project(tmp_path)
    assert names(root) == []

    store(root, "document", MODEL)

    assert names(root) == ["documents"]


def test_the_base_class_is_never_resolved(tmp_path: Path) -> None:
    """`__tablename__` is the whole test.

    Working out what a class inherits from would mean knowing SQLAlchemy's declarative base,
    which is knowing a library -- and the parser learns no library, ever. A model on a base
    imported from three modules away is the same model.
    """
    root = project(tmp_path)
    store(
        root,
        "odd",
        "from somewhere.deep import OurOwnBase\n\n\n"
        "class Session(OurOwnBase):\n"
        '    __tablename__ = "agent_sessions"\n',
    )

    assert names(root) == ["agent_sessions"]


def test_a_class_without_a_tablename_is_not_a_table(tmp_path: Path) -> None:
    """A mixin, a schema, a plain class. Only the assignment says "table"."""
    root = project(tmp_path)
    store(root, "plain", "class Helper:\n    name = 'documents'\n")

    assert names(root) == []


def test_a_tablename_that_is_not_a_literal_is_not_read(tmp_path: Path) -> None:
    """A name built at import time is one nobody reading the file could have known."""
    root = project(tmp_path)
    store(
        root,
        "computed",
        "PREFIX = 'app'\n\n\nclass Document:\n    __tablename__ = PREFIX + '_documents'\n",
    )

    assert names(root) == []


def test_the_declaring_file_is_the_one_the_panel_names(tmp_path: Path) -> None:
    """ "Who touches it" is where it is declared, which is a fact rather than an inference."""
    root = project(tmp_path)
    store(root, "document", MODEL)

    assert read_database(root).tables[0].file == "repositories/document.py"


def test_migrations_are_read_only_where_there_are_no_models(tmp_path: Path) -> None:
    """A project with both would list every table twice: once as it is now, and once as it
    was when somebody wrote the migration that made it."""
    root = project(tmp_path)
    versions = root / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_initial.py").write_text(
        "import sqlalchemy as sa\nfrom alembic import op\n\n\n"
        "def upgrade() -> None:\n"
        '    op.create_table("jobs", sa.Column("id", sa.Integer()))\n',
        encoding="utf-8",
    )

    assert names(root) == ["jobs"]

    store(root, "document", MODEL)

    assert names(root) == ["documents"]


# -- pgvector --------------------------------------------------------------------------


def test_a_vector_column_labels_the_node_and_marks_its_table(tmp_path: Path) -> None:
    """The plan's rule, and both halves of it: the node is renamed and the table is marked."""
    root = project(tmp_path)
    store(
        root,
        "chunk",
        "from pgvector.sqlalchemy import Vector\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n\n\n"
        "class Chunk:\n"
        '    __tablename__ = "chunks"\n\n'
        "    embedding: Mapped[list[float]] = mapped_column(Vector(1536))\n",
    )
    store(root, "document", MODEL)

    database = read_database(root)
    assert database.label == "postgres + pgvector"
    assert {table.name: table.vector for table in database.tables} == {
        "chunks": True,
        "documents": False,
    }
    node = next(item for item in read_graph(root).nodes if item.kind == "dependency")
    assert node.name == "postgres + pgvector"


def test_without_a_vector_column_it_is_plain_postgres(tmp_path: Path) -> None:
    root = project(tmp_path)
    store(root, "document", MODEL)

    assert read_database(root).label == "postgres"


# -- the connection target -------------------------------------------------------------


def test_a_project_with_no_models_shows_the_connection_target_and_no_tables(
    tmp_path: Path,
) -> None:
    """The plan's third criterion. A project on raw SQL still says what it talks to."""
    root = project(tmp_path)
    (root / "api" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class ApiSettings(BaseSettings):\n"
        '    database_url: str = "postgresql://localhost:5432/app"\n',
        encoding="utf-8",
    )

    database = read_database(root)
    assert database.present is True
    assert database.target == "postgresql://localhost:5432/app"
    assert database.tables == ()


def test_a_driver_suffix_is_part_of_the_scheme(tmp_path: Path) -> None:
    """`postgresql+asyncpg` is what SQLAlchemy calls it, so it is matched by prefix."""
    root = project(tmp_path)
    (root / "api" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class ApiSettings(BaseSettings):\n"
        '    dsn: str = "postgresql+asyncpg://localhost/app"\n',
        encoding="utf-8",
    )

    assert read_database(root).target.startswith("postgresql+asyncpg://")


def test_a_credential_never_reaches_the_payload(tmp_path: Path) -> None:
    """A password rendered on a canvas is one console log from being somewhere permanent.

    The same rule `mcp.py` follows about a server's `env`. What is useful is what the project
    points at, and that survives the removal intact.
    """
    root = project(tmp_path)
    (root / "api" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class ApiSettings(BaseSettings):\n"
        '    dsn: str = "postgresql://bob:hunter2@db.internal:5432/app"\n',
        encoding="utf-8",
    )

    target = read_database(root).target
    assert "hunter2" not in target
    assert target == "postgresql://db.internal:5432/app"


def test_another_backend_s_url_is_not_a_postgres(tmp_path: Path) -> None:
    """One node per backend, and this is not that backend."""
    root = project(tmp_path)
    (root / "api" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class ApiSettings(BaseSettings):\n"
        '    cache_url: str = "redis://localhost:6379/0"\n',
        encoding="utf-8",
    )

    assert read_database(root).present is False


# -- the edges -------------------------------------------------------------------------


def test_a_system_importing_a_model_draws_an_edge_to_the_node(tmp_path: Path) -> None:
    """The plan's second criterion. The import is the edge, as everywhere else."""
    root = project(tmp_path)
    store(root, "document", MODEL)
    reader(root, "from repositories.document import Document\n\n\nUSED = Document\n")

    found = {(edge.source, edge.target) for edge in read_graph(root).edges}
    assert ("api", "postgres") in found


def test_removing_the_import_removes_the_edge(tmp_path: Path) -> None:
    root = project(tmp_path)
    store(root, "document", MODEL)
    reader(root, "from repositories.document import Document\n\n\nUSED = Document\n")
    assert ("api", "postgres") in {(e.source, e.target) for e in read_graph(root).edges}

    reader(root, "USED = None\n")

    assert ("api", "postgres") not in {(e.source, e.target) for e in read_graph(root).edges}


def test_the_system_that_states_the_connection_string_gets_the_edge(tmp_path: Path) -> None:
    """A project with no `repositories/` and no model still says who touches storage.

    A `rag/` holding its own DSN and speaking to Postgres directly is the ordinary shape,
    and it was producing a database node with no line into it -- which reads as "nothing
    uses this" about the one fact the node was derived from. The edge comes from that same
    fact, so the two can never disagree.
    """
    root = project(tmp_path)
    (root / "rag" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        '    dsn: str = "postgresql://localhost/rag"\n',
        encoding="utf-8",
    )

    graph = read_graph(root)
    assert any(node.id == "postgres" for node in graph.nodes)
    assert ("rag", "postgres") in {(edge.source, edge.target) for edge in graph.edges}


def test_the_connection_string_edge_is_never_a_second_copy(tmp_path: Path) -> None:
    """The import walk owns the edge where it draws one; this only fills a gap.

    Two answers to "who touches storage" would put two edges with one id on the canvas,
    which is a duplicate React key and a line drawn twice.
    """
    root = project(tmp_path)
    store(root, "document", MODEL)
    reader(root, "from repositories.document import Document\n\n\nUSED = Document\n")
    (root / "api" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        '    dsn: str = "postgresql://localhost/app"\n',
        encoding="utf-8",
    )

    edges = [edge for edge in read_graph(root).edges if edge.target == "postgres"]
    assert [edge.source for edge in edges] == ["api"]
    assert len({edge.id for edge in edges}) == len(edges)


def test_an_edge_lands_on_the_node_and_never_on_a_table(tmp_path: Path) -> None:
    """Table-level edges produce a hairball. The mapping lives in the panel, read on demand."""
    root = project(tmp_path)
    store(root, "document", MODEL)
    reader(root, "from repositories.document import Document\n\n\nUSED = Document\n")

    for edge in read_graph(root).edges:
        if edge.target == "postgres":
            assert edge.port == ""
    assert next(item for item in read_graph(root).nodes if item.id == "postgres").ports == ()


def test_the_database_carries_no_verdict_and_is_not_a_package(tmp_path: Path) -> None:
    """Nothing in a test run executes a Postgres, so nothing can prove one.

    A dependency has a status, which is a different claim from a different mechanism. Were
    this a package, Observe would hand coverage a source directory that does not exist and
    the node would turn grey for not being reached by a test -- a wrong colour, which is the
    one thing this product cannot ship.
    """
    from framestack_core.parser import is_system

    root = project(tmp_path)
    store(root, "document", MODEL)

    node = next(item for item in read_graph(root).nodes if item.id == "postgres")
    assert not is_system(node)
    assert node.exports == () and node.missing == () and node.complete is True


def test_reading_the_same_project_three_times_gives_the_same_tables(tmp_path: Path) -> None:
    """I-4 in the small: `rglob` promises no order, so the walk sorts and stays sorted."""
    root = project(tmp_path)
    store(root, "document", MODEL)
    store(root, "chunk", MODEL.replace("Document", "Chunk").replace("documents", "chunks"))

    assert len({tuple(names(root)) for _ in range(3)}) == 1


# -- the contract ----------------------------------------------------------------------


def test_the_payload_matches_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    store(root, "document", MODEL)
    validate(wire_form(database_read(root)), DATABASE_SCHEMA)


def test_an_absent_database_matches_the_same_contract() -> None:
    validate(wire_form(database_read(EXAMPLE)), DATABASE_SCHEMA)
