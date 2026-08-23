"""Checks for the nodes the probe cannot look at.

`probe.py` is the module that imports the user's project; a `Dockerfile` imports nothing and
a compose file is not Python. Their checks run here instead, in the toolchain's own process,
and the separation is the point: the probe's one dangerous property -- it executes a
stranger's code -- must not spread to a check that only needs to ask docker a question
(architecture §5.7).

Everything in here follows §5.8. Nothing reads a file: what the compose file says is asked
of `docker compose`, and whether a service is usable is answered by connecting to the port
it publishes.

**A check never starts anything.** A compose file whose services are down is not a broken
node -- it is an unproven one, and the reason names the button that would prove it (P11).
"""

from __future__ import annotations

from pathlib import Path

from aibuilder_core.environment import Environment, describe_environment
from aibuilder_core.ir import Graph, Node
from aibuilder_core.kinds import CarrierType, lookup
from aibuilder_core.verdict import Observation

__all__ = ["ArtifactRun", "artifact_nodes", "check_artifacts"]


class ArtifactRun:
    """What could be proven about the artifact nodes, and why the rest could not."""

    def __init__(self) -> None:
        self.observations: dict[str, Observation] = {}
        self.skipped: dict[str, str] = {}

    def passed(self, node: str, check: str, detail: str) -> None:
        self.observations[node] = Observation(passed=True, check=check, detail=detail)

    def failed(self, node: str, check: str, detail: str) -> None:
        self.observations[node] = Observation(passed=False, check=check, detail=detail)

    def skip(self, node: str, detail: str) -> None:
        self.skipped[node] = detail


def artifact_nodes(graph: Graph) -> tuple[Node, ...]:
    """The nodes carried by a file. The probe is never told about these."""
    return tuple(node for node in graph.nodes if node.carrier_type == CarrierType.FILE.value)


def check_artifacts(
    graph: Graph, project: Path | str, environment: Environment | None = None
) -> ArtifactRun:
    """Run each artifact node's check. Reads and asks; changes nothing."""
    run = ArtifactRun()
    nodes = artifact_nodes(graph)
    if not nodes:
        return run

    state = environment or describe_environment(project)

    for node in nodes:
        kind = lookup(node.kind)
        if kind is None:
            continue  # an unregistered kind has no check; the gate already said so
        check = CHECKS.get(kind.check)
        if check is None:
            run.skip(node.id, "no runner for this check yet")
            continue
        check(run, node, state)
    return run


def _services_answer(run: ArtifactRun, node: Node, environment: Environment) -> None:
    """The services this file declares, and whether anything answers where they publish."""
    check = "docker.services_answer"

    if environment.docker_unavailable:
        run.skip(node.id, environment.docker_unavailable)
        return
    if not environment.services:
        run.skip(node.id, "this file declares no services")
        return

    published = [service for service in environment.services if service.ports]
    if not published:
        run.skip(node.id, "no declared service publishes a port, so none can be reached from here")
        return

    missing = environment.services_missing
    if missing:
        # Not a failure: the file is fine and the services are simply not up. The reason
        # names what would prove it, which is the button on this node (P11).
        run.skip(
            node.id,
            f"nothing answers where these services publish: {', '.join(missing)}"
            " -- start them from this node",
        )
        return

    run.passed(node.id, check, f"all {len(published)} declared service(s) answer")


def _image_referenced(run: ArtifactRun, node: Node, environment: Environment) -> None:
    """Is this Dockerfile the one a declared service builds from?

    The wiring question, and the same one route mounting asks: declared is not enough, it
    has to be the file something actually builds. Asked of `docker compose config`, so a
    Dockerfile that is built by hand or by CI is unproven here rather than wrong -- this
    project has nothing that says otherwise.
    """
    check = "docker.image_referenced"

    if environment.docker_unavailable:
        run.skip(node.id, environment.docker_unavailable)
        return

    building = [
        service.name
        for service in environment.services
        if service.dockerfile and Path(service.dockerfile).name == Path(node.carrier).name
    ]
    if not building:
        run.skip(node.id, "no declared service builds from this file")
        return

    run.passed(node.id, check, f"built by the service(s): {', '.join(sorted(building))}")


CHECKS = {
    "docker.services_answer": _services_answer,
    "docker.image_referenced": _image_referenced,
}
