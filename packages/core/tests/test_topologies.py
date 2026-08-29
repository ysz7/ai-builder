"""The topologies that are not a web service: a LangGraph agent, a RAG pipeline (P10), and
an agent with tools and MCP servers (P15).

P9 proved the loop on a service whose nodes are routes. These two exist to prove that what
closed the loop there was the mechanism and not the shape of FastAPI:

* **LangGraph** puts a graph inside the group. The members are a state schema, three step
  functions and a router — none of which is reachable by an HTTP call, and one of which
  (the state) is a type rather than a thing that runs.
* **RAG** puts a pipeline inside the group, and it is the case that forced the group
  construct in the first place (§5.3): four equal stages, no one of which owns the others,
  **each carrying its own knobs**. That last part is what §5.4 promises the user — expand
  the pipeline, tune the stage you are looking at — and this is where it is first true.

* **MCP** puts two subsystems side by side: an agent that consumes a server, and the
  server this project exposes. What each of those is proven by differs on purpose, and
  what the phase is really about lives in `test_tools.py` -- this file only holds it to
  the same loop as the rest.

Each project goes through the same loop as the slice, driven from one parametrised test:
graph, reference, knob written back, deliberate breakage in the generated zone,
reconciliation, repair, green again, and the stripped copy proving the same things.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from framestack_core.api import snapshot_status
from framestack_core.gate import check_graph
from framestack_core.observe import run_observations
from framestack_core.parser import parse_project
from framestack_core.repair import apply_repair
from framestack_core.snapshot import save_snapshot, take_snapshot
from framestack_core.strip import strip_project
from framestack_core.verdict import Verdict
from framestack_core.writer import set_knob

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


@dataclass(frozen=True)
class Topology:
    """One example project, and the moves that exercise its loop."""

    name: str
    group: str
    knob_node: str
    knob: str
    value: int
    #: A hand edit in the generated zone: the file, the text, and what replaces it.
    file: str
    before: str
    after: str
    target: str


TOPOLOGIES = [
    Topology(
        name="langgraph-agent",
        group="agent",
        knob_node="agent.settings",
        knob="max_notes",
        value=5,
        file="agent/graph.py",
        before='{"recursion_limit": settings.recursion_limit}',
        after='{"recursion_limit": 5}',
        target="ask",
    ),
    Topology(
        name="rag-pipeline",
        group="rag",
        knob_node="rag.retrieval",
        knob="top_k",
        value=5,
        file="rag/pipeline.py",
        before="Retriever().find(build_index(), question)",
        after="Retriever().find(build_index(), question.lower())",
        target="answer",
    ),
    Topology(
        name="mcp-agent",
        group="agent",
        # A knob on the consumed server's declaration: the timeout is ours to set, which is
        # exactly the line Q12 draws -- a knob is a syntax node in *this* project's source,
        # and no write of ours reaches into a third party's process.
        knob_node="agent.notes",
        knob="timeout_s",
        value=30,
        file="agent/graph.py",
        before='builder.add_edge("tools", "consult")',
        after='builder.add_edge("tools", END)',
        target="build_graph",
    ),
]


@pytest.fixture(params=TOPOLOGIES, ids=lambda topology: topology.name)
def topology(request: pytest.FixtureRequest) -> Topology:
    return request.param  # type: ignore[no-any-return]


def project(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(
        EXAMPLES / name, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack")
    )
    return root


def verdicts(root: Path) -> dict[str, str]:
    """Parsed **and** proven by a run. There is no other kind of green (I-5)."""
    graph = parse_project(root)
    run = run_observations(graph, root)
    return check_graph(graph, observations=run.observations).verdicts


def test_the_loop_closes_on_this_topology_too(tmp_path: Path, topology: Topology) -> None:
    root = project(tmp_path, topology.name)

    # Green means both conditions, on a topology no HTTP call can reach.
    assert set(verdicts(root).values()) == {Verdict.GREEN.value}

    save_snapshot(take_snapshot(parse_project(root)), root)
    assert snapshot_status(root)["divergences"] == []

    # A knob written back through the syntax tree, into the carrier that owns it.
    assert set_knob(root, topology.knob_node, topology.knob, topology.value).written is True
    assert snapshot_status(root)["divergences"] == []

    # A hand edit in the generated zone, and the reconciliation that notices it.
    edited = root / topology.file
    source = edited.read_text()
    assert topology.before in source, f"{topology.file} no longer contains the text to edit"
    edited.write_text(source.replace(topology.before, topology.after))

    divergences = snapshot_status(root)["divergences"]
    assert [divergence["code"] for divergence in divergences] == ["function.generated_touched"]

    repaired = apply_repair(
        root, code="function.generated_touched", target=topology.target, resolution="revert"
    )
    assert repaired.applied is True
    assert topology.before in edited.read_text()

    # Green again, and the stripped copy proving exactly the same things (I-2).
    assert set(verdicts(root).values()) == {Verdict.GREEN.value}

    stripped = tmp_path / f"{topology.name}-stripped"
    strip_project(root, stripped)
    annotated = run_observations(parse_project(root), root)
    without_markup = run_observations(parse_project(root), stripped)

    assert without_markup.skipped == annotated.skipped == {}
    assert {node: run.passed for node, run in without_markup.observations.items()} == {
        node: run.passed for node, run in annotated.observations.items()
    }


def test_every_node_is_reached_by_a_run(topology: Topology) -> None:
    """The Q7 measurement, on each topology: the unreached band is a number, and it is 0.

    Both of these are technologies where **nothing** could be proven by a call the
    toolchain invents -- a step function takes a state, a retriever takes a question. The
    project's own tests are the whole of the evidence, which is the arrangement Q7 chose.
    """
    root = EXAMPLES / topology.name

    run = run_observations(parse_project(root), root)

    assert run.skipped == {}
    assert all(observation.passed for observation in run.observations.values())


# -- what each topology is supposed to look like ---------------------------------


def test_the_agent_is_a_group_over_its_state_and_steps() -> None:
    graph = parse_project(EXAMPLES / "langgraph-agent")
    agent = graph.node("agent")

    assert agent is not None
    assert agent.kind == "langgraph.agent"
    assert agent.carrier_type == "group"
    assert set(agent.members) == {
        "agent.state",
        "agent.plan",
        "agent.gather",
        "agent.answer",
        "agent.route",
        "agent.settings",
    }
    # The state is a node, not a detail of the assembly: it is what every step shares.
    state = graph.node("agent.state")
    assert state is not None and state.kind == "langgraph.state"


def test_the_router_is_proven_by_being_wired_not_by_being_named() -> None:
    """`graph.branch_registered` asks an identity question, the way route mounting does."""
    root = EXAMPLES / "langgraph-agent"

    run = run_observations(parse_project(root), root)

    assert run.observations["agent.route"].passed is True


def test_the_pipeline_is_a_group_whose_stages_carry_their_own_knobs() -> None:
    """§5.4's promise, first made true here: subnodes with knobs of their own."""
    graph = parse_project(EXAMPLES / "rag-pipeline")
    pipeline = graph.node("rag")

    assert pipeline is not None
    assert pipeline.kind == "rag.pipeline"
    assert pipeline.knobs == ()  # the group holds none; the stages do
    assert list(pipeline.members) == [
        "rag.chunking",
        "rag.embedding",
        "rag.retrieval",
        "rag.generation",
    ]

    knobs = {
        member: {knob.name for knob in node.knobs}
        for member in pipeline.members
        if (node := graph.node(member)) is not None
    }
    assert knobs == {
        "rag.chunking": {"chunk_size", "chunk_overlap"},
        "rag.embedding": {"dimensions"},
        "rag.retrieval": {"top_k", "search_type"},
        "rag.generation": {"max_context_chunks", "tone"},
    }


def test_a_stage_knob_is_written_into_the_stage_that_owns_it(tmp_path: Path) -> None:
    root = project(tmp_path, "rag-pipeline")

    assert set_knob(root, "rag.chunking", "chunk_size", 300).written is True

    assert "= 300" in (root / "rag" / "chunking.py").read_text()
    # And nothing was written into the neighbour that has a similarly shaped field.
    assert "= 300" not in (root / "rag" / "retrieval.py").read_text()


def test_a_reducer_annotation_survives_the_strip(tmp_path: Path) -> None:
    """The strip takes `Param` out of `Annotated` and leaves everyone else's metadata.

    LangGraph puts its reducers there, and they are load-bearing at runtime: a strip that
    removed them would leave a project that imports and then merges state wrongly -- I-2
    broken in the worst way, silently.
    """
    stripped = tmp_path / "stripped"
    strip_project(EXAMPLES / "langgraph-agent", stripped)

    state = (stripped / "agent" / "state.py").read_text()
    settings = (stripped / "agent" / "settings.py").read_text()

    assert "Annotated[list[str], add_steps]" in state
    assert "Param(" not in settings
    assert "max_notes: int = 3" in settings


# -- what the checks were written against ----------------------------------------


def test_the_recorded_version_is_the_one_the_suite_proves() -> None:
    """The number cannot go stale quietly, which is the only thing that makes it worth having.

    `Technology.verified` says "the checks were written against this release". This test
    is what keeps that true: upgrade the dependency and it fails here, so the number is
    updated by whoever moved it rather than discovered to be a lie by a user on a different
    version.
    """
    from framestack_core.kinds import TECHNOLOGIES, installed_version

    drifted = {
        technology.name: (technology.verified, installed_version(technology.distribution))
        for technology in TECHNOLOGIES.values()
        if installed_version(technology.distribution) != technology.verified
    }

    assert drifted == {}


def test_a_technology_is_recorded_only_where_a_check_reads_its_internals() -> None:
    """RAG has no entry on purpose: its checks are plain Python and touch no library.

    The queue does have one: its checks ask celery for a task registry and a beat schedule,
    which is reading someone else's surface however public it is. MCP has one for the same
    reason: the tool *listing* is protocol, but "is this exact function the one exposed?"
    goes through the SDK's own tool manager.

    Recording a version there would be a claim about a dependency our code never looks at
    -- knowledge we do not have, which is precisely what this table is not for.
    """
    from framestack_core.kinds import REGISTRY, TECHNOLOGIES

    prefixes = {kind.partition(".")[0] for kind in REGISTRY}

    assert set(TECHNOLOGIES) == {"fastapi", "langgraph", "queue", "mcp"}
    assert set(TECHNOLOGIES) <= prefixes  # no entry for a technology that does not exist


def test_the_version_note_appears_only_on_a_mismatch() -> None:
    from framestack_core.probe import version_note

    plan = {
        "technologies": {
            "langgraph": {"distribution": "langgraph", "verified": "0.0.1-not-installed"}
        }
    }

    note = version_note(plan, "langgraph.node")

    assert "written against langgraph 0.0.1-not-installed" in note
    assert "is installed" in note


def test_the_version_note_is_silent_when_the_versions_agree() -> None:
    from framestack_core.kinds import TECHNOLOGIES
    from framestack_core.probe import version_note

    langgraph = TECHNOLOGIES["langgraph"]
    plan = {
        "technologies": {
            "langgraph": {"distribution": langgraph.distribution, "verified": langgraph.verified}
        }
    }

    assert version_note(plan, "langgraph.node") == ""
    assert version_note(plan, "rag.chunking") == ""  # no entry, nothing to say


def test_a_proven_node_carries_no_version_footnote() -> None:
    """A green node needs no warning about a problem that demonstrably is not there."""
    run = run_observations(
        parse_project(EXAMPLES / "langgraph-agent"), EXAMPLES / "langgraph-agent"
    )

    assert all(
        "written against" not in observation.detail for observation in run.observations.values()
    )
