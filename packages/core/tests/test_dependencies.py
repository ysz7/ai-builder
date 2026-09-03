"""What the project's code talks to, and whether it can be reached (Phase 7).

Two halves, and the line between them is the phase's whole argument. **Recognition** is
static: an import root, a string literal, a file at the root -- read, never connected. **A
status** is a connection, asked once per request, and it is a different claim on a different
scale from a verdict. A reachable Postgres is not a proven one.

The checks that would cost money are never made, and there is a test that says so.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import STATUS_SCHEMA, status_read
from framestack_core.dependencies import CREDENTIALS, SIGNS
from framestack_core.parser import is_system, read_graph
from framestack_core.status import (
    CONFIGURED,
    REACHABLE,
    UNCONFIGURED,
    UNKNOWN,
    UNREACHABLE,
    read_status,
)

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def deps(root: Path) -> set[str]:
    return {node.id for node in read_graph(root).nodes if node.kind == "dependency"}


def edges_to(root: Path, node: str) -> set[str]:
    return {edge.source for edge in read_graph(root).edges if edge.target == node}


# -- how they appear: automatically, never by hand --------------------------------------


def test_the_example_names_only_what_its_own_code_reaches() -> None:
    """A `compose.yaml` makes `docker`; models and a connection string make `postgres`.

    Both are facts in the project: a file at the root, and a `__tablename__` beside a URL in
    a settings default. A node for a thing the code does not reference would be a box with
    nothing behind it, which is the defect the whole taxonomy exists to avoid — so there is
    no `redis` here, and no `anthropic`, because nothing in it names one.
    """
    assert deps(EXAMPLE) == {"docker", "postgres"}


def test_a_client_import_is_what_makes_the_node(tmp_path: Path) -> None:
    """`import redis` is the fact. Nothing is configured and nothing is placed by hand."""
    root = project(tmp_path)
    assert "redis" not in deps(root)

    (root / "worker" / "queue.py").write_text(
        "import redis\n\n\ndef client() -> object:\n    return redis.Redis()\n",
        encoding="utf-8",
    )

    assert "redis" in deps(root)


def test_removing_the_import_removes_the_node(tmp_path: Path) -> None:
    """A projection like every other: the node is the code, so deleting the code deletes it."""
    root = project(tmp_path)
    where = root / "worker" / "queue.py"
    where.write_text("import redis\n\n\ndef client() -> object:\n    return None\n", "utf-8")
    assert "redis" in deps(root)

    where.write_text("def client() -> object:\n    return None\n", encoding="utf-8")

    assert "redis" not in deps(root)


def test_a_model_name_in_settings_is_enough(tmp_path: Path) -> None:
    """The plan's other half of the rule: the SDK import, **or** a model name in settings."""
    root = project(tmp_path)
    (root / "agent" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class AgentSettings(BaseSettings):\n"
        '    model: str = "claude-sonnet-4-6"\n',
        encoding="utf-8",
    )

    assert "anthropic" in deps(root)


def test_a_docstring_that_names_a_provider_is_not_a_dependency(tmp_path: Path) -> None:
    """Prose is excluded by construction: a docstring is never an argument or a right-hand
    side, so the first agent documented in English cannot draw a box nobody asked for."""
    root = project(tmp_path)
    (root / "agent" / "notes.py").write_text(
        '"""We could use gpt-4 here one day."""\n\n\ndef notes() -> str:\n    return ""\n',
        encoding="utf-8",
    )

    assert "openai" not in deps(root)


def test_the_node_that_names_it_gets_the_edge(tmp_path: Path) -> None:
    """An edge from the package whose own file wrote the import, as everywhere else."""
    root = project(tmp_path)
    (root / "worker" / "queue.py").write_text("import redis\n", encoding="utf-8")

    assert edges_to(root, "redis") == {"worker"}


def test_docker_comes_from_a_file_and_has_no_edges() -> None:
    """No import can point at Docker. What it runs is declared in a file, and the file node
    is where a person goes to change it."""
    assert edges_to(EXAMPLE, "docker") == set()


def test_a_dependency_carries_no_verdict_and_is_not_a_package() -> None:
    """Nothing in a test run executes a Postgres, a Redis or an API.

    Were one a package, Observe would hand coverage a source directory that does not exist
    and the node would turn grey for not being reached by a test -- a wrong colour, which is
    the one thing this product cannot ship.
    """
    for node in read_graph(EXAMPLE).nodes:
        if node.kind == "dependency":
            assert not is_system(node)
            assert node.exports == () and node.ports == ()


def test_reading_the_reference_three_times_names_the_same_dependencies() -> None:
    """I-4 for this phase: recognition is a function of the files, asked three times."""
    assert len({frozenset(deps(EXAMPLE)) for _ in range(3)}) == 1


# -- the status --------------------------------------------------------------------------


def test_no_check_ever_costs_money() -> None:
    """The plan's third criterion, asserted as a property rather than as a behaviour.

    Every paid node is answered by looking for a credential, and the two states it can be in
    are named for that. If a future check were wired to a provider's API, this fails.
    """
    assert {"anthropic", "openai"} == CREDENTIALS
    for node in sorted(CREDENTIALS):
        answer = read_status(EXAMPLE, node)
        assert answer.status in (CONFIGURED, UNCONFIGURED)


def test_a_provider_with_no_key_says_so_and_names_the_variable(tmp_path: Path) -> None:
    """Actionable or it is decoration: the refusal says which line is missing."""
    root = project(tmp_path)
    answer = read_status(root, "anthropic")

    assert answer.status == UNCONFIGURED
    assert "ANTHROPIC_API_KEY" in answer.detail


def test_a_provider_with_a_key_is_configured_and_the_key_never_leaves_the_file(
    tmp_path: Path,
) -> None:
    """Only the **name** is read. A key in a payload is one console log from permanence."""
    root = project(tmp_path)
    env = root / ".env"
    env.write_text(
        env.read_text(encoding="utf-8") + "\nANTHROPIC_API_KEY=sk-ant-secret-value\n",
        encoding="utf-8",
    )

    answer = read_status(root, "anthropic")

    assert answer.status == CONFIGURED
    assert "secret-value" not in answer.detail
    assert "ANTHROPIC_API_KEY" in answer.detail


def test_a_commented_out_key_is_not_a_key(tmp_path: Path) -> None:
    root = project(tmp_path)
    env = root / ".env"
    env.write_text(
        env.read_text(encoding="utf-8") + "\n# ANTHROPIC_API_KEY=sk-ant-x\n", encoding="utf-8"
    )

    assert read_status(root, "anthropic").status == UNCONFIGURED


def test_a_postgres_with_nothing_to_connect_to_is_unknown_and_never_red(
    tmp_path: Path,
) -> None:
    """`unknown` and `unreachable` are different claims and are never merged.

    "There is no connection string" is not "the database refused". A person told the second
    would go looking for a database that was never asked for.
    """
    answer = read_status(project(tmp_path), "postgres")

    assert answer.status == UNKNOWN
    assert answer.status != UNREACHABLE


def test_a_check_with_no_driver_in_the_project_is_unknown_rather_than_red(
    tmp_path: Path,
) -> None:
    """The core has no Postgres driver and will not acquire one -- a connector written is a
    connector maintained. Where the project has none either, the honest answer is that this
    cannot be checked from here."""
    root = project(tmp_path)
    (root / "api" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class ApiSettings(BaseSettings):\n"
        '    database_url: str = "postgresql://127.0.0.1:1/nothing"\n',
        encoding="utf-8",
    )

    answer = read_status(root, "postgres")

    assert answer.status == UNKNOWN
    assert "psycopg" in answer.detail


def test_ollama_answers_one_of_two_states_and_always_says_why(tmp_path: Path) -> None:
    """A live check, and the only one with no driver behind it.

    Which of the two it is depends on whether this machine is running an Ollama, so the
    assertion is the property that holds either way: it is reachable or unreachable, never
    a third thing, and it always carries a reason. A test that demanded one of them would
    pass on one developer's laptop and fail on the next one's, which proves nothing about
    the code and is exactly the sort of evidence this product refuses elsewhere.
    """
    answer = read_status(project(tmp_path), "ollama")

    assert answer.status in (REACHABLE, UNREACHABLE)
    assert answer.detail


def test_a_node_nothing_can_check_says_so_rather_than_guessing(tmp_path: Path) -> None:
    """An MCP server's status is `list_tools`, which means speaking the protocol to it --
    and only the server knows. Until the client that can ask exists, this says it does not
    know, which is exactly true."""
    answer = read_status(project(tmp_path), "mcp.filesystem")

    assert answer.status == UNKNOWN
    assert answer.ok is False


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    answer = read_status(tmp_path / "nowhere", "docker")

    assert answer.ok is False
    assert answer.status == UNKNOWN


def test_every_sign_can_be_asked_for_a_status(tmp_path: Path) -> None:
    """A node the canvas can draw and the core cannot answer for is a control whose only
    possible outcome is an error."""
    root = project(tmp_path)
    for sign in SIGNS:
        assert read_status(root, sign.node).status != ""


# -- the contract ----------------------------------------------------------------------


def test_the_payload_matches_the_declared_contract(tmp_path: Path) -> None:
    validate(wire_form(status_read(project(tmp_path), "anthropic")), STATUS_SCHEMA)


def test_a_refusal_matches_the_same_contract(tmp_path: Path) -> None:
    validate(wire_form(status_read(tmp_path / "nowhere", "docker")), STATUS_SCHEMA)
