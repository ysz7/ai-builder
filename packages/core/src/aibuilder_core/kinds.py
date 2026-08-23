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

__all__ = [
    "CarrierType",
    "NodeKind",
    "REGISTRY",
    "TECHNOLOGIES",
    "Technology",
    "installed_version",
    "is_registered",
    "lookup",
    "technology_of",
]


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


#: The three v0 technologies. A kind is added here deliberately, together with its row in
#: the system prompt's table -- a test holds the two lists against each other, because an
#: agent told about a kind the checker cannot dispatch on writes code nothing can prove.
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
        # -- LangGraph (P10). A group over state nodes: the topology is a graph, and the
        # state is what every part of it shares, so the state is a node rather than a
        # detail of the assembly.
        _kind(
            "langgraph.agent",
            CarrierType.GROUP,
            top_level=True,
            check="graph.compiles",
            description="The agent as a whole: a group over its state, steps and routers.",
        ),
        _kind(
            "langgraph.state",
            CarrierType.CLASS,
            check="graph.state_schema",
            description="The state schema every node reads and writes.",
        ),
        _kind(
            "langgraph.node",
            CarrierType.FUNCTION,
            check="graph.node_registered",
            description="One step of the agent: state in, the part of it that changed out.",
        ),
        _kind(
            "langgraph.router",
            CarrierType.FUNCTION,
            check="graph.branch_registered",
            description="A conditional edge: it decides at runtime where the graph goes next.",
        ),
        _kind(
            "langgraph.settings",
            CarrierType.CLASS,
            check="settings.load",
            description="A settings object; the home of the agent's knobs.",
        ),
        # -- RAG (P10). A group over pipeline stages, and the case that forced the group
        # construct (architecture §5.3): each stage is a carrier with its own knobs.
        _kind(
            "rag.pipeline",
            CarrierType.GROUP,
            top_level=True,
            check="rag.stages_load",
            description="The pipeline as a whole: a group over its stages.",
        ),
        _kind(
            "rag.chunking",
            CarrierType.CLASS,
            CarrierType.FUNCTION,
            check="rag.stage_ready",
            description="Splitting documents into the units that get embedded.",
        ),
        _kind(
            "rag.embedding",
            CarrierType.CLASS,
            CarrierType.FUNCTION,
            check="rag.stage_ready",
            description="Turning text into vectors, and the store they go into.",
        ),
        _kind(
            "rag.retrieval",
            CarrierType.CLASS,
            CarrierType.FUNCTION,
            check="rag.stage_ready",
            description="Finding the chunks a question should be answered from.",
        ),
        _kind(
            "rag.generation",
            CarrierType.CLASS,
            CarrierType.FUNCTION,
            check="rag.stage_ready",
            description="Turning retrieved chunks and a question into an answer.",
        ),
    )
}


def lookup(kind: str) -> NodeKind | None:
    return REGISTRY.get(kind)


def is_registered(kind: str) -> bool:
    return kind in REGISTRY


# -- what the checks were written against ----------------------------------------


@dataclass(frozen=True)
class Technology:
    """A stack whose **internals an observable check reads**, and the release it reads.

    This is a statement about our code, not about theirs: "the checks were written against
    this version". It is never a claim that a different version is broken, and nothing here
    refuses, warns about, or blocks an upgrade -- the user's dependencies are not ours to
    police, and a warning about a release we have never run would be a guess wearing the
    costume of a fact.

    It exists because P10 produced the failure it answers. The LangGraph checks reach for
    `builder.nodes[...].runnable.func` -- an attribute LangGraph does not promise -- and a
    release that moves it turns a proven node into an unproven one with a truthful but
    baffling reason. Recorded here, that reason can say what it is actually about.

    A technology whose checks touch no library internals gets **no entry**, and RAG is the
    example: `rag.stage_ready` is plain Python, and the pipeline's real evidence is the
    project's own tests. Recording a version there would be knowledge we do not have.
    """

    name: str
    #: The installed distribution to ask for a version. Not always the import name.
    distribution: str
    #: The release the checks are written and tested against. A test asserts this equals
    #: what is installed, so the number cannot go stale quietly: whoever upgrades the
    #: dependency updates it, or the suite says so.
    verified: str


TECHNOLOGIES: dict[str, Technology] = {
    technology.name: technology
    for technology in (
        Technology(name="fastapi", distribution="fastapi", verified="0.141.1"),
        Technology(name="langgraph", distribution="langgraph", verified="1.2.11"),
    )
}


def technology_of(kind: str) -> Technology | None:
    """The technology a kind belongs to, by its prefix. `None` when nothing is recorded."""
    return TECHNOLOGIES.get(kind.partition(".")[0])


def installed_version(distribution: str) -> str | None:
    """What is actually installed, or `None` when the distribution is not there at all.

    Never raises: this is context attached to an answer, and failing to read a version must
    not cost the answer it was going to be attached to.
    """
    import importlib.metadata

    try:
        return importlib.metadata.version(distribution)
    except Exception:
        return None
