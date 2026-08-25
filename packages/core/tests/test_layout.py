"""Where the person put things (Q13, amended).

The layout is the fifth file in `.aibuilder/`, and the tests here are almost entirely about
what it is **not** allowed to be. It cannot add a node, remove one, rename one, or change
anything the graph says — and the core cannot look inside it, because a core that understood
a coordinate would sooner or later be asked to produce one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from test_api import validate, wire_form

from aibuilder_core.api import LAYOUT_READ_SCHEMA, LAYOUT_WRITE_SCHEMA, layout_get, layout_put
from aibuilder_core.layout import LAYOUT_PATH, read_layout, write_layout
from aibuilder_core.parser import parse_project

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"

POSITIONS = {
    "api": {"x": 40, "y": 40, "collapsed": False},
    "health": {"x": 220, "y": 120},
    "users": {"x": 220, "y": 260, "collapsed": True},
}


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".aibuilder"))
    return root


def test_a_layout_comes_back_exactly_as_it_was_stored(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert write_layout(root, POSITIONS).ok is True

    assert read_layout(root) == POSITIONS


def test_the_core_stores_whatever_shape_the_canvas_needs(tmp_path: Path) -> None:
    """The contract is the refusal to look inside.

    Coordinates today, a collapsed flag beside them, something nobody has thought of yet --
    none of it is the core's business, and a store that validated the shape would be a store
    with an opinion about what a layout is.
    """
    root = project(tmp_path)
    strange = {"api": {"anything": [1, 2, {"at": "all"}]}, "note": "not a position"}

    write_layout(root, strange)

    assert read_layout(root) == strange


def test_no_layout_is_an_ordinary_answer(tmp_path: Path) -> None:
    """It is what a project looks like the first time it is opened."""
    assert read_layout(project(tmp_path)) == {}


def test_a_corrupt_layout_never_costs_the_graph(tmp_path: Path) -> None:
    """A cache that cannot be read is a cache that holds nothing. It is not an error.

    The nodes come back in different places and the person moves them again. Refusing to
    draw a graph because a convenience file was truncated would be the tail wagging the dog.
    """
    root = project(tmp_path)
    path = root / LAYOUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"api": {"x": 4', encoding="utf-8")

    assert read_layout(root) == {}
    assert len(parse_project(root).nodes) == 6


def test_a_write_replaces_and_never_merges(tmp_path: Path) -> None:
    """Merging would mean deciding which entry wins, and the core decides nothing here."""
    root = project(tmp_path)
    write_layout(root, POSITIONS)

    write_layout(root, {"health": {"x": 1, "y": 1}})

    assert read_layout(root) == {"health": {"x": 1, "y": 1}}


def test_the_layout_is_not_a_source_the_graph_reads_from(tmp_path: Path) -> None:
    """I-1, at the one place a second store of state was most likely to appear.

    An entry naming a node that does not exist changes nothing, and a node with no entry is
    still in the graph. The file answers one question -- where to draw this -- and cannot
    answer any other.
    """
    root = project(tmp_path)
    before = parse_project(root).to_dict()

    write_layout(root, {"ghost": {"x": 0, "y": 0}, "health": {"x": 9, "y": 9}})

    assert parse_project(root).to_dict() == before


def test_deleting_it_changes_nothing_about_the_project(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_layout(root, POSITIONS)
    before = parse_project(root).to_dict()

    (root / LAYOUT_PATH).unlink()

    assert parse_project(root).to_dict() == before
    assert read_layout(root) == {}


def test_it_is_stored_beside_the_other_tooling_state(tmp_path: Path) -> None:
    """The fifth file in `.aibuilder/`, and it is not project source."""
    root = project(tmp_path)
    write_layout(root, POSITIONS)

    assert (root / ".aibuilder" / "layout.json").is_file()
    assert json.loads((root / LAYOUT_PATH).read_text())["health"] == {"x": 220, "y": 120}


def test_a_payload_that_will_not_serialise_leaves_the_previous_one_alone(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_layout(root, POSITIONS)

    result = write_layout(root, {"api": {1, 2, 3}})  # type: ignore[dict-item]

    assert result.ok is False
    assert read_layout(root) == POSITIONS


def test_the_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)

    validate(wire_form(layout_put(str(root), POSITIONS)), LAYOUT_WRITE_SCHEMA)
    validate(wire_form(layout_get(str(root))), LAYOUT_READ_SCHEMA)


def test_the_capability_is_a_method_in_the_core(tmp_path: Path) -> None:
    """Q13's amendment: the webview may call `core_request` and nothing else.

    A filesystem plugin in the shell would mean a second implementation the moment a second
    client exists -- and two implementations of one thing drift.
    """
    from aibuilder_core.handlers import dispatch

    root = project(tmp_path)
    dispatch("layout.write", {"project": str(root), "layout": POSITIONS})

    assert dispatch("layout.read", {"project": str(root)})["layout"] == POSITIONS


def test_a_layout_that_is_not_an_object_is_a_protocol_fault() -> None:
    from aibuilder_core.handlers import dispatch
    from aibuilder_core.protocol import ProtocolError

    try:
        dispatch("layout.write", {"project": ".", "layout": [1, 2]})
    except ProtocolError as error:
        assert "must be an object" in str(error)
    else:  # pragma: no cover
        raise AssertionError("a list is not a layout")
