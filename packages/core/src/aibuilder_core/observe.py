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
plain file, and a project's virtual environment has no `aibuilder_core` in it. The rule that
looked like tidiness in P4 is what makes the environment work at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from aibuilder_core.environment import Environment, describe_environment
from aibuilder_core.ir import Graph
from aibuilder_core.kinds import lookup, technology_of
from aibuilder_core.markup import GROUP_MANIFEST
from aibuilder_core.verdict import Observation

__all__ = ["ObservationRun", "probe_script", "run_observations", "tests_path"]

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

    def as_dict(self) -> dict[str, object]:
        return {
            "environment": None if self.environment is None else self.environment.as_dict(),
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
    candidate = bundled / "aibuilder_core" / "probe.py"
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
    modules = {
        _module_of(location.file)
        for location in [node.location for node in graph.nodes]
        + [function.location for function in graph.functions]
        if Path(location.file).name != GROUP_MANIFEST
    }

    nodes = []
    for node in graph.nodes:
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
        "nodes": nodes,
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
    if not plan["nodes"]:
        return ObservationRun(environment=environment)

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

    for result in payload.get("results", []):
        if result["status"] == "skipped":
            skipped[result["node"]] = result["detail"]
        else:
            observations[result["node"]] = Observation(
                passed=result["status"] == "passed",
                check=result["check"],
                detail=result["detail"],
            )

    return ObservationRun(observations=observations, skipped=skipped, environment=environment)


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
