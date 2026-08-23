"""The registry of node kinds.

A `kind` is not a caption. The graph picks a node's shape from it, and the observable-check
runner (roadmap P4) picks that node's proof-of-life from it -- so it is an API value, and
an unregistered one is a diagnostic rather than a new node type someone invented in a
docstring-shaped moment. This is the reflection-registry rule from Unreal: node types are
declared to the system, never conjured by naming.

Adding a technology means adding entries here, deliberately. That is the intended cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["CarrierType", "NodeKind", "REGISTRY", "is_registered", "lookup"]


class CarrierType(str, Enum):
    """What kind of Python object a node hangs on (I-3)."""

    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    GROUP = "group"


@dataclass(frozen=True)
class NodeKind:
    """One entry: what may carry this node, where it may sit, and how it proves it works."""

    name: str
    carriers: frozenset[CarrierType]
    #: May this kind stand at the top level? Only groups may (architecture §5.1).
    top_level: bool
    #: The observable check this kind dispatches to (`observe.py`, `probe.py`).
    #:
    #: A check proves a node by running it with real input -- a call that needs nothing
    #: invented, or, later, the project's own tests with the carriers instrumented. It
    #: never synthesizes input: a pass manufactured from a made-up request is the same
    #: lie as a decorator moved to satisfy the parser (architecture §7).
    check: str
    description: str


def _kind(
    name: str,
    *carriers: CarrierType,
    top_level: bool = False,
    check: str,
    description: str,
) -> NodeKind:
    return NodeKind(
        name=name,
        carriers=frozenset(carriers),
        top_level=top_level,
        check=check,
        description=description,
    )


#: The FastAPI vertical slice. LangGraph and RAG kinds arrive with their phases (P10).
REGISTRY: dict[str, NodeKind] = {
    kind.name: kind
    for kind in (
        _kind(
            "fastapi.service",
            CarrierType.GROUP,
            top_level=True,
            check="http.app_serves",
            description="The service as a whole: a group over its routers and settings.",
        ),
        _kind(
            "fastapi.router",
            CarrierType.FUNCTION,
            CarrierType.CLASS,
            check="http.router_mounts",
            description="An APIRouter and the routes it owns.",
        ),
        _kind(
            "fastapi.route",
            CarrierType.FUNCTION,
            check="http.route_answers",
            description="A single endpoint.",
        ),
        _kind(
            "fastapi.dependency",
            CarrierType.FUNCTION,
            CarrierType.CLASS,
            check="http.dependency_resolves",
            description="A dependency provider injected into routes.",
        ),
        _kind(
            "fastapi.settings",
            CarrierType.CLASS,
            check="settings.load",
            description="A settings object; the home of the service's knobs.",
        ),
    )
}


def lookup(kind: str) -> NodeKind | None:
    return REGISTRY.get(kind)


def is_registered(kind: str) -> bool:
    return kind in REGISTRY
