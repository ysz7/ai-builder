"""The diagnostic record, and the catalogue of things that can be wrong.

A diagnostic carries **what**, **where**, **which rule**, and **what a repair must do**
(architecture §9). The address is the point: the difference between a repair that lands
first time and a blind edit that breaks the neighbour is the difference between "fix RAG"
and "in `chunking.py` the node's carrier is gone, restore the boundary without touching
the signature of `chunk()`".

The shape is fixed here, deliberately early. Everything downstream is built against it --
the UI badge, the repair prompt, the snapshot's divergence report -- so widening it later
costs more than getting it right now.

The catalogue below is closed on purpose. A new failure mode gets an entry with its rule
reference and its repair instruction; it never gets an ad-hoc message string invented at
the call site, or the repair prompts stop being writable from the diagnostic alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from framestack_core.ir import Location

__all__ = ["CATALOGUE", "Code", "Diagnostic", "Severity", "describe"]


class Severity(str, Enum):
    """How much of the graph's honesty the violation costs.

    `ERROR` means the graph would misrepresent the code -- a node with no carrier cannot
    be drawn truthfully. `WARNING` means the graph is drawable but something the toolchain
    relies on is missing. Neither rejects the code in v0 (§7, soft gates); both flag it.
    """

    ERROR = "error"
    WARNING = "warning"


class Code(str, Enum):
    """Stable machine identifiers. Renaming one is a breaking API change."""

    UNPARSED_FILE = "file.unparsed"
    MISSING_ID = "node.missing_id"
    DUPLICATE_ID = "node.duplicate_id"
    UNREGISTERED_KIND = "node.unregistered_kind"
    WRONG_CARRIER = "node.wrong_carrier"
    TOP_LEVEL_NOT_GROUP = "node.top_level_not_group"
    MULTIPLE_PARENTS = "node.multiple_parents"
    UNRESOLVED_MEMBER = "node.unresolved_member"
    UNCLASSIFIED_FUNCTION = "function.unclassified"
    UNADDRESSABLE_KNOB = "knob.unaddressable"
    UNDECLARED_CARRIER = "graph.undeclared_carrier"


@dataclass(frozen=True)
class Entry:
    """A catalogue entry: the rule a code violates, and how it is repaired."""

    severity: Severity
    rule: str
    repair: str


#: Every failure the static gate can report. `rule` points at the invariant or the section
#: that is being broken, so a reader can go and check the reasoning rather than trust the
#: message.
CATALOGUE: dict[Code, Entry] = {
    Code.UNPARSED_FILE: Entry(
        Severity.ERROR,
        "§7 acceptance condition 1",
        "Fix the syntax error. Until the file parses, anything it declares is missing "
        "from the graph.",
    ),
    Code.MISSING_ID: Entry(
        Severity.ERROR,
        "§5.1",
        "Give the node an explicit literal `id=`. It must be unique and stable: it is "
        "what the snapshot and every diagnostic address the node by.",
    ),
    Code.DUPLICATE_ID: Entry(
        Severity.ERROR,
        "§5.1",
        "Make the ids unique. Two nodes under one id means every write addressed to it "
        "is ambiguous.",
    ),
    Code.UNREGISTERED_KIND: Entry(
        Severity.ERROR,
        "§5.6",
        "Use a `kind` from the registry. An unregistered kind has no shape and no "
        "observable check, so the node can never go green.",
    ),
    Code.WRONG_CARRIER: Entry(
        Severity.ERROR,
        "I-3, §5.6",
        "Move the node onto a carrier its kind allows, or change the kind to match the "
        "carrier that is actually there.",
    ),
    Code.TOP_LEVEL_NOT_GROUP: Entry(
        Severity.ERROR,
        "§5.1",
        "Claim this node in its subsystem's `members`, or make it a `group_node`. The "
        "top level holds groups only.",
    ),
    Code.MULTIPLE_PARENTS: Entry(
        Severity.ERROR,
        "§5.4",
        "Remove the node from all but one `members` list. Containment is a tree: the "
        "nearest container claims it, and nothing else may.",
    ),
    Code.UNRESOLVED_MEMBER: Entry(
        Severity.ERROR,
        "§5.3",
        "Import the member and list it by object reference. A name the parser cannot "
        "resolve to a node is silently absent from the graph.",
    ),
    Code.UNCLASSIFIED_FUNCTION: Entry(
        Severity.ERROR,
        "§4",
        "Mark the function `@editable(signature_locked=True)` if the user may change its "
        "body, `@generated()` otherwise. An unmarked function reads as a forgotten "
        "classification, because in the syntax tree that is exactly what it looks like.",
    ),
    Code.UNDECLARED_CARRIER: Entry(
        Severity.ERROR,
        "I-3 (Q12)",
        "Put this carrier on the graph: `@node` with a `kind` from the registry, claimed "
        "in its subsystem's `members`. I-3 says every node has a carrier; this is the "
        "other half of it -- a carrier with no node is invisible, and a graph that omits "
        "what the code holds is lying by silence rather than merely incomplete.",
    ),
    Code.UNADDRESSABLE_KNOB: Entry(
        Severity.WARNING,
        "§5.5",
        "Give the field a literal default. The default is the single place the writer "
        "puts a new value; without one the knob can be shown but never edited.",
    ),
}


@dataclass(frozen=True)
class Diagnostic:
    """One addressed problem.

    `message` says what is wrong in this instance; `repair` says what has to be done about
    it, and comes from the catalogue so the instruction is identical every time the same
    rule is broken.
    """

    code: str
    message: str
    location: Location
    rule: str
    severity: str
    repair: str
    node: str | None = None

    @property
    def address(self) -> str:
        """`file:line object` -- the form a human reads and an editor can jump to."""
        return f"{self.location.file}:{self.location.start_line} {self.location.object}"


def describe(code: Code, message: str, location: Location, node: str | None = None) -> Diagnostic:
    """Build a diagnostic from the catalogue, so rule and repair are never invented."""
    entry = CATALOGUE[code]
    return Diagnostic(
        code=code.value,
        message=message,
        location=location,
        rule=entry.rule,
        severity=entry.severity.value,
        repair=entry.repair,
        node=node,
    )
