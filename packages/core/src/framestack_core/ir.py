"""The graph intermediate representation.

What the parser produces and everything downstream consumes: the UI draws it, the gates
judge it, the snapshot is a subset of it, and the writer addresses code through it.

Two properties are load-bearing:

* **It is derived, never stored.** The IR is rebuilt from code on demand. Persisting it as
  the thing the graph reads would create the second source of truth I-1 forbids -- the
  snapshot (P5) keeps an outline of it strictly as a diff reference.
* **Everything carries an address.** Every record knows its file, its object and its lines,
  because a diagnostic without an address (§9) cannot be repaired, only guessed at.

Positions are 1-indexed lines, matching every editor and `git`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "Edge",
    "Function",
    "Graph",
    "Knob",
    "Location",
    "Node",
    "Parameter",
    "Signature",
    "Zone",
]

#: What the parser saw. `None` means the function carries neither mark -- not an error here
#: (the gate decides that in P3), but a fact the gate needs reported.
Zone = str


@dataclass(frozen=True)
class Location:
    """Where something is. The address half of every diagnostic (§9)."""

    file: str
    object: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Parameter:
    name: str
    annotation: str | None
    default: str | None


@dataclass(frozen=True)
class Signature:
    """A function's contract. This, not the body, is what the graph draws edges from (§6)."""

    parameters: tuple[Parameter, ...] = ()
    returns: str | None = None

    def render(self) -> str:
        rendered = []
        for parameter in self.parameters:
            text = parameter.name
            if parameter.annotation:
                text += f": {parameter.annotation}"
            if parameter.default:
                text += f" = {parameter.default}"
            rendered.append(text)
        returns = f" -> {self.returns}" if self.returns else ""
        return f"({', '.join(rendered)}){returns}"


@dataclass(frozen=True)
class Knob:
    """A user-tunable value: an `Annotated` field whose literal default the writer targets."""

    name: str
    type: str
    default: str | None
    widget: str | None = None
    label: str | None = None
    help: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[str, ...] | None = None
    location: Location | None = None


@dataclass(frozen=True)
class Function:
    """Every function definition the parser found, marked or not.

    Unmarked ones are here on purpose: "no unmarked functions inside a carrier" is a gate
    rule (P3), and a gate cannot report what the parser silently dropped.
    """

    path: str
    zone: Zone | None
    signature: Signature
    signature_locked: bool
    location: Location
    #: A structural digest of a **generated** body, and `None` for every editable one.
    #:
    #: The absence is deliberate, not an oversight. Reconciliation has to notice a touched
    #: generated zone (§9 case 2) and must raise nothing at all when a user edits inside an
    #: editable body (§8) -- so the material for the first comparison exists and the
    #: material for the second does not. Carrying an editable digest "just in case" would
    #: be an invitation to diff it later.
    #:
    #: Structural, so a reformat is not a change: it is taken from the abstract syntax with
    #: positions and comments dropped.
    body_digest: str | None = None
    #: The generated body's source, and `None` for editable ones on the same reasoning.
    #:
    #: The digest answers "did this change"; the source is what makes "revert to the last
    #: working state" (§9 case 2) an action rather than a word. A choice between reverting
    #: and accepting is only a real choice if the tool can actually perform both.
    body_source: str | None = None


@dataclass(frozen=True)
class Node:
    """A unit on the graph. Always has a carrier (I-3)."""

    id: str
    kind: str
    title: str | None
    carrier: str
    carrier_type: str
    location: Location
    zone: Zone | None = None
    signature: Signature | None = None
    knobs: tuple[Knob, ...] = ()
    #: The nodes this one contains, as node ids. Declared, never inferred (§5.4).
    members: tuple[str, ...] = ()
    #: Names listed as members that resolve to no node. Reported rather than dropped:
    #: a member the parser cannot find is missing from the graph, and silence about it
    #: would make the graph quietly smaller than the code.
    unresolved_members: tuple[str, ...] = ()
    #: The first line of the carrier's docstring, or "". What the node says about itself,
    #: in the author's own words rather than in ours (Q29). Nothing decides anything by it:
    #: no gate reads it and no verdict depends on it, so a carrier that gains or loses a
    #: docstring changes what a card *says* and never what the graph *is*.
    summary: str = ""


@dataclass(frozen=True)
class Edge:
    """A type crossing a node boundary (§6).

    The edge exists because one node's carrier names another's; the **contract** is read
    off the target's signature. Never guessed, never drawn by hand in the canvas.
    """

    source: str
    target: str
    contract: str


@dataclass(frozen=True)
class Graph:
    """One project, as the builder sees it."""

    root: str
    nodes: tuple[Node, ...] = ()
    functions: tuple[Function, ...] = ()
    edges: tuple[Edge, ...] = ()
    #: Files the parser could not read at all. Their contents are unknown, so anything
    #: they declared is missing from the graph and the caller has to be told.
    unparsed: tuple[Location, ...] = field(default_factory=tuple)

    def node(self, node_id: str) -> Node | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    @property
    def top_level(self) -> tuple[Node, ...]:
        """Nodes no group claims as a member."""
        claimed = {member for node in self.nodes for member in node.members}
        return tuple(node for node in self.nodes if node.id not in claimed)

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-ready data. The wire form the shell and the UI receive."""
        return asdict(self)
