"""The graph snapshot: the outline of the last state that passed the gates.

Read §8 before changing anything here, because the two temptations this file resists are
both reasonable-sounding.

**It is a reference, never a source.** The graph is always rebuilt from code (I-1). The
snapshot exists only to be diffed against, and nothing may ever read a fact *out* of it to
draw or decide with. The moment something does, there are two stores of state and they can
disagree — which is the failure mode the whole product is arranged to avoid.

**It stores the outline, not the code.** Boundaries, carriers, locked signatures, declared
knobs, membership, contract edges — and, for generated functions only, a structural digest
of the body. Editable bodies are absent by design: their internals belong to the user (§4),
so changing a variable inside one must raise nothing at all, and the only way to guarantee
that is to have nothing to compare.

There is deliberately no file watcher (§8). The question worth answering is "is it still
valid", not "did something change" — a watcher fires on formatters, `git checkout`, branch
switches and IDE auto-imports, and drowns the real signal in noise.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aibuilder_core.ir import Graph

__all__ = [
    "SNAPSHOT_PATH",
    "SNAPSHOT_VERSION",
    "FunctionOutline",
    "NodeOutline",
    "Snapshot",
    "load_snapshot",
    "save_snapshot",
    "snapshot_path",
    "take_snapshot",
]

#: Bumped when the outline's shape changes. An older snapshot is discarded rather than
#: guessed at: a wrong reference produces confident, wrong divergences.
SNAPSHOT_VERSION = 2

#: Where the reference lives, relative to the project root. A build artifact, like a lock
#: file for a state rather than for dependencies -- safe to delete, and the next successful
#: gate run writes it again.
SNAPSHOT_PATH = Path(".aibuilder") / "snapshot.json"


@dataclass(frozen=True)
class KnobOutline:
    """A knob as the snapshot remembers it -- including the value the graph wrote."""

    name: str
    type: str
    default: str | None
    widget: str | None
    choices: tuple[str, ...] | None


@dataclass(frozen=True)
class NodeOutline:
    id: str
    kind: str
    carrier: str
    carrier_type: str
    title: str | None
    zone: str | None
    signature: str | None
    knobs: tuple[KnobOutline, ...]
    members: tuple[str, ...]


@dataclass(frozen=True)
class FunctionOutline:
    path: str
    zone: str | None
    signature: str
    signature_locked: bool
    #: Present for generated bodies only. See `ir.Function.body_digest`.
    body_digest: str | None
    #: The generated body's source, kept so a revert has something to revert *to*.
    #:
    #: This is the one place the reference holds code rather than outline, and it is the
    #: narrowest form that makes §9 case 2 honest: without it, "revert to the last working
    #: state" would be an option the tool could offer and not perform. Editable bodies stay
    #: absent -- they are the user's, and nothing may reconstruct them from a reference.
    body_source: str | None


@dataclass(frozen=True)
class EdgeOutline:
    source: str
    target: str
    contract: str


@dataclass(frozen=True)
class Snapshot:
    """The structural outline of one valid graph state."""

    version: int
    nodes: tuple[NodeOutline, ...] = ()
    functions: tuple[FunctionOutline, ...] = ()
    edges: tuple[EdgeOutline, ...] = ()

    def node(self, node_id: str) -> NodeOutline | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def function(self, path: str) -> FunctionOutline | None:
        return next((function for function in self.functions if function.path == path), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def take_snapshot(graph: Graph) -> Snapshot:
    """Reduce a graph to the outline worth remembering.

    Everything dropped here is dropped on purpose. Locations are not kept: a node that
    moved down a file has not diverged, and remembering where it used to be would turn
    every insertion above it into a false divergence.
    """
    return Snapshot(
        version=SNAPSHOT_VERSION,
        nodes=tuple(
            NodeOutline(
                id=node.id,
                kind=node.kind,
                carrier=node.carrier,
                carrier_type=node.carrier_type,
                title=node.title,
                zone=node.zone,
                signature=node.signature.render() if node.signature else None,
                knobs=tuple(
                    KnobOutline(
                        name=knob.name,
                        type=knob.type,
                        default=knob.default,
                        widget=knob.widget,
                        choices=knob.choices,
                    )
                    for knob in node.knobs
                ),
                members=node.members,
            )
            for node in graph.nodes
        ),
        functions=tuple(
            FunctionOutline(
                path=function.path,
                zone=function.zone,
                signature=function.signature.render(),
                signature_locked=function.signature_locked,
                body_digest=function.body_digest,
                body_source=function.body_source,
            )
            for function in graph.functions
        ),
        edges=tuple(
            EdgeOutline(source=edge.source, target=edge.target, contract=edge.contract)
            for edge in graph.edges
        ),
    )


def snapshot_path(project: Path | str) -> Path:
    return Path(project) / SNAPSHOT_PATH


def save_snapshot(snapshot: Snapshot, project: Path | str) -> Path:
    path = snapshot_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_snapshot(project: Path | str) -> Snapshot | None:
    """The stored reference, or None when there is none to compare against.

    A snapshot from an older version is treated as absent rather than migrated. There is
    nothing to lose by re-taking one from a state that passes the gates, and everything to
    lose by diffing against a reference whose meaning has shifted.
    """
    path = snapshot_path(project)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    if payload.get("version") != SNAPSHOT_VERSION:
        return None

    return Snapshot(
        version=payload["version"],
        nodes=tuple(
            NodeOutline(
                id=node["id"],
                kind=node["kind"],
                carrier=node["carrier"],
                carrier_type=node["carrier_type"],
                title=node["title"],
                zone=node["zone"],
                signature=node["signature"],
                knobs=tuple(
                    KnobOutline(
                        name=knob["name"],
                        type=knob["type"],
                        default=knob["default"],
                        widget=knob["widget"],
                        choices=tuple(knob["choices"]) if knob["choices"] else None,
                    )
                    for knob in node["knobs"]
                ),
                members=tuple(node["members"]),
            )
            for node in payload["nodes"]
        ),
        functions=tuple(
            FunctionOutline(
                path=function["path"],
                zone=function["zone"],
                signature=function["signature"],
                signature_locked=function["signature_locked"],
                body_digest=function["body_digest"],
                body_source=function["body_source"],
            )
            for function in payload["functions"]
        ),
        edges=tuple(
            EdgeOutline(source=edge["source"], target=edge["target"], contract=edge["contract"])
            for edge in payload["edges"]
        ),
    )
