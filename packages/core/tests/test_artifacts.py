"""Nodes carried by a file, and the machinery that keeps them from costing anything (P12).

A `Dockerfile` declares nothing and is still part of the project. Making it a node amended
I-3 to admit a second species of carrier (Q10), and the amendment is only safe because of
what did **not** change with it:

* the parser still reads Python and knows no file format — a separate reader finds these,
  and composition happens in one place above both (§5.7);
* nothing is parsed: what the compose file says is asked of docker, and whether a service is
  usable is answered by connecting to its port (§5.8);
* nothing is generated: the file stays the source of truth about itself;
* a check never starts anything, so a compose file whose services are down is an *unproven*
  node that names the button, not a red one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aibuilder_core.artifacts import read_artifacts
from aibuilder_core.environment import Environment, Service
from aibuilder_core.gate import check_graph
from aibuilder_core.ir import Location, Node
from aibuilder_core.kinds import REGISTRY, CarrierType
from aibuilder_core.parser import parse_project
from aibuilder_core.project import read_project
from aibuilder_core.runner import artifact_nodes, check_artifacts
from aibuilder_core.verdict import Verdict

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
CACHED = EXAMPLES / "service-with-cache"
PLAIN = EXAMPLES / "fastapi-service"


def project_with(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


# -- discovery --------------------------------------------------------------------


def test_a_declared_path_becomes_a_node(tmp_path: Path) -> None:
    root = project_with(tmp_path, {"Dockerfile": "FROM python:3.12-slim\n"})

    nodes = read_artifacts(root)

    assert [node.id for node in nodes] == ["Dockerfile"]
    assert nodes[0].kind == "docker.image"
    assert nodes[0].carrier_type == CarrierType.FILE.value


def test_identity_is_the_path_because_a_file_declares_nothing(tmp_path: Path) -> None:
    """A Python node's id is stated in code; a file has only where it is."""
    root = project_with(tmp_path, {"compose.yaml": "services: {}\n"})

    node = read_artifacts(root)[0]

    assert node.id == node.carrier == "compose.yaml"
    assert node.location.file == "compose.yaml"
    assert node.location.start_line == 1


def test_an_undeclared_file_is_not_a_node(tmp_path: Path) -> None:
    """There is no rule that says a familiar-looking name becomes a node."""
    root = project_with(tmp_path, {"Makefile": "all:\n", "deploy.sh": "echo\n"})

    assert read_artifacts(root) == ()


def test_one_node_per_kind_even_when_two_candidates_exist(tmp_path: Path) -> None:
    """Docker reads one of them and ignores the other; two nodes would be a fiction."""
    root = project_with(
        tmp_path, {"compose.yaml": "services: {}\n", "docker-compose.yml": "services: {}\n"}
    )

    nodes = read_artifacts(root)

    assert [node.id for node in nodes] == ["compose.yaml"]


def test_nothing_is_read_out_of_the_file(tmp_path: Path) -> None:
    """A file we cannot even decode still has a node and an address (§5.8).

    The reader counts the file's extent and stops. Everything about what is *inside* is
    asked of the tool that owns the format.
    """
    root = tmp_path
    (root / "Dockerfile").write_bytes(b"\xff\xfe not text at all \x00\n")

    node = read_artifacts(root)[0]

    assert node.id == "Dockerfile"
    assert node.location.end_line >= 1


# -- composition ------------------------------------------------------------------


def test_the_parser_never_sees_an_artifact() -> None:
    """The line that has held since P2: `parser.py` reads Python and nothing else."""
    python_only = {node.id for node in parse_project(CACHED).nodes}
    whole = {node.id for node in read_project(CACHED).nodes}

    assert "compose.yaml" not in python_only
    assert "compose.yaml" in whole
    assert python_only < whole


def test_a_declared_node_is_never_displaced_by_an_artifact(tmp_path: Path) -> None:
    """An id collision is a mistake worth a diagnostic, not a silent overwrite."""
    root = project_with(
        tmp_path,
        {
            "Dockerfile": "FROM python:3.12-slim\n",
            "app.py": (
                "from bp import group_node\n\n"
                "service = group_node(id='Dockerfile', kind='fastapi.service', members=[])\n"
            ),
        },
    )

    nodes = read_project(root).nodes
    dockerfile = [node for node in nodes if node.id == "Dockerfile"]

    assert len(dockerfile) == 1
    assert dockerfile[0].carrier_type != CarrierType.FILE.value


def test_a_project_with_no_artifacts_is_untouched() -> None:
    assert read_project(PLAIN).to_dict() == parse_project(PLAIN).to_dict()


# -- the gate ---------------------------------------------------------------------


def test_an_artifact_at_the_top_level_is_not_a_missing_group() -> None:
    """Q4's amendment, held where it is enforced rather than only in prose (§5.7)."""
    diagnostics = check_graph(read_project(CACHED)).diagnostics
    about_compose = [
        diagnostic for diagnostic in diagnostics if diagnostic.location.file == "compose.yaml"
    ]

    assert about_compose == []


def test_every_file_carried_kind_names_its_paths() -> None:
    for kind in REGISTRY.values():
        if CarrierType.FILE in kind.carriers:
            assert kind.artifact
            assert kind.top_level


# -- the checks -------------------------------------------------------------------


def environment(**overrides: object) -> Environment:
    base = {"interpreter": "/x", "interpreter_origin": "toolchain", "compose_file": "compose.yaml"}
    return Environment(**{**base, **overrides})  # type: ignore[arg-type]


def artifact(kind: str, name: str) -> Node:
    return Node(
        id=name,
        kind=kind,
        title=name,
        carrier=name,
        carrier_type=CarrierType.FILE.value,
        location=Location(file=name, object=name, start_line=1, end_line=1),
    )


def graph_of(*nodes: Node) -> object:
    from aibuilder_core.ir import Graph

    return Graph(root=".", nodes=tuple(nodes))


def test_services_that_answer_prove_the_compose_node() -> None:
    run = check_artifacts(
        graph_of(artifact("docker.compose", "compose.yaml")),  # type: ignore[arg-type]
        ".",
        environment(services=(Service(name="db", ports=(5432,), reachable=True),)),
    )

    assert run.observations["compose.yaml"].passed is True


def test_services_that_are_down_leave_it_unproven_and_name_the_button() -> None:
    """Not a failure. The file is fine; the services are simply not up (P11)."""
    run = check_artifacts(
        graph_of(artifact("docker.compose", "compose.yaml")),  # type: ignore[arg-type]
        ".",
        environment(services=(Service(name="db", ports=(5432,), reachable=False),)),
    )

    assert "compose.yaml" not in run.observations
    assert "start them from this node" in run.skipped["compose.yaml"]


def test_a_dockerfile_is_proven_by_something_building_from_it() -> None:
    """The wiring question, the same one route mounting asks."""
    run = check_artifacts(
        graph_of(artifact("docker.image", "Dockerfile")),  # type: ignore[arg-type]
        ".",
        environment(services=(Service(name="api", dockerfile="Dockerfile"),)),
    )

    assert run.observations["Dockerfile"].passed is True


def test_the_relation_between_the_two_docker_nodes_is_drawn(tmp_path: Path) -> None:
    """The arrow the canvas was missing (Q24).

    "built by the service(s): api" was the whole of what tied these two nodes together, and
    it was a sentence in a panel -- so on the canvas a Dockerfile and the compose file that
    builds it looked like two unrelated things near each other. It is **flow, and `wiring`**:
    the compose file holds the edge by declaring it and nothing ran through it, which is the
    same rank as an edge read off a compiled LangGraph. And it appears only after an observe,
    because the only way to know is to ask docker -- no ask, no arrow.
    """
    run = check_artifacts(
        graph_of(
            artifact("docker.image", "Dockerfile"),  # type: ignore[arg-type]
            artifact("docker.compose", "compose.yaml"),  # type: ignore[arg-type]
        ),
        tmp_path,
        environment(services=(Service(name="api", dockerfile="Dockerfile"),)),
    )

    assert run.flow == [{"source": "Dockerfile", "target": "compose.yaml", "origin": "wiring"}]


def test_no_arrow_where_nothing_builds_from_the_file(tmp_path: Path) -> None:
    """The relation is a fact about the compose file, not about the two nodes existing."""
    run = check_artifacts(
        graph_of(
            artifact("docker.image", "Dockerfile"),  # type: ignore[arg-type]
            artifact("docker.compose", "compose.yaml"),  # type: ignore[arg-type]
        ),
        tmp_path,
        environment(services=(Service(name="api", dockerfile=None),)),
    )

    assert run.flow == []


def test_a_dockerfile_nothing_builds_from_is_unproven_not_wrong() -> None:
    """Built by hand or by CI is normal; this project simply has nothing that says so."""
    run = check_artifacts(
        graph_of(artifact("docker.image", "Dockerfile")),  # type: ignore[arg-type]
        ".",
        environment(services=(Service(name="api", dockerfile=None),)),
    )

    assert "no declared service builds" in run.skipped["Dockerfile"]


def test_docker_being_absent_is_the_reason_rather_than_a_verdict() -> None:
    run = check_artifacts(
        graph_of(artifact("docker.compose", "compose.yaml")),  # type: ignore[arg-type]
        ".",
        environment(docker_unavailable="docker is not installed"),
    )

    assert run.observations == {}
    assert run.skipped["compose.yaml"] == "docker is not installed"


def test_the_probe_is_never_told_about_an_artifact() -> None:
    """A file carries no Python object; there is nothing there to import or call."""
    from aibuilder_core.observe import build_plan

    graph = read_project(CACHED)
    plan = build_plan(graph, CACHED)

    assert artifact_nodes(graph)
    assert "compose.yaml" not in [node["id"] for node in plan["nodes"]]  # type: ignore[index]
    assert "compose" not in plan["modules"]  # type: ignore[operator]


# -- end to end, on the example ---------------------------------------------------


def test_the_compose_node_lands_on_the_graph_of_a_real_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(CACHED, root, ignore=shutil.ignore_patterns("__pycache__", ".aibuilder"))

    graph = read_project(root)
    compose = graph.node("compose.yaml")

    assert compose is not None
    assert compose.kind == "docker.compose"
    assert compose.title == "compose.yaml"


@pytest.mark.parametrize("example", ["service-with-cache", "service-with-db"])
def test_a_service_that_is_not_up_costs_nobody_a_red_badge(example: str) -> None:
    """The phase's standing promise, on both projects that declare services.

    Every node is green or unproven; nothing is broken. On a machine with the services down
    -- a laptop, or CI before anyone presses the button -- that is the whole of the truth.
    """
    from aibuilder_core.observe import run_observations

    root = EXAMPLES / example
    graph = read_project(root)
    run = run_observations(graph, root)
    verdicts = check_graph(graph, observations=run.observations).verdicts

    assert Verdict.BROKEN.value not in verdicts.values()
    assert Verdict.GREEN.value in verdicts.values()
