"""The static gate: acceptance condition 1.

The parser draws the graph; this decides whether the graph is drawable *truthfully*. The
two are the same machine on purpose (§7) -- the thing that reads the code is the thing
that guards the invariant that the code is readable at all.

**Soft by default** (§7, the v0 decision). Violations flag the node; they do not reject
the code. Early on, collecting the list of the agent's real misses is worth more than a
perfect graph on three test projects, and a hard refusal would hide exactly the cases we
need to see. Hard mode exists as a switch rather than a rewrite, because a demo will
eventually want it.

**This gate cannot make a node green.** It answers half of I-5; the observable checks (P4)
answer the other half, and `verdict.py` is the single place the two are combined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from aibuilder_core.diagnostics import Code, Diagnostic, Severity, describe
from aibuilder_core.ir import Graph, Node
from aibuilder_core.kinds import CarrierType, lookup
from aibuilder_core.verdict import Observation, Verdict, verdict_for

__all__ = ["GateMode", "GateResult", "check_graph"]

#: The prefix the parser gives a node whose `id=` is missing or not a literal.
_UNIDENTIFIED = "<unidentified:"


class GateMode(str, Enum):
    """Whether a violation stops the code entering the project."""

    SOFT = "soft"
    HARD = "hard"


@dataclass(frozen=True)
class GateResult:
    diagnostics: tuple[Diagnostic, ...] = ()
    #: node id -> its verdict. Never `GREEN` while the observable runner is missing.
    verdicts: dict[str, str] = field(default_factory=dict)
    mode: str = GateMode.SOFT.value

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == Severity.ERROR.value)

    @property
    def accepted(self) -> bool:
        """Whether the code enters the project.

        Soft mode always accepts -- that is what "soft" means, and the badge plus the
        repair offer (§9) is the whole response to a violation in v0.
        """
        return self.mode == GateMode.SOFT.value or not self.errors

    def for_node(self, node_id: str) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.node == node_id)


def check_graph(
    graph: Graph,
    *,
    mode: GateMode = GateMode.SOFT,
    observations: dict[str, Observation] | None = None,
) -> GateResult:
    """Run every static acceptance check and compute each node's verdict."""
    diagnostics: list[Diagnostic] = []

    diagnostics.extend(_unparsed_files(graph))
    diagnostics.extend(_node_identity(graph))
    diagnostics.extend(_node_kinds(graph))
    diagnostics.extend(_containment(graph))
    diagnostics.extend(_classification(graph))
    diagnostics.extend(_knobs(graph))

    observations = observations or {}
    flagged = {d.node for d in diagnostics if d.severity == Severity.ERROR.value}
    verdicts = {
        node.id: verdict_for(
            static_clean=node.id not in flagged,
            observation=observations.get(node.id),
        ).value
        for node in graph.nodes
    }

    return GateResult(
        diagnostics=tuple(diagnostics),
        verdicts=verdicts,
        mode=mode.value,
    )


def _unparsed_files(graph: Graph) -> list[Diagnostic]:
    return [
        describe(
            Code.UNPARSED_FILE,
            f"{location.file} could not be parsed ({location.object}); "
            "anything it declares is missing from the graph",
            location,
        )
        for location in graph.unparsed
    ]


def _node_identity(graph: Graph) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: dict[str, Node] = {}

    for node in graph.nodes:
        if node.id.startswith(_UNIDENTIFIED):
            diagnostics.append(
                describe(
                    Code.MISSING_ID,
                    f"the node on {node.carrier} has no literal `id=`",
                    node.location,
                    node.id,
                )
            )
            continue

        first = seen.get(node.id)
        if first is not None:
            diagnostics.append(
                describe(
                    Code.DUPLICATE_ID,
                    f"id {node.id!r} is declared twice: on {first.carrier} and on {node.carrier}",
                    node.location,
                    node.id,
                )
            )
        else:
            seen[node.id] = node

    return diagnostics


def _node_kinds(graph: Graph) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    for node in graph.nodes:
        kind = lookup(node.kind)
        if kind is None:
            diagnostics.append(
                describe(
                    Code.UNREGISTERED_KIND,
                    f"kind {node.kind!r} is not in the registry",
                    node.location,
                    node.id,
                )
            )
            continue

        if CarrierType(node.carrier_type) not in kind.carriers:
            allowed = ", ".join(sorted(carrier.value for carrier in kind.carriers))
            diagnostics.append(
                describe(
                    Code.WRONG_CARRIER,
                    f"kind {node.kind!r} expects a carrier of type {allowed}, "
                    f"but {node.carrier} is a {node.carrier_type}",
                    node.location,
                    node.id,
                )
            )

    return diagnostics


def _containment(graph: Graph) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    parents: dict[str, list[str]] = {}
    for node in graph.nodes:
        for member in node.members:
            parents.setdefault(member, []).append(node.id)

    for node in graph.nodes:
        claims = parents.get(node.id, [])

        if len(claims) > 1:
            diagnostics.append(
                describe(
                    Code.MULTIPLE_PARENTS,
                    f"claimed as a member by {', '.join(sorted(claims))}",
                    node.location,
                    node.id,
                )
            )

        if not claims and node.carrier_type != CarrierType.GROUP.value:
            diagnostics.append(
                describe(
                    Code.TOP_LEVEL_NOT_GROUP,
                    f"no node claims {node.id!r}, so it sits at the top level, "
                    "which holds groups only",
                    node.location,
                    node.id,
                )
            )

        for missing in node.unresolved_members:
            diagnostics.append(
                describe(
                    Code.UNRESOLVED_MEMBER,
                    f"member {missing!r} resolves to no node",
                    node.location,
                    node.id,
                )
            )

    return diagnostics


def _classification(graph: Graph) -> list[Diagnostic]:
    """Unmarked functions, in the files that take part in the graph.

    A file with no markup at all is not part of the graph and is nobody's business here
    (§4: code outside a carrier is invisible, not illegal). A file that already carries a
    node or a classified function *is* participating -- and there, an unmarked function is
    a forgotten classification, because that is precisely what one looks like.
    """
    participating = {node.location.file for node in graph.nodes}
    participating |= {
        function.location.file for function in graph.functions if function.zone is not None
    }

    return [
        describe(
            Code.UNCLASSIFIED_FUNCTION,
            f"{function.path} is neither @editable nor @generated",
            function.location,
        )
        for function in graph.functions
        if function.zone is None and function.location.file in participating
    ]


def _knobs(graph: Graph) -> list[Diagnostic]:
    return [
        describe(
            Code.UNADDRESSABLE_KNOB,
            f"knob {knob.name!r} has no literal default, so there is nowhere to write to",
            knob.location or node.location,
            node.id,
        )
        for node in graph.nodes
        for knob in node.knobs
        if knob.default is None
    ]


def summarize(result: GateResult) -> str:
    """A one-line count, for a CLI and for logs."""
    errors = len(result.errors)
    warnings = len(result.diagnostics) - errors
    green = sum(1 for verdict in result.verdicts.values() if verdict == Verdict.GREEN.value)
    return f"{errors} error(s), {warnings} warning(s), {green}/{len(result.verdicts)} node(s) green"
