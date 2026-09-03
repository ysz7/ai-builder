"""Live re-parse, as a question the caller asks (Phase 13).

The wire pushes nothing, so "the graph updates as the code changes" is a revision number the
caller holds and sends back. Two things are under test and both are about restraint:

* **a save is reported once the tree has settled**, so a file an editor is halfway through
  writing never reaches the parser;
* **a file that does not parse marks one node and blanks nothing**, which is the difference
  between a canvas that follows the code and one that flickers while somebody types.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import WATCH_SCHEMA, watch_read
from framestack_core.parser import read_graph
from framestack_core.watch import SETTLE, forget_watch, read_watch

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "reference"

#: Long enough for the scan to run twice and the settle window to pass, short enough that a
#: watcher that never notices fails the suite rather than holding it open.
PATIENCE = 6


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def settled(root: Path, revision: int) -> tuple[int, bool]:
    """Poll until the watcher reports a change, or give up. The polling *is* the contract."""
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        answer = read_watch(root, revision)
        if answer.changed:
            return answer.revision, True
        time.sleep(0.05)
    return revision, False


# -- the question ---------------------------------------------------------------------------


def test_the_first_ask_starts_the_watch_and_reports_no_change(tmp_path: Path) -> None:
    """A caller that has just read the graph is not stale. Telling it otherwise would make
    every window re-parse the moment it opened."""
    root = project(tmp_path)
    try:
        answer = read_watch(root)

        assert answer.ok is True
        assert answer.changed is False
        assert answer.revision > 0
    finally:
        forget_watch(root)


def test_saving_a_file_the_parser_reads_moves_the_revision(tmp_path: Path) -> None:
    root = project(tmp_path)
    try:
        first = read_watch(root).revision

        (root / "rag" / "chunker.py").write_text("SIZE = 500\n", encoding="utf-8")
        revision, changed = settled(root, first)

        assert changed is True
        assert revision > first
        # And it stays reported until the caller catches up, then goes quiet.
        assert read_watch(root, revision).changed is False
    finally:
        forget_watch(root)


def test_a_file_the_parser_never_reads_is_not_a_change(tmp_path: Path) -> None:
    """A README saving is not a change to the graph, and re-parsing for one would be
    answering a question nobody asked."""
    root = project(tmp_path)
    try:
        first = read_watch(root).revision

        (root / "README.md").write_text("# hello\n", encoding="utf-8")
        time.sleep(SETTLE * 4)

        assert read_watch(root, first).changed is False
    finally:
        forget_watch(root)


def test_the_ignored_directories_are_not_watched(tmp_path: Path) -> None:
    """`.framestack/` in particular: this application writes there constantly, and a watcher
    that noticed would re-parse the project every time a run wrote a log line."""
    root = project(tmp_path)
    try:
        first = read_watch(root).revision

        for where in (".framestack", "__pycache__", ".venv"):
            (root / where).mkdir(exist_ok=True)
            (root / where / "noise.py").write_text("x = 1\n", encoding="utf-8")
        time.sleep(SETTLE * 4)

        assert read_watch(root, first).changed is False
    finally:
        forget_watch(root)


def test_forgetting_a_project_stops_watching_it(tmp_path: Path) -> None:
    root = project(tmp_path)
    read_watch(root)

    assert forget_watch(root).ok is True
    # And asking again starts a fresh watch rather than answering from the old one.
    assert read_watch(root).changed is False
    forget_watch(root)


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert read_watch(tmp_path / "nowhere").ok is False


# -- a broken file marks, never blanks --------------------------------------------------------


def test_a_syntax_error_marks_one_node_and_leaves_the_rest_intact(tmp_path: Path) -> None:
    """The acceptance criterion. A file mid-write is ordinary in a graph that re-reads itself
    on save, and a node that vanished for it would make the canvas flicker."""
    root = project(tmp_path)
    (root / "rag" / "chunker.py").write_text("def chunk(:\n", encoding="utf-8")

    graph = read_graph(root)
    rag = next(node for node in graph.nodes if node.id == "rag")

    assert rag.broken.startswith("chunker.py line ")
    # Nothing else about it moved: it still exports what its `__init__.py` binds.
    assert rag.missing == ()
    assert rag.complete is True
    # And no other node is marked.
    assert [node.id for node in graph.nodes if node.broken] == ["rag"]


def test_a_broken_init_still_leaves_a_node_on_the_canvas(tmp_path: Path) -> None:
    """The worst case: the file the exports are read from. The node is still there, with the
    reason said in its own words rather than repaired into a guess."""
    root = project(tmp_path)
    (root / "rag" / "__init__.py").write_text("def search(:\n", encoding="utf-8")

    rag = next(node for node in read_graph(root).nodes if node.id == "rag")

    assert rag.broken.startswith("__init__.py line ")
    assert rag.complete is False
    assert "could not be read" in rag.reason


def test_a_healthy_project_marks_nothing(tmp_path: Path) -> None:
    assert all(node.broken == "" for node in read_graph(project(tmp_path)).nodes)


# -- the wire ---------------------------------------------------------------------------------


def test_the_payload_matches_the_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    try:
        validate(wire_form(watch_read(root)), WATCH_SCHEMA)
        validate(wire_form(watch_read(root, 1)), WATCH_SCHEMA)
        validate(wire_form(watch_read(tmp_path / "nowhere")), WATCH_SCHEMA)
    finally:
        forget_watch(root)
