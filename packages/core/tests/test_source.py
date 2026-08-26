"""The code a node carries, read for the panel that shows it.

The graph deliberately holds no editable body -- I-1 says the file is the only copy -- so
"show me this node's code" is a read of its own. What is worth testing is that it stays a
read: the right span of the right file, the most specific node's panel, and a refusal where
there is nothing to answer.
"""

from __future__ import annotations

from pathlib import Path

from test_api import validate, wire_form

from aibuilder_core.api import NODE_SOURCE_SCHEMA, read_source
from aibuilder_core.source import node_source

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def test_a_nodes_own_function_comes_back_as_it_is_on_disk() -> None:
    read = node_source(EXAMPLE, "health")

    assert read.file == "app/api/health.py"
    assert [function.path for function in read.functions] == ["app.api.health.health"]
    body = read.functions[0]
    assert body.zone == "editable"
    assert body.signature_locked is True
    # The text is the file's, decorators included: an editor that showed a body without the
    # markup above it would be showing something the person cannot save back.
    assert body.source.startswith("@node(")
    assert "return" in body.source


def test_a_function_appears_on_the_most_specific_node_only() -> None:
    """A module carrier owns everything inside it, so ownership alone would put a route's
    body in its module's panel as well as its own -- and an edit made in the wrong panel
    is an edit made through the wrong node (I-6)."""
    route = node_source(EXAMPLE, "health")
    owning = [
        node
        for node in ("api", "service")
        if any(f.path == "app.api.health.health" for f in node_source(EXAMPLE, node).functions)
    ]

    assert [f.path for f in route.functions] == ["app.api.health.health"]
    assert owning == []


def test_a_node_that_is_not_on_the_graph_is_answered_not_raised() -> None:
    read = node_source(EXAMPLE, "no-such-node")

    assert read.refused is not None
    assert read.functions == ()


def test_reading_a_nodes_code_matches_the_declared_contract() -> None:
    payload = read_source(EXAMPLE, "health")

    validate(wire_form(payload), NODE_SOURCE_SCHEMA)


def test_reading_source_never_writes(tmp_path: Path) -> None:
    """It opens a file and nothing else. A read that could touch the project would be a
    second way for looking at a graph to change it (P11)."""
    import shutil

    copy = tmp_path / "project"
    shutil.copytree(EXAMPLE, copy)
    before = {p.relative_to(copy): p.stat().st_mtime_ns for p in copy.rglob("*") if p.is_file()}

    node_source(copy, "health")

    after = {p.relative_to(copy): p.stat().st_mtime_ns for p in copy.rglob("*") if p.is_file()}
    assert after == before


def test_reading_a_nodes_code_is_a_method_in_the_core() -> None:
    """The extension point is `HANDLERS`, never a new command in the Rust shell."""
    from aibuilder_core.handlers import dispatch

    answer = dispatch("node.source", {"project": str(EXAMPLE), "node": "health"})

    assert answer["file"] == "app/api/health.py"
    assert answer["refused"] is None
