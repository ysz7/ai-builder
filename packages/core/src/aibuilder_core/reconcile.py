"""Reconciliation: what no longer matches the last valid state.

The `git status` model (§8). Not "did something change" — a watcher answers that and
drowns in formatters, branch switches and IDE auto-imports — but "is it still valid",
asked when the project opens and when the user asks.

Every divergence carries a **fault classification**, because §9's two cases need
different handling and the difference is not cosmetic:

* `CONTRACT` — an edit inside an editable zone broke the boundary the neighbours bind to.
  Repairable: the original contract is in the snapshot and the user's body is in the file,
  so the fix restores one without discarding the other.
* `GENERATED` — load-bearing code was edited by hand. **The toolchain does not choose
  here.** It offers both paths and waits. A tool that always reverts will one day erase an
  edit a human needed; a tool that always accepts will one day bless broken code inside a
  green node. Either habit spends the graph's only currency, which is being believed.
* `STRUCTURE` — the shape of the graph moved: a node appeared or vanished, membership or a
  contract edge changed. Usually intentional; always worth showing.

What is *not* here matters as much: nothing compares editable bodies. Changing a variable
inside one raises nothing, and that silence is a promise the product makes (§4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aibuilder_core.ir import Graph, Location
from aibuilder_core.snapshot import NodeOutline, Snapshot

__all__ = ["Divergence", "DivergenceCode", "Fault", "Resolution", "reconcile"]


class Fault(str, Enum):
    CONTRACT = "contract"
    GENERATED = "generated"
    STRUCTURE = "structure"


class Resolution(str, Enum):
    """What may be done about a divergence.

    `REVERT` and `ACCEPT` appear together, never alone: presenting one of them by itself
    would be the silent choice §9 forbids.
    """

    REPAIR = "repair"
    REVERT = "revert"
    ACCEPT = "accept"


class DivergenceCode(str, Enum):
    CARRIER_GONE = "node.carrier_gone"
    NODE_ADDED = "node.added"
    KIND_CHANGED = "node.kind_changed"
    SIGNATURE_BROKEN = "function.signature_broken"
    FUNCTION_GONE = "function.gone"
    GENERATED_TOUCHED = "function.generated_touched"
    ZONE_CHANGED = "function.zone_changed"
    KNOB_CHANGED = "knob.changed"
    MEMBERS_CHANGED = "node.members_changed"
    EDGE_CHANGED = "edge.changed"


@dataclass(frozen=True)
class Entry:
    fault: Fault
    rule: str
    resolutions: tuple[Resolution, ...]
    repair: str


CATALOGUE: dict[DivergenceCode, Entry] = {
    DivergenceCode.CARRIER_GONE: Entry(
        Fault.GENERATED,
        "I-3, §9 case 2",
        (Resolution.REVERT, Resolution.ACCEPT),
        "The node's carrier declaration is gone. Restore the boundary, or accept the "
        "removal and let the node leave the graph.",
    ),
    DivergenceCode.NODE_ADDED: Entry(
        Fault.STRUCTURE,
        "§8",
        (Resolution.ACCEPT,),
        "A node exists that the reference did not have. Usually intended; take a new "
        "snapshot once it passes the gates.",
    ),
    DivergenceCode.KIND_CHANGED: Entry(
        Fault.STRUCTURE,
        "§5.6",
        (Resolution.REVERT, Resolution.ACCEPT),
        "The node's kind changed, so its shape and its observable check changed with it. "
        "Confirm that was meant.",
    ),
    DivergenceCode.SIGNATURE_BROKEN: Entry(
        Fault.CONTRACT,
        "§5.2, §9 case 1",
        (Resolution.REPAIR,),
        "Restore the locked signature from the reference **without discarding the body**. "
        "The signature is the contract the neighbouring nodes bind to; the body is the "
        "user's work.",
    ),
    DivergenceCode.FUNCTION_GONE: Entry(
        Fault.STRUCTURE,
        "§8",
        (Resolution.REVERT, Resolution.ACCEPT),
        "A function the reference knew about is no longer there. Restore it, or accept "
        "the removal.",
    ),
    DivergenceCode.GENERATED_TOUCHED: Entry(
        Fault.GENERATED,
        "§4, §9 case 2",
        (Resolution.REVERT, Resolution.ACCEPT),
        "Generated code was edited by hand. Revert to the reference, or accept the edit "
        "and re-annotate. This choice belongs to the user, not to the toolchain.",
    ),
    DivergenceCode.ZONE_CHANGED: Entry(
        Fault.GENERATED,
        "§4",
        (Resolution.REVERT, Resolution.ACCEPT),
        "A function's classification changed, so what the user is allowed to edit changed "
        "with it. Confirm that was meant.",
    ),
    DivergenceCode.KNOB_CHANGED: Entry(
        Fault.STRUCTURE,
        "§5.5",
        (Resolution.ACCEPT,),
        "A knob's declaration or value differs from the reference. If the graph made the "
        "change this is expected; take a new snapshot.",
    ),
    DivergenceCode.MEMBERS_CHANGED: Entry(
        Fault.STRUCTURE,
        "§5.4",
        (Resolution.ACCEPT,),
        "The node's members changed, so the hierarchy moved. Confirm and re-snapshot.",
    ),
    DivergenceCode.EDGE_CHANGED: Entry(
        Fault.STRUCTURE,
        "§6",
        (Resolution.ACCEPT,),
        "A contract edge appeared, vanished or changed type. An edge is a signature "
        "crossing a boundary, so this reflects a real change in how nodes bind.",
    ),
}


@dataclass(frozen=True)
class Divergence:
    """One addressed difference from the reference, with whose fault it is."""

    code: str
    message: str
    location: Location
    rule: str
    fault: str
    resolutions: tuple[str, ...]
    repair: str
    node: str | None = None
    #: What the reference held, when a repair needs it (a locked signature, for one).
    reference: str | None = None

    @property
    def address(self) -> str:
        return f"{self.location.file}:{self.location.start_line} {self.location.object}"


def _divergence(
    code: DivergenceCode,
    message: str,
    location: Location,
    node: str | None = None,
    reference: str | None = None,
) -> Divergence:
    entry = CATALOGUE[code]
    return Divergence(
        code=code.value,
        message=message,
        location=location,
        rule=entry.rule,
        fault=entry.fault.value,
        resolutions=tuple(resolution.value for resolution in entry.resolutions),
        repair=entry.repair,
        node=node,
        reference=reference,
    )


def reconcile(snapshot: Snapshot, graph: Graph) -> tuple[Divergence, ...]:
    """Diff the current graph against the reference. Nothing here reads code."""
    divergences: list[Divergence] = []

    divergences.extend(_nodes(snapshot, graph))
    divergences.extend(_functions(snapshot, graph))
    divergences.extend(_edges(snapshot, graph))

    return tuple(divergences)


def _nodes(snapshot: Snapshot, graph: Graph) -> list[Divergence]:
    divergences: list[Divergence] = []
    current = {node.id: node for node in graph.nodes}

    for previous in snapshot.nodes:
        node = current.get(previous.id)
        if node is None:
            divergences.append(
                _divergence(
                    DivergenceCode.CARRIER_GONE,
                    f"node {previous.id!r} on {previous.carrier} is no longer declared",
                    Location(
                        file=_file_of(previous.carrier),
                        object=previous.carrier,
                        start_line=1,
                        end_line=1,
                    ),
                    previous.id,
                    reference=previous.carrier,
                )
            )
            continue

        if node.kind != previous.kind:
            divergences.append(
                _divergence(
                    DivergenceCode.KIND_CHANGED,
                    f"kind changed from {previous.kind!r} to {node.kind!r}",
                    node.location,
                    node.id,
                    reference=previous.kind,
                )
            )

        if node.members != previous.members:
            divergences.append(
                _divergence(
                    DivergenceCode.MEMBERS_CHANGED,
                    f"members changed from {list(previous.members)} to {list(node.members)}",
                    node.location,
                    node.id,
                    reference=", ".join(previous.members),
                )
            )

        divergences.extend(_knobs(previous, node))

    for node in graph.nodes:
        if snapshot.node(node.id) is None:
            divergences.append(
                _divergence(
                    DivergenceCode.NODE_ADDED,
                    f"node {node.id!r} is not in the reference",
                    node.location,
                    node.id,
                )
            )

    return divergences


def _knobs(previous: NodeOutline, node: object) -> list[Divergence]:
    current = {knob.name: knob for knob in node.knobs}  # type: ignore[attr-defined]
    divergences: list[Divergence] = []

    for was in previous.knobs:
        now = current.get(was.name)
        if now is None:
            divergences.append(
                _divergence(
                    DivergenceCode.KNOB_CHANGED,
                    f"knob {was.name!r} is gone",
                    node.location,  # type: ignore[attr-defined]
                    node.id,  # type: ignore[attr-defined]
                    reference=was.default,
                )
            )
            continue
        if (now.default, now.type) != (was.default, was.type):
            divergences.append(
                _divergence(
                    DivergenceCode.KNOB_CHANGED,
                    f"knob {was.name!r} changed from {was.type} = {was.default} "
                    f"to {now.type} = {now.default}",
                    now.location or node.location,  # type: ignore[attr-defined]
                    node.id,  # type: ignore[attr-defined]
                    reference=was.default,
                )
            )

    return divergences


def _functions(snapshot: Snapshot, graph: Graph) -> list[Divergence]:
    divergences: list[Divergence] = []
    current = {function.path: function for function in graph.functions}

    for previous in snapshot.functions:
        function = current.get(previous.path)
        if function is None:
            divergences.append(
                _divergence(
                    DivergenceCode.FUNCTION_GONE,
                    f"{previous.path} is no longer declared",
                    Location(
                        file=_file_of(previous.path), object=previous.path, start_line=1, end_line=1
                    ),
                    reference=previous.signature,
                )
            )
            continue

        signature = function.signature.render()
        if previous.signature_locked and signature != previous.signature:
            divergences.append(
                _divergence(
                    DivergenceCode.SIGNATURE_BROKEN,
                    f"locked signature changed from {previous.signature} to {signature}",
                    function.location,
                    reference=previous.signature,
                )
            )

        if function.zone != previous.zone:
            divergences.append(
                _divergence(
                    DivergenceCode.ZONE_CHANGED,
                    f"classification changed from {previous.zone} to {function.zone}",
                    function.location,
                    reference=previous.zone,
                )
            )
            continue

        # Only generated bodies are compared. An editable body is the user's, and §8 is
        # explicit that a change inside one raises nothing.
        if (
            function.zone == "generated"
            and previous.body_digest is not None
            and function.body_digest != previous.body_digest
        ):
            divergences.append(
                _divergence(
                    DivergenceCode.GENERATED_TOUCHED,
                    f"the generated body of {previous.path} was edited",
                    function.location,
                    reference=previous.body_digest,
                )
            )

    return divergences


def _edges(snapshot: Snapshot, graph: Graph) -> list[Divergence]:
    was = {(edge.source, edge.target): edge.contract for edge in snapshot.edges}
    now = {(edge.source, edge.target): edge.contract for edge in graph.edges}
    divergences: list[Divergence] = []

    for pair in sorted(set(was) | set(now)):
        before, after = was.get(pair), now.get(pair)
        if before == after:
            continue

        source = graph.node(pair[0])
        location = (
            source.location
            if source is not None
            else Location(file="", object=f"{pair[0]} -> {pair[1]}", start_line=1, end_line=1)
        )
        described = f"edge {pair[0]} -> {pair[1]} " + (
            "appeared" if before is None else "vanished" if after is None else "changed"
        )
        divergences.append(
            _divergence(
                DivergenceCode.EDGE_CHANGED,
                f"{described}: {before} -> {after}",
                location,
                pair[0],
                reference=before,
            )
        )

    return divergences


def _file_of(dotted: str) -> str:
    """A best-effort file for something that no longer exists to be located.

    A vanished carrier has no position in the current tree, and a diagnostic without an
    address is useless (§9) -- so the dotted path is turned back into the path it was most
    likely written at.
    """
    parts = dotted.split(".")
    return "/".join(parts[:-1]) + ".py" if len(parts) > 1 else f"{dotted}.py"
