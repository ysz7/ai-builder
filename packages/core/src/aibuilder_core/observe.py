"""Running the observable checks, from outside the project.

This side builds the plan and reads the answers. The checks themselves run in `probe.py`,
in a **separate process**, and that separation is not tidiness: the probe imports the
user's code, and imported code can raise on import, block on a socket, exhaust memory or
call `sys.exit`. A crash there must cost a subprocess, never the core the UI is talking to.

What comes back is deliberately three-valued. `passed` and `failed` are evidence; anything
a check could not run is **skipped**, which leaves the node unproven rather than green.
Turning "could not check" into "fine" is precisely the erosion I-5 is written against, and
it is the erosion that would be easiest to introduce here, one convenience at a time.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from aibuilder_core.ir import Graph
from aibuilder_core.kinds import lookup
from aibuilder_core.verdict import Observation

__all__ = ["ObservationRun", "run_observations"]

#: How long the whole probe may take. A project that hangs is a failing project, and the
#: runner has to come back to say so.
DEFAULT_TIMEOUT_S = 120


@dataclass(frozen=True)
class ObservationRun:
    """Evidence gathered, and the reasons for everything that stayed unproven."""

    observations: dict[str, Observation] = field(default_factory=dict)
    #: node id -> why its check did not run. Never an absence of information.
    skipped: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
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


def build_plan(graph: Graph, project: Path) -> dict[str, object]:
    """What the probe is asked to import and check.

    Only the modules the graph already knows about are imported -- the ones that carry a
    node or a classified function. A project's untouched corners stay untouched, and the
    blast radius of running a stranger's code is the part they annotated for us.
    """
    carriers = {node.id: node.carrier for node in graph.nodes}

    modules = {
        _module_of(location.file)
        for location in [node.location for node in graph.nodes]
        + [function.location for function in graph.functions]
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
    }


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
) -> ObservationRun:
    """Run every node's observable check and return what could be proven."""
    project = Path(project)
    plan = build_plan(graph, project)
    if not plan["nodes"]:
        return ObservationRun()

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "aibuilder_core.probe"],
            input=json.dumps(plan),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _all_failed(plan, f"the checks did not finish within {timeout_s}s")

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return _all_failed(
            plan, f"the checker exited {completed.returncode}: {detail[-1] if detail else ''}"
        )

    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return _all_failed(plan, "the checker produced no readable result")

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

    return ObservationRun(observations=observations, skipped=skipped)


def _all_failed(plan: dict[str, object], detail: str) -> ObservationRun:
    """Nothing could be proven, and the reason is the same for every node."""
    nodes: list[dict[str, str]] = plan["nodes"]  # type: ignore[assignment]
    return ObservationRun(
        observations={
            node["id"]: Observation(passed=False, check=node["check"], detail=detail)
            for node in nodes
        }
    )
