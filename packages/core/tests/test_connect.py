"""Connecting two nodes is a write into the generated zone (P21, Q31).

The claims worth holding are the ones that separate this from a flow-document builder.
There an edge is data and dropping a wire *is* the connection. Here the gesture writes a
call into real code and the arrow -- if one appears at all -- appears afterwards, because a
type now crosses a boundary or because a run drew a flow (Q9). So: the code changes, the
change is confined to the generated zone, an undescribed composition is refused with both
kinds named, and nothing anywhere records that a connection was made.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from framestack_core.api import read_graph
from framestack_core.compose import composition_for, targets_for
from framestack_core.gate import check_graph
from framestack_core.parser import parse_project
from framestack_core.writer import connect

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"

#: A router the example does not mount, so there is something left to connect.
NOTES = '''"""Notes routes."""

from fastapi import APIRouter

from bp import editable, generated, node


@node(id="notes.list", kind="fastapi.route", title="List notes")
@editable(signature_locked=True)
def list_notes() -> list[str]:
    # USER-EDITABLE. Signature is locked; changing it breaks the node's edge.
    return ["one", "two"]


@node(id="notes", kind="fastapi.router", title="Notes", members=[list_notes])
@generated()
def notes_router() -> APIRouter:
    # GENERATED. Router assembly; edited through the graph, not by hand.
    router = APIRouter(prefix="/notes", tags=["notes"])
    router.add_api_route("", list_notes, methods=["GET"])
    return router
'''


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The example, plus an unmounted router, and nothing else changed."""
    root = tmp_path / "service"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    (root / "app" / "api" / "notes.py").write_text(NOTES, encoding="utf-8")

    manifest = root / "app" / "api" / "__node__.py"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace(
        "from app.api.users import users_router",
        "from app.api.notes import notes_router\nfrom app.api.users import users_router",
        1,
    )
    text = text.replace(
        "members=[health, users_router, ApiSettings],",
        "members=[health, users_router, notes_router, ApiSettings],",
        1,
    )
    manifest.write_text(text, encoding="utf-8")
    return root


# -- the table -------------------------------------------------------------------------


def test_a_composition_is_described_or_it_does_not_exist() -> None:
    """No fallback and no inference: the table answers, or the answer is `None`."""
    assert composition_for("fastapi.router", "fastapi.service") is not None
    assert composition_for("fastapi.settings", "fastapi.service") is None
    assert composition_for("fastapi.router", "langgraph.agent") is None


def test_what_a_kind_may_be_connected_to_comes_from_the_same_table() -> None:
    """A canvas asks this to decline a gesture; there must not be a second list to ask."""
    assert targets_for("fastapi.router") == ("fastapi.service",)
    assert targets_for("fastapi.settings") == ()


# -- writing ---------------------------------------------------------------------------


def test_connecting_writes_the_call_into_the_generated_zone(project: Path) -> None:
    result = connect(project, "notes", "api")

    assert result.written
    assert result.file == "app/main.py"
    assert "app.include_router(notes_router())" in (project / "app" / "main.py").read_text(
        encoding="utf-8"
    )


def test_the_call_lands_before_the_return(project: Path) -> None:
    """A generated zone builds something and hands it back: a line after the `return` could
    never run, and one before the app exists would act on nothing."""
    connect(project, "notes", "api")

    lines = [
        line.strip()
        for line in (project / "app" / "main.py").read_text(encoding="utf-8").splitlines()
    ]

    assert lines.index("app.include_router(notes_router())") < lines.index("return app")


def test_only_the_assembly_file_is_touched(project: Path) -> None:
    """`git diff` shows a generated-zone edit and nothing else -- one file, and it is the
    one that holds the assembly."""
    before = {
        path: path.read_bytes() for path in project.rglob("*.py") if "__pycache__" not in path.parts
    }

    connect(project, "notes", "api")

    changed = {
        path.relative_to(project).as_posix()
        for path, was in before.items()
        if path.read_bytes() != was
    }

    assert changed == {"app/main.py"}


def test_the_gate_still_accepts_the_project(project: Path) -> None:
    connect(project, "notes", "api")

    assert list(check_graph(parse_project(project)).errors) == []


def test_connecting_draws_no_flow_arrow_by_itself(project: Path) -> None:
    """**The difference from every flow-document builder, as a test.**

    There, dropping a wire *is* the connection and the arrow is the record of it. Here the
    gesture writes a call, and flow comes from a run and from nowhere else (Q9) -- so a
    project that has just been connected and never observed has no flow at all. If somebody
    ever makes a gesture put an arrow on the graph, this is the test that fails.
    """
    connect(project, "notes", "api")

    payload = read_graph(project)

    assert payload["flow"] == []
    # And every contract edge that exists carries the type that crosses the boundary. An
    # edge with nothing to name would be a connection recorded for its own sake.
    assert all(edge["contract"] for edge in payload["graph"]["edges"])


def test_nothing_records_that_a_connection_was_made(project: Path) -> None:
    """There is no graph file to write a connection into, and there must never be one."""
    connect(project, "notes", "api")

    state = project / ".framestack"
    written = {path.name for path in state.rglob("*")} if state.exists() else set()

    assert "edges.json" not in written
    assert "connections.json" not in written


# -- refusing --------------------------------------------------------------------------


def test_an_undescribed_composition_is_refused_with_both_kinds_named(project: Path) -> None:
    """A wrong write into a generated zone is a broken project; a refusal is a sentence."""
    result = connect(project, "api.settings", "api")

    assert not result.written
    assert "fastapi.settings" in (result.refused or "")
    assert "fastapi.service" in (result.refused or "")


def test_a_refusal_writes_nothing(project: Path) -> None:
    before = (project / "app" / "main.py").read_text(encoding="utf-8")

    connect(project, "api.settings", "api")

    assert (project / "app" / "main.py").read_text(encoding="utf-8") == before


def test_connecting_the_same_pair_twice_is_refused(project: Path) -> None:
    """Writing it again would mount the same router twice, which is a real change."""
    connect(project, "notes", "api")

    result = connect(project, "notes", "api")

    assert not result.written
    assert "already connected" in (result.refused or "")


def test_a_node_cannot_be_connected_to_itself(project: Path) -> None:
    assert not connect(project, "notes", "notes").written


def test_an_unknown_node_is_refused_by_name(project: Path) -> None:
    assert "not-a-node" in (connect(project, "not-a-node", "api").refused or "")
