"""The graph, read from a project's own directories and imports (Phase 1).

Every test here is stated about `examples/reference` or about a copy of it, because that is
the fixture the plan's acceptance criteria are written against: four systems, four file
nodes, and one import between two of them.

The shape of these tests is the point of the rebuild. Each one changes **one thing in the
project** -- an import, a directory name, an export -- and asserts the one thing that
changes in the graph. That is only possible because recognition is a convention rather than
an annotation: there is nothing else the change could have broken.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import GRAPH_SCHEMA, graph_get
from framestack_core.parser import Graph, Node, read_graph

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "reference"


def project(tmp_path: Path) -> Path:
    """A writable copy. These tests edit the project; the reference is not theirs to edit."""
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def ids(graph: Graph, family: str) -> list[str]:
    """The node ids of one family: `"file"` for the four root files, `"system"` for the rest."""
    wanted = family == "file"
    return sorted(item.id for item in graph.nodes if (item.kind == "file") is wanted)


def edges(graph: Graph) -> set[tuple[str, str, str]]:
    return {(edge.source, edge.target, edge.kind) for edge in graph.edges}


def node(graph: Graph, node_id: str) -> Node:
    found = [item for item in graph.nodes if item.id == node_id]
    assert found, f"no node {node_id!r} in {[item.id for item in graph.nodes]}"
    return found[0]


# -- what the reference is -------------------------------------------------------------


def test_the_reference_is_four_systems_and_four_files() -> None:
    """The acceptance criterion, stated as one assertion.

    `exactly` is the load-bearing word. A parser that found five would be one that guessed
    about a directory, and every guess this file exists to prevent starts as one extra node.
    """
    graph = read_graph(EXAMPLE)

    assert graph.ok is True
    assert ids(graph, "system") == ["agent", "api", "rag", "worker"]
    assert ids(graph, "file") == [".env", "Dockerfile", "compose.yaml", "mcp.json"]


def test_every_system_in_the_reference_is_complete() -> None:
    """Its four packages export what their kinds require, which is what makes it a fixture."""
    graph = read_graph(EXAMPLE)

    for item in graph.nodes:
        assert item.complete is True, f"{item.id}: {item.reason}"
        assert item.missing == ()


def test_a_kind_is_never_a_framework() -> None:
    """The whole reason there are four kinds and not twenty-seven.

    `agent/` is recognised because it exports `run`, and nothing in the payload may say what
    it is built on -- the moment a stack appears in a kind, the registry is back.
    """
    graph = read_graph(EXAMPLE)

    assert {item.kind for item in graph.nodes} == {"agent", "api", "rag", "worker", "file"}


def test_file_nodes_carry_no_contract() -> None:
    """They are shown, opened and edited. Nothing runs them, so nothing can prove them."""
    graph = read_graph(EXAMPLE)

    for item in graph.nodes:
        if item.kind != "file":
            continue
        assert item.exports == ()
        assert item.children == ()
        assert item.parent == ""


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash() -> None:
    graph = read_graph(EXAMPLE / "nowhere")

    assert graph.ok is False
    assert graph.nodes == ()
    assert "no project" in graph.detail


# -- edges -----------------------------------------------------------------------------


def test_the_agent_rag_edge_exists_because_of_one_import() -> None:
    """`agent/tools.py` does `from rag import search`. That import is the whole edge."""
    assert ("agent", "rag", "import") in edges(read_graph(EXAMPLE))


def test_removing_the_import_removes_the_edge(tmp_path: Path) -> None:
    """The projection, proven in one step: change the code, the graph follows.

    Nothing is invalidated, nothing is migrated, and no stored edge has to be found and
    deleted -- because there was never anywhere for one to be stored.
    """
    root = project(tmp_path)
    assert ("agent", "rag", "import") in edges(read_graph(root))

    (root / "agent" / "tools.py").write_text(
        "def look_up(query: str, passages: int) -> list[str]:\n    return []\n",
        encoding="utf-8",
    )

    assert ("agent", "rag", "import") not in edges(read_graph(root))


def test_a_relative_import_states_the_same_fact_as_an_absolute_one(tmp_path: Path) -> None:
    """`from ..rag import search` is the same dependency, written differently."""
    root = project(tmp_path)
    (root / "agent" / "tools.py").write_text(
        "from ..rag import search\n\n\ndef look_up(q: str, n: int) -> list[str]:\n"
        "    return [c.text for c in search(q, top_k=n)]\n",
        encoding="utf-8",
    )

    assert ("agent", "rag", "import") in edges(read_graph(root))


def test_a_package_importing_itself_is_not_an_edge() -> None:
    """`agent/__init__.py` reads `agent.tools`. That is its own internals, not a relation."""
    for edge in read_graph(EXAMPLE).edges:
        assert edge.source != edge.target


def test_mcp_servers_are_edges_from_the_agent_to_the_file_that_configures_them() -> None:
    """One edge per configured server. The servers themselves are not nodes.

    They are somebody else's process reached over a protocol; the project's fact about them
    is the file, so that is where the edges land -- each carrying the server's name.
    """
    graph = read_graph(EXAMPLE)
    mcp = [edge for edge in graph.edges if edge.kind == "mcp"]

    assert [(edge.source, edge.target, edge.label) for edge in mcp] == [
        ("agent", "mcp.json", "filesystem")
    ]


def test_an_unreadable_mcp_file_costs_the_edges_and_nothing_else(tmp_path: Path) -> None:
    """A person edits this file by hand. A trailing comma must not stop the graph."""
    root = project(tmp_path)
    (root / "mcp.json").write_text("{ not json", encoding="utf-8")

    graph = read_graph(root)

    assert graph.ok is True
    assert [edge for edge in graph.edges if edge.kind == "mcp"] == []
    assert "mcp.json" in ids(graph, "file")


# -- a directory that is not a node, and one that is broken ------------------------------


def test_renaming_a_system_makes_it_disappear_rather_than_fail(tmp_path: Path) -> None:
    """A directory not in the table is ordinary code. Not an error, not a warning."""
    root = project(tmp_path)
    (root / "rag").rename(root / "rag_old")

    graph = read_graph(root)

    assert graph.ok is True
    assert "rag" not in ids(graph, "system")
    assert "rag_old" not in ids(graph, "system")
    # And the edge that pointed at it goes with it, because the import now names nothing.
    assert ("agent", "rag", "import") not in edges(graph)


def test_a_missing_export_is_an_incomplete_node_and_names_what_is_missing(
    tmp_path: Path,
) -> None:
    """Never guessed at. The node is drawn, and it says which half of the contract is absent."""
    root = project(tmp_path)
    init = root / "rag" / "__init__.py"
    init.write_text(
        init.read_text(encoding="utf-8").replace(
            "def index(paths: list[str]) -> None:", "def fill(paths: list[str]) -> None:"
        ),
        encoding="utf-8",
    )

    rag = node(read_graph(root), "rag")

    assert rag.complete is False
    assert rag.missing == ("index",)
    assert "index" in rag.reason


def test_a_system_directory_with_no_init_is_incomplete_not_absent(tmp_path: Path) -> None:
    """It is the state a half-written package is in, and hiding it hides the way out of it."""
    root = project(tmp_path)
    (root / "rag" / "__init__.py").unlink()

    rag = node(read_graph(root), "rag")

    assert rag.complete is False
    assert rag.missing == ("index", "search")


def test_a_package_that_cannot_be_parsed_is_incomplete_and_not_a_crash(tmp_path: Path) -> None:
    """Half-typed code is the ordinary state of code. The rest of the graph still draws."""
    root = project(tmp_path)
    (root / "rag" / "__init__.py").write_text("def search(  :::\n", encoding="utf-8")

    graph = read_graph(root)

    assert graph.ok is True
    assert node(graph, "rag").complete is False
    assert node(graph, "api").complete is True


def test_an_export_may_arrive_by_any_binding(tmp_path: Path) -> None:
    """A re-export, an assignment and a def are the same fact: the name is there.

    The contract is the symbol, not how it came to exist -- which is what lets a package be
    rewritten onto a different stack without becoming a different node.
    """
    root = project(tmp_path)
    (root / "agent" / "__init__.py").write_text(
        "from agent.tools import look_up as run\n", encoding="utf-8"
    )
    assert node(read_graph(root), "agent").complete is True

    (root / "agent" / "__init__.py").write_text("run = lambda m, **kw: m\n", encoding="utf-8")
    assert node(read_graph(root), "agent").complete is True


def test_a_name_bound_only_under_type_checking_is_not_an_export(tmp_path: Path) -> None:
    """It does not exist at runtime, and a parser that credited it would be guessing.

    The same rule covers `try/except ImportError`: which branch ran is a question only
    running the code can answer, and this never runs anything.
    """
    root = project(tmp_path)
    (root / "agent" / "__init__.py").write_text(
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from agent.tools import run\n",
        encoding="utf-8",
    )

    assert node(read_graph(root), "agent").complete is False


# -- one level of nesting ----------------------------------------------------------------


def child(root: Path, name: str, body: str = "") -> None:
    """Write `agent/agents/<name>/` as a node, plus whatever else the test needs."""
    package = root / "agent" / "agents" / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"from agent.agents.{name}.work import run\n\n__all__ = ['run']\n", encoding="utf-8"
    )
    (package / "work.py").write_text(
        body or "def run(message: str, **kw: object) -> str:\n    return message\n",
        encoding="utf-8",
    )


def test_a_child_appears_under_its_parent_and_the_count_moves(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert node(read_graph(root), "agent").children == ()

    child(root, "researcher")

    graph = read_graph(root)
    assert node(graph, "agent").children == ("agent.researcher",)
    assert node(graph, "agent.researcher").parent == "agent"
    assert node(graph, "agent.researcher").kind == "agent"


def test_a_child_gets_its_own_edges(tmp_path: Path) -> None:
    """The same rule one level down, including the one that draws the lines."""
    root = project(tmp_path)
    child(root, "researcher")
    (root / "agent" / "agents" / "researcher" / "tools.py").write_text(
        "from rag import search\n\n\ndef look(q: str) -> list[object]:\n    return search(q)\n",
        encoding="utf-8",
    )

    assert ("agent.researcher", "rag", "import") in edges(read_graph(root))


def test_a_parent_does_not_own_its_children_s_files(tmp_path: Path) -> None:
    """Listed once, under the node they belong to. Twice would make the parent look bigger."""
    root = project(tmp_path)
    child(root, "researcher")

    graph = read_graph(root)
    parent_files = node(graph, "agent").files

    assert "agent/tools.py" in parent_files
    assert not any(item.startswith("agent/agents/") for item in parent_files)
    assert "agent/agents/researcher/work.py" in node(graph, "agent.researcher").files


def test_a_third_level_produces_no_nodes_and_no_error(tmp_path: Path) -> None:
    """Only one level is recognised. Deeper is ordinary code, and silence is the answer."""
    root = project(tmp_path)
    child(root, "researcher")
    deeper = root / "agent" / "agents" / "researcher" / "agents" / "assistant"
    deeper.mkdir(parents=True)
    (deeper / "__init__.py").write_text(
        "def run(message: str, **kw: object) -> str:\n    return message\n", encoding="utf-8"
    )

    graph = read_graph(root)

    assert graph.ok is True
    assert not any(item.id.endswith(".assistant") for item in graph.nodes)
    assert node(graph, "agent.researcher").children == ()


def test_a_directory_in_the_nest_that_is_not_a_package_is_not_a_node(tmp_path: Path) -> None:
    """In here the name is the author's, so the signal is being a package -- nothing else."""
    root = project(tmp_path)
    plain = root / "agent" / "agents" / "notes"
    plain.mkdir(parents=True)
    (plain / "readme.md").write_text("not a package\n", encoding="utf-8")

    assert node(read_graph(root), "agent").children == ()


def test_a_child_missing_its_export_is_incomplete_rather_than_absent(tmp_path: Path) -> None:
    root = project(tmp_path)
    package = root / "agent" / "agents" / "half"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("PLANNED = True\n", encoding="utf-8")

    half = node(read_graph(root), "agent.half")

    assert half.complete is False
    assert half.missing == ("run",)


# -- the payload, and what it costs ------------------------------------------------------


def test_the_payload_matches_the_declared_contract() -> None:
    """Strictly, in both directions: an undeclared field fails as loudly as a missing one."""
    validate(wire_form(graph_get(EXAMPLE)), GRAPH_SCHEMA)


def test_a_refusal_matches_the_same_contract(tmp_path: Path) -> None:
    validate(wire_form(graph_get(tmp_path / "nowhere")), GRAPH_SCHEMA)


def test_reading_the_reference_twice_gives_the_same_answer() -> None:
    """Determinism (I-2), stated as the cheapest possible test.

    The graph is a function of the tree and the imports in it. If two reads of an unchanged
    project ever differ, something in here is reading the filesystem's ordering as meaning.
    """
    first = wire_form(graph_get(EXAMPLE))
    second = wire_form(graph_get(EXAMPLE))

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_reading_the_reference_is_under_500ms() -> None:
    """The acceptance number. A parse a person waits for is a parse they stop asking for."""
    started = time.perf_counter()
    read_graph(EXAMPLE)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"{elapsed:.3f}s"
