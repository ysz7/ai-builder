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
    "families",
    "family_of",
    "REGISTRY",
    "TECHNOLOGIES",
    "Technology",
    "installed_version",
    "is_registered",
    "lookup",
    "technology_of",
]


class CarrierType(str, Enum):
    """What a node hangs on (I-3).

    `FILE` is the amendment P10 made deliberately: a non-Python artifact -- a `Dockerfile`,
    a compose file -- is carried by the file itself. I-3 was written to stop nodes over
    *fragments*, and a whole file is not one: it has a path, it is addressable, and it is a
    statement the project makes by existing (architecture §5.7).
    """

    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    GROUP = "group"
    FILE = "file"


@dataclass(frozen=True)
class NodeKind:
    """One entry: what may carry this node, where it may sit, and how it proves it works."""

    name: str
    carriers: frozenset[CarrierType]
    #: May this kind stand at the top level? Only groups may (architecture §5.1).
    top_level: bool
    #: The paths that carry this kind, in the order the tool that owns them would consider
    #: them. Only a kind whose carriers include `FILE` may set it, and this is the whole of
    #: the discovery rule: a file becomes a node because a registry entry named it, never
    #: because its name looked familiar.
    artifact: tuple[str, ...]
    #: The completeness probe this kind opts in to (Q12), or "" for the kinds that do
    #: not. "If it is not on the graph, it is not in the code" is the missing half of I-3,
    #: and it is answered by **asking the library what it holds** after a run -- so a kind
    #: joins the rule by naming a probe here, and the mechanism learns nothing new when the
    #: next kind does. A kind with no probe makes no completeness claim at all, which is
    #: honest rather than lenient: nothing has been asked, so nothing is being asserted.
    completeness: str
    #: How a person talks to this kind, or "" for the kinds nobody can talk to (P17.2).
    #:
    #: A conversation is an action on a node (Q18), and **a kind opts in by naming the way
    #: in** -- never by the toolchain sniffing what a carrier looks like. A kind that has not
    #: opted in shows no button at all, rather than a button that constructs a class and
    #: reports its `repr` as an answer.
    #:
    #: The value names a calling convention, and each one is somebody else's convention that
    #: we are following rather than inventing: `langgraph.ask` is the compiled graph asked
    #: LangGraph's own way, `rag.ask` is the entry point the system prompt requires a
    #: generated pipeline to expose. A convention with no such guarantee does not belong here.
    converses: str
    #: How documents are handed to this kind, or "" for the kinds that hold none (P17.5).
    #:
    #: The same relation as `converses` with a different verb, and it opts in the same way:
    #: indexing is a **write into somebody's store**, so it happens because a person pressed
    #: a button on a node whose kind said it had one -- never as a consequence of drawing the
    #: graph, and never on a kind that was merely callable.
    indexes: str
    #: Which process verb starts and stops this kind, or "" for the kinds nothing starts.
    #:
    #: The same opt-in as `converses` and `indexes`, and it exists for the same reason: the
    #: interface was carrying its own list of which kinds get a Run button --
    #: `fastapi.service`, `mcp.service`, `queue.workers` spelled out in a panel -- which is a
    #: second opinion about the registry that goes stale the moment a kind is added to it.
    #:
    #: The value names the family of verbs, never a command: `run` is `run.start` / `run.stop`
    #: (the application), `work` is `work.start` / `work.stop` (a worker), `env` is `env.up` /
    #: `env.down` (the services a compose file declares). What each of those does is the
    #: runner's business; what this says is only that pressing something here means something.
    #:
    #: It is also what lets a node say **whether it is running right now**, which is the one
    #: piece of state a person looks for first and the graph itself cannot carry: the graph is
    #: a projection of code, and whether a process is alive is not in the code.
    starts: str
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
    artifact: tuple[str, ...] = (),
    completeness: str = "",
    converses: str = "",
    indexes: str = "",
    starts: str = "",
) -> NodeKind:
    return NodeKind(
        name=name,
        carriers=frozenset(carriers),
        top_level=top_level,
        artifact=artifact,
        completeness=completeness,
        converses=converses,
        indexes=indexes,
        starts=starts,
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
            starts="run",
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
            converses="langgraph.ask",
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
            converses="rag.ask",
            indexes="rag.build_index",
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
        # -- Persistence and vectors (P12). The Python that talks to a service is what goes
        # on the graph; the container it connects to is the docker node beside it (Q10).
        _kind(
            "db.session",
            CarrierType.CLASS,
            CarrierType.MODULE,
            check="db.connection_opens",
            description="The object that owns the database connection, and its pool knobs.",
        ),
        _kind(
            "vector.store",
            CarrierType.CLASS,
            CarrierType.MODULE,
            check="vector.store_opens",
            description="The vector index: what is embedded into it and searched in it.",
        ),
        # -- Background work (P14). The subsystem that runs *after* the request, in a
        # process the application never starts. Its nodes are proven by two different
        # things on purpose: a task by a run that entered it, and the queue itself by the
        # broker answering -- because a task that works and a queue that delivers are not
        # the same claim, and one must never stand in for the other.
        _kind(
            "queue.workers",
            CarrierType.GROUP,
            top_level=True,
            starts="work",
            check="queue.assembles",
            description="The background work as a whole: the queue, its tasks and its schedule.",
        ),
        _kind(
            "queue.app",
            CarrierType.CLASS,
            CarrierType.MODULE,
            starts="work",
            check="queue.broker_answers",
            description="The queue itself: the broker it talks to, and a worker's knobs.",
        ),
        _kind(
            "queue.task",
            CarrierType.FUNCTION,
            check="queue.task_registered",
            description="One unit of background work: queued by name, run by a worker.",
        ),
        _kind(
            "queue.schedule",
            CarrierType.FUNCTION,
            CarrierType.CLASS,
            check="queue.schedule_entries",
            description="What runs on a timer, and the tasks those entries name.",
        ),
        # -- MCP and tools (P15). Three roles wear the same word and none of them is the
        # others: a server this project *consumes* is a declaration of how to reach a
        # foreign program, a tool this project *exposes* is its own code, and a tool bound
        # to an agent is a function the agent may call. What a consumed server offers is
        # read from the server and shown as the node's contents -- never as nodes, because
        # a remote tool has no carrier to hang one on (Q12).
        _kind(
            "mcp.service",
            CarrierType.GROUP,
            top_level=True,
            starts="run",
            check="mcp.service_serves",
            description="The MCP server this project exposes: a group over the tools on it.",
        ),
        _kind(
            "mcp.tool",
            CarrierType.FUNCTION,
            check="mcp.tool_exposed",
            completeness="mcp.tools",
            description="A function of ours, offered to whoever connects to our server.",
        ),
        _kind(
            "mcp.server",
            CarrierType.CLASS,
            CarrierType.MODULE,
            check="mcp.server_reachable",
            completeness="mcp.clients",
            description="A server this project talks to: how to reach it, and what it may call.",
        ),
        # The prefix names the technology whose surface the check reads, and this one reads
        # LangGraph's: "bound to the agent" is a fact held by the compiled graph.
        _kind(
            "langgraph.tool",
            CarrierType.FUNCTION,
            check="graph.tool_bound",
            completeness="graph.tools",
            description="A tool bound to an agent, callable from its steps.",
        ),
        # -- Docker (P12). The first nodes carried by a file rather than by a Python
        # object (Q10, architecture §5.7). Neither of them parses anything: what the
        # compose file says is asked of `docker compose config`, and whether a service is
        # usable is answered by connecting to the port it publishes (§5.8).
        _kind(
            "docker.compose",
            CarrierType.FILE,
            top_level=True,
            artifact=(
                "compose.yaml",
                "compose.yml",
                "docker-compose.yaml",
                "docker-compose.yml",
            ),
            starts="env",
            check="docker.services_answer",
            description="The services this project declares, and the buttons that run them.",
        ),
        _kind(
            "docker.image",
            CarrierType.FILE,
            top_level=True,
            artifact=("Dockerfile",),
            check="docker.image_referenced",
            description="The image this project builds itself into.",
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
        # The queue checks ask celery for its task registry, its beat schedule and its
        # workers. Public surface, and still a surface: a release that moves any of it
        # turns a proven node into an unproven one, and this is what lets the reason say so.
        Technology(name="queue", distribution="celery", verified="5.6.3"),
        # The MCP checks ask a server for the tools it is holding and ask a client for what
        # a connection returned. The listing is protocol, but the *identity* question --
        # "is this exact function the one exposed?" -- goes through the SDK's own tool
        # manager, which is a surface like any other.
        Technology(name="mcp", distribution="mcp", verified="2.1.0"),
    )
}


def technology_of(kind: str) -> Technology | None:
    """The technology a kind belongs to, by its prefix. `None` when nothing is recorded."""
    return TECHNOLOGIES.get(kind.partition(".")[0])


def family_of(kind: str) -> str:
    """The family a kind belongs to: the part of its name before the dot.

    Deliberately **not** `technology_of`, which answers a different question with a similar
    word. That one returns the record of a release our checks were written against, and it
    exists only for the four stacks whose internals a check reads -- `rag` has no entry and
    is not going to get one. This one is the naming rule itself, and every registered kind
    has an answer to it.

    It is here rather than in whatever is drawing a list, because a client splitting a kind
    name on a dot would be a second opinion about how kinds are named -- small, correct
    today, and the sort of thing that is discovered to be wrong long after the convention
    changed (§5.6).
    """
    return kind.partition(".")[0]


def families() -> tuple[str, ...]:
    """Every family the registry holds, in the order the registry declares them.

    Derived and never listed: **a family exists because a kind named it.** A written-down
    list of families is exactly the thing that would let a new kind be added and quietly not
    appear anywhere, which is the failure P19's library exists to make impossible.

    Registry order rather than alphabetical: the registry is already grouped by technology
    and ordered by the phase that added each one, and that order is more use to a reader
    than the alphabet.
    """
    seen: dict[str, None] = {}
    for name in REGISTRY:
        seen.setdefault(family_of(name), None)
    return tuple(seen)


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
