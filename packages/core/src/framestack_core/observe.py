"""Running the observable checks, from outside the project.

This side builds the plan and reads the answers. The checks themselves run in `probe.py`,
in a **separate process**, and that separation is not tidiness: the probe imports the
user's code, and imported code can raise on import, block on a socket, exhaust memory or
call `sys.exit`. A crash there must cost a subprocess, never the core the UI is talking to.

What comes back is deliberately three-valued. `passed` and `failed` are evidence; anything
a check could not run is **skipped**, which leaves the node unproven rather than green.
Turning "could not check" into "fine" is precisely the erosion I-5 is written against, and
it is the erosion that would be easiest to introduce here, one convenience at a time.

The plan names the project's test suite when it has one, because that suite is the run the
graph observes (Q7). Which evidence then counts for which node is decided in `probe.py`,
once -- this side only says where the tests are.

**The probe is spawned with the project's own interpreter** (P11), which is possible only
because the probe imports nothing from this package: it is handed to that interpreter as a
plain file, and a project's virtual environment has no `framestack_core` in it. The rule that
looked like tidiness in P4 is what makes the environment work at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from framestack_core.converse import conversations_held
from framestack_core.environment import Environment, describe_environment
from framestack_core.ir import Graph
from framestack_core.kinds import REGISTRY, CarrierType, lookup, technology_of
from framestack_core.markup import GROUP_MANIFEST
from framestack_core.paths import iter_python_files, module_name
from framestack_core.runner import check_artifacts
from framestack_core.verdict import Observation

__all__ = [
    "ObservationRun",
    "probe_script",
    "project_modules",
    "run_observations",
    "tests_path",
]

#: How long the whole probe may take -- the project's own test suite included, since P9.
#: A project that hangs is a failing project, and the runner has to come back to say so.
DEFAULT_TIMEOUT_S = 120

#: Where a project keeps its tests. Convention, not configuration: this is what a Python
#: project does, and a project that does something else is one whose nodes fall back to
#: the direct checks -- a smaller claim, not a wrong one.
TESTS_DIRECTORY = "tests"


@dataclass(frozen=True)
class ObservationRun:
    """Evidence gathered, and the reasons for everything that stayed unproven."""

    observations: dict[str, Observation] = field(default_factory=dict)
    #: node id -> why its check did not run. Never an absence of information.
    skipped: dict[str, str] = field(default_factory=dict)
    #: The environment the run happened in. Travels with the evidence, because evidence
    #: from an environment nobody described is evidence about nothing in particular.
    environment: Environment | None = None
    #: What the graph left out (Q12): `state` is `proven` only when every completeness
    #: probe could actually ask its library, and `undeclared` names each carrier the
    #: libraries hold that no node declares -- with an address, like every diagnostic.
    completeness: dict[str, object] = field(
        default_factory=lambda: {"state": "unproven", "detail": "nothing was run", "undeclared": []}
    )
    #: The flow this run revealed (Q9): `observed` where a passing test went from one node
    #: to the next, `wiring` where the framework itself holds the edge. Empty before a run,
    #: which is the honest state -- a path nothing took is dark, as it is in Unreal.
    flow: tuple[dict[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "completeness": dict(self.completeness),
            "environment": None if self.environment is None else self.environment.as_dict(),
            "flow": [dict(edge) for edge in self.flow],
            "observations": {
                node: {
                    "passed": observation.passed,
                    "check": observation.check,
                    "detail": observation.detail,
                }
                for node, observation in self.observations.items()
            },
            "skipped": dict(self.skipped),
        }


def probe_script() -> Path:
    """The probe, as a file another interpreter can be handed.

    By path, never by import: importing it here would run the module that imports the
    user's project, in the process the UI is talking to. Frozen, it travels as bundled data
    beside the package, for the same reason the prompt does.
    """
    beside = Path(__file__).resolve().with_name("probe.py")
    if beside.is_file():
        return beside

    bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidate = bundled / "framestack_core" / "probe.py"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"the probe is missing at {beside}")


def build_plan(
    graph: Graph, project: Path, environment: Environment | None = None
) -> dict[str, object]:
    """What the probe is asked to import and check.

    Only the modules the graph already knows about are imported -- the ones that carry a
    node or a classified function. A project's untouched corners stay untouched, and the
    blast radius of running a stranger's code is the part they annotated for us.
    """
    carriers = {node.id: node.carrier for node in graph.nodes}

    # Group manifests are left out on purpose. A `__node__.py` is markup and nothing else
    # -- the strip deletes it -- so a plan that imported one could only ever run against
    # annotated code, and the claim that the stripped copy proves the same things would be
    # untestable (I-2). Nothing is lost: the manifest declares members it imports from the
    # modules already in this set.
    # Artifact nodes are left out here as well as below: a compose file is not a module,
    # and importing "compose" would fail the whole run for every node in it.
    modules = {
        _module_of(location.file)
        for location in [
            node.location for node in graph.nodes if node.carrier_type != CarrierType.FILE.value
        ]
        + [function.location for function in graph.functions]
        if Path(location.file).name != GROUP_MANIFEST
    }

    nodes = []
    for node in graph.nodes:
        if node.carrier_type == CarrierType.FILE.value:
            # A file carries no Python object, so there is nothing here for the probe to
            # import or call. Artifact checks run on the toolchain's side (`runner.py`).
            continue
        kind = lookup(node.kind)
        if kind is None:
            continue  # an unregistered kind has no check; the gate already said so
        nodes.append(
            {
                "id": node.id,
                "kind": node.kind,
                "check": kind.check,
                "carrier": node.carrier,
                "carrier_type": node.carrier_type,
                "member_carriers": [
                    carriers[member] for member in node.members if member in carriers
                ],
            }
        )

    return {
        "project": str(project.resolve()),
        "modules": sorted(name for name in modules if name),
        # Every module, annotated or not (Q12). The completeness rule exists for the file
        # with no markup in it, so a plan that named only the annotated ones could never
        # find one -- and these are imported leniently, after everything else, so a corner
        # of the project the graph knows nothing about cannot redden a node.
        "all_modules": project_modules(project),
        # The kinds that opted in to being asked "is everything here on the graph?". A list
        # rather than a flag, so a kind joins the rule by naming a probe in the registry.
        "completeness": sorted(
            {kind.completeness for kind in REGISTRY.values() if kind.completeness}
        ),
        "nodes": nodes,
        # What a person already proved by talking to a node (P17.4). Handed over as a fact
        # about what was said, never as a verdict: which evidence wins is decided in
        # `probe.run_plan` and nowhere else, so this side reads the transcript and stops.
        "conversations": conversations_held(project),
        "tests": tests_path(project),
        # What the run is happening in. The probe needs it to know when a failing test
        # cannot be attributed to the node that failed it.
        "environment": {} if environment is None else environment.as_dict(),
        # Only the technologies this graph actually uses, and only those whose checks read
        # library internals. The probe compares them with what is installed *there* -- it
        # is the process that has the project's world in front of it.
        "technologies": {
            technology.name: {
                "distribution": technology.distribution,
                "verified": technology.verified,
            }
            for node in graph.nodes
            if (technology := technology_of(node.kind)) is not None
        },
    }


def project_modules(project: Path) -> list[str]:
    """Every importable module of the **application**, for the completeness claim (Q12).

    Three exclusions, and each is a rule rather than a convenience. A group manifest is
    markup and nothing else -- the strip deletes it -- so importing one would make the
    annotated copy behave differently from the stripped one, which is what I-2 forbids. The
    test suite is not the application, and it is run separately anyway. And `__main__` is
    the module whose whole purpose is to *start* something: importing it to ask a question
    would start a server on the way past, which is precisely what P11 exists to prevent.
    """
    root = project.resolve()
    skip = {GROUP_MANIFEST, "conftest.py", "__main__.py"}
    return sorted(
        name
        for path in iter_python_files(root)
        if path.name not in skip
        and TESTS_DIRECTORY not in path.relative_to(root).parts
        and (name := module_name(path, root))
    )


def tests_path(project: Path) -> str:
    """The project's own test suite, if it has one where a Python project keeps it.

    An empty string means "no suite", and the probe says so in the reason it gives for
    every node the direct checks could not prove. Absence of tests is a fact about the
    project worth reporting, not a condition to work around.
    """
    tests = project.resolve() / TESTS_DIRECTORY
    if tests.is_dir() and any(tests.rglob("test_*.py")):
        return str(tests)
    return ""


def _module_of(relative_file: str) -> str:
    parts = Path(relative_file).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def run_observations(
    graph: Graph,
    project: Path | str,
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    python: str | None = None,
) -> ObservationRun:
    """Run every node's observable check and return what could be proven.

    Reads the environment; never changes it. If the project declares services and they are
    not running, that fact travels into the plan and comes back in the reasons -- it does
    not cause anything to be started (P11).
    """
    project = Path(project)
    environment = describe_environment(project, python)
    plan = build_plan(graph, project, environment)
    artifacts = check_artifacts(graph, project, environment)
    if not plan["nodes"]:
        # No Python node means nothing to import, so nothing was asked and completeness
        # keeps its honest default: unproven, with the reason.
        return ObservationRun(
            observations=dict(artifacts.observations),
            skipped=dict(artifacts.skipped),
            environment=environment,
            flow=tuple(artifacts.flow),
        )

    try:
        completed = subprocess.run(
            # The project's interpreter, and the probe as a plain file -- see `probe_script`.
            [environment.interpreter, str(probe_script())],
            input=json.dumps(plan),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _all_failed(plan, f"the checks did not finish within {timeout_s}s", environment)

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return _all_failed(
            plan,
            f"the checker exited {completed.returncode}: {detail[-1] if detail else ''}",
            environment,
        )

    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return _all_failed(plan, "the checker produced no readable result", environment)

    observations: dict[str, Observation] = {}
    skipped: dict[str, str] = {}
    flow = tuple(
        {str(key): str(value) for key, value in edge.items()}
        for edge in payload.get("flow", [])
        if isinstance(edge, dict)
    )

    for result in payload.get("results", []):
        if result["status"] == "skipped":
            skipped[result["node"]] = result["detail"]
        else:
            observations[result["node"]] = Observation(
                passed=result["status"] == "passed",
                check=result["check"],
                detail=result["detail"],
            )

    # The artifact nodes' answers join the probe's. Two runners, one set of evidence --
    # and no node is ever looked at by both. Their flow joins it too: an edge a compose file
    # holds is the same kind of fact as an edge a compiled graph holds, and the canvas has
    # one place to draw both.
    observations.update(artifacts.observations)
    skipped.update(artifacts.skipped)
    flow = (*flow, *artifacts.flow)

    completeness = payload.get("completeness")
    return ObservationRun(
        observations=observations,
        skipped=skipped,
        environment=environment,
        flow=flow,
        completeness=(
            dict(completeness)
            if isinstance(completeness, dict)
            else {
                "state": "unproven",
                "detail": "the checker said nothing about it",
                "undeclared": [],
            }
        ),
    )


def _all_failed(
    plan: dict[str, object], detail: str, environment: Environment | None = None
) -> ObservationRun:
    """Nothing could be proven, and the reason is the same for every node."""
    nodes: list[dict[str, str]] = plan["nodes"]  # type: ignore[assignment]
    return ObservationRun(
        observations={
            node["id"]: Observation(passed=False, check=node["check"], detail=detail)
            for node in nodes
        },
        environment=environment,
    )
