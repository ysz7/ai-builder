"""Whether a node is green. One implementation, and it requires both conditions.

Invariant I-5: a green node **parses and passes its observable checks**. The temptation
this guards against is specific and predictable -- the agent moves a decorator until the
parser is satisfied, the badge turns green, and the service is still broken. The defence
is structural rather than procedural: green is computed in exactly one place, that place
takes both inputs, and an absent observable result can never be read as a passing one.

Until the observable-check runner exists (roadmap P4) every static-clean node is
`UNPROVEN`, never `GREEN`. That is the honest state, and it is meant to be visible: it is
the reminder that half of the criterion is not implemented yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["Observation", "Verdict", "verdict_for"]


class Verdict(str, Enum):
    GREEN = "green"
    #: The static gate found something. The graph would misrepresent the code.
    BROKEN = "broken"
    #: Statically clean, but nothing has proven the node actually works.
    UNPROVEN = "unproven"


@dataclass(frozen=True)
class Observation:
    """The result of a node's observable check (P4).

    A distinct type rather than a bool so that "not run" cannot be spelled the same way as
    "ran and failed" -- passing `None` is the absence of evidence, and the absence of
    evidence is never green.
    """

    passed: bool
    check: str
    detail: str | None = None


def verdict_for(*, static_clean: bool, observation: Observation | None) -> Verdict:
    """The only place a node is called green.

    Keyword-only on purpose: two positional booleans at a call site would be one
    transposition away from reporting green on a broken node.
    """
    if not static_clean:
        return Verdict.BROKEN
    if observation is None:
        return Verdict.UNPROVEN
    return Verdict.GREEN if observation.passed else Verdict.BROKEN
