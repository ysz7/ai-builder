"""The graph API: what the shell and the UI are handed.

Versioned from the first day it exists. The UI is delivered separately and on its own
schedule, so the two sides will be out of step at some point; a payload that announces its
version can be handled, one that changes shape silently cannot.

Everything here is assembly. The parsing is `parser.py`, the judging is `gate.py`, the
green verdict is `verdict.py` -- this module puts their results in one envelope and adds
nothing of its own. A decision made here would be a decision made twice.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from aibuilder_core.agent import build_brief, failure_modes, record_outcome
from aibuilder_core.catalog import find_catalog, list_blueprints
from aibuilder_core.diagnostics import Code, describe
from aibuilder_core.environment import describe_environment, start_services, stop_services
from aibuilder_core.gate import GateMode, check_graph
from aibuilder_core.ir import Location
from aibuilder_core.kinds import REGISTRY
from aibuilder_core.layout import create_project, read_layout, write_layout
from aibuilder_core.observe import run_observations
from aibuilder_core.project import read_project
from aibuilder_core.reconcile import reconcile
from aibuilder_core.repair import apply_repair, list_repairs
from aibuilder_core.runner import (
    build_image,
    call_endpoint,
    call_server_tool,
    inspect_server,
    read_logs,
    read_worker_logs,
    run_status,
    start_application,
    start_worker,
    stop_application,
    stop_worker,
    worker_status,
)
from aibuilder_core.session import (
    poll_session,
    say,
    session_status,
    start_session,
    stop_session,
)
from aibuilder_core.snapshot import load_snapshot, save_snapshot, take_snapshot
from aibuilder_core.verdict import Observation
from aibuilder_core.writer import set_body, set_knob, set_node_title

__all__ = [
    "AGENT_BLUEPRINTS_SCHEMA",
    "AGENT_BRIEF_SCHEMA",
    "AGENT_SESSION_SCHEMA",
    "AGENT_FAILURES_SCHEMA",
    "AGENT_RECORD_SCHEMA",
    "ENVIRONMENT_SCHEMA",
    "GRAPH_API_VERSION",
    "RUN_CALL_SCHEMA",
    "RUN_SCHEMA",
    "SERVICE_SCHEMA",
    "GRAPH_KINDS_SCHEMA",
    "GRAPH_READ_SCHEMA",
    "LAYOUT_READ_SCHEMA",
    "LAYOUT_WRITE_SCHEMA",
    "MCP_CALL_SCHEMA",
    "MCP_INSPECT_SCHEMA",
    "SNAPSHOT_STATUS_SCHEMA",
    "SNAPSHOT_TAKE_SCHEMA",
    "REPAIR_APPLY_SCHEMA",
    "REPAIR_LIST_SCHEMA",
    "WRITE_SCHEMA",
    "agent_blueprints",
    "environment_status",
    "run_build",
    "run_call",
    "run_logs",
    "run_start",
    "run_state",
    "run_stop",
    "services_start",
    "services_stop",
    "agent_brief",
    "agent_failures",
    "agent_open",
    "agent_poll",
    "agent_say",
    "agent_session",
    "agent_shut",
    "agent_record",
    "describe_kinds",
    "create_new_project",
    "layout_get",
    "layout_put",
    "mcp_call",
    "mcp_inspect",
    "read_graph",
    "snapshot_status",
    "take_project_snapshot",
    "repair_divergence",
    "repairs_available",
    "write_body",
    "write_knob",
    "write_node_title",
]

#: Bumped when the payload's shape changes in a way a client would notice. Additive fields
#: do not bump it; removing or retyping one does.
#:
#: 2: the environment's services stopped being a list of names plus a list of running ones,
#: and became one list of services each carrying its ports and whether anything answers
#: there. Readiness is now a connection rather than docker's own status, so the old fields
#: had nothing behind them (P11).
GRAPH_API_VERSION = 2


# -- the contract ---------------------------------------------------------------
#
# Written out rather than derived from what the code happens to emit: a contract is a
# decision, and a schema inferred from current behaviour would ratify a mistake as readily
# as a design. The test validates real payloads against this, strictly -- an undeclared
# field fails just as loudly as a missing one, because a client that starts depending on
# an accidental field is a client we have silently promised something to.
#
# Notation: "str"/"int"/"bool" are scalars, a trailing "?" allows null, [x] is a list of
# x, {...} is an object with exactly these keys, {"<key>": x} is a map with arbitrary keys
# and values shaped like x, and `_null_or(x)` allows a structure to be absent.


def _null_or(schema: Any) -> dict[str, Any]:
    """A structure that may arrive as null -- a group node has no signature, for one."""
    return {"<nullable>": schema}


_LOCATION = {"file": "str", "object": "str", "start_line": "int", "end_line": "int"}

_SIGNATURE = {
    "parameters": [{"name": "str", "annotation": "str?", "default": "str?"}],
    "returns": "str?",
}

_KNOB = {
    "name": "str",
    "type": "str",
    "default": "str?",
    "widget": "str?",
    "label": "str?",
    "help": "str?",
    "min": "number?",
    "max": "number?",
    "step": "number?",
    "choices": _null_or(["str"]),
    "location": _null_or(_LOCATION),
}

_NODE = {
    "id": "str",
    "kind": "str",
    "title": "str?",
    "carrier": "str",
    "carrier_type": "str",
    "location": _LOCATION,
    "zone": "str?",
    "signature": _null_or(_SIGNATURE),
    "knobs": [_KNOB],
    "members": ["str"],
    "unresolved_members": ["str"],
}

_FUNCTION = {
    "path": "str",
    "zone": "str?",
    "signature": _SIGNATURE,
    "signature_locked": "bool",
    "location": _LOCATION,
    # Generated bodies only; null for every editable one, deliberately (see ir.Function).
    "body_digest": "str?",
    "body_source": "str?",
}

_EDGE = {"source": "str", "target": "str", "contract": "str"}

_DIAGNOSTIC = {
    "code": "str",
    "message": "str",
    "location": _LOCATION,
    "rule": "str",
    "severity": "str",
    "repair": "str",
    "node": "str?",
}

_ENVIRONMENT = {
    "interpreter": "str",
    "interpreter_origin": "str",
    "compose_file": "str?",
    # Each declared service, and whether anything answers where it publishes. Readiness is
    # a connection rather than a status field: it is the question the application asks.
    "services": [{"name": "str", "ports": ["int"], "reachable": "bool", "dockerfile": "str?"}],
    "missing": ["str"],
    "docker_unavailable": "str?",
    "incomplete": "str?",
}

#: The `env.status` payload: what the project runs in. Read-only, always -- describing an
#: environment never changes it (P11).
ENVIRONMENT_SCHEMA = {"api_version": "int", "environment": _ENVIRONMENT}

#: The `env.up` / `env.down` payload. These are the two methods that do change something,
#: and they exist so that nothing else has to.
SERVICE_SCHEMA = {"api_version": "int", "ok": "bool", "detail": "str", "services": ["str"]}

#: The payload of every `run.*` and `work.*` verb except `run.call`. One schema because
#: they are one shape: a process was started, found or stopped, and `port` is 0 for a worker
#: -- which publishes nothing and is reached through the queue instead. Refusals are results
#: here too: a project with no application to run is a normal answer, not a fault in the call.
RUN_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "state": _null_or(
        {
            "pid": "int",
            "port": "int",
            "target": "str",
            "command": ["str"],
            "started_at": "str",
        }
    ),
    "logs": "str",
    # Where the reader got to. Logs are polled, never pushed: the wire carries one answer
    # per request, and a stream would hold it open (P13).
    "offset": "int",
}

#: The `run.call` payload: what the running application answered when it was called.
RUN_CALL_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "status": "int?",
    "body": "str",
}

#: The `graph.read` payload.
GRAPH_READ_SCHEMA = {
    "api_version": "int",
    "root": "str",
    "graph": {
        "root": "str",
        "nodes": [_NODE],
        "functions": [_FUNCTION],
        "edges": [_EDGE],
        "unparsed": [_LOCATION],
    },
    "diagnostics": [_DIAGNOSTIC],
    "verdicts": {"<key>": "str"},
    # Evidence from the observable checks, and the reason for everything that stayed
    # unproven. Both are empty unless the caller asked for them: running them imports and
    # executes the project, which is never a side effect a read should have by surprise.
    "observations": {"<key>": {"passed": "bool", "check": "str", "detail": "str?"}},
    "skipped": {"<key>": "str"},
    # Present only when the checks ran: it describes the environment they ran in, and
    # describing it means asking docker, which a plain read has no business doing.
    "environment": _null_or(_ENVIRONMENT),
    # What ran, and in what order (Q9). A different relation from `graph.edges`: an edge is
    # a type crossing a boundary, a flow is one node running and then another. Empty until
    # something has actually run.
    "flow": [{"source": "str", "target": "str", "origin": "str"}],
    # Whether the graph is complete about what is in the code (Q12), and what it left out.
    # `state` is `unproven` until a run has actually asked the libraries -- a completeness
    # claim from a static read would be the I-5 failure one level up. The undeclared
    # carriers also appear in `diagnostics`, addressed like everything else.
    "completeness": {"state": "str", "detail": "str", "undeclared": [_LOCATION]},
    "mode": "str",
    "accepted": "bool",
}

#: The `mcp.inspect` payload: what a consumed server answered when somebody connected to
#: it. `status` is the node's verdict for this connection and nothing is written down --
#: a colleague who has not connected sees `unproven`, never somebody else's yesterday
#: (I-1). `tools` is the server's own listing: contents of the node, never nodes (Q12).
MCP_INSPECT_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "status": "str",
    "detail": "str",
    "tools": [{"name": "str", "description": "str"}],
    "allowed": ["str"],
    "missing": ["str"],
}

#: The `mcp.call` payload: what one tool said when it was called with input a person typed.
MCP_CALL_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "status": "str",
    "detail": "str",
    "result": "str",
}

#: The `layout.read` payload: where the person put things (Q13).
#:
#: `"<opaque>"` is not a shrug — it is the contract. The core stores this and refuses to
#: look inside, because a core that understood a coordinate would sooner or later be asked
#: to produce one, and a graph the toolchain laid out is a graph it has an opinion about.
LAYOUT_READ_SCHEMA = {"api_version": "int", "layout": {"<key>": "<opaque>"}}

#: The `layout.write` payload. A refusal is a result, as everywhere else.
LAYOUT_WRITE_SCHEMA = {"api_version": "int", "ok": "bool", "detail": "str"}

_DIVERGENCE = {
    "code": "str",
    "message": "str",
    "location": _LOCATION,
    "rule": "str",
    "fault": "str",
    "resolutions": ["str"],
    "repair": "str",
    "node": "str?",
    "reference": "str?",
}

#: The `snapshot.status` payload.
SNAPSHOT_STATUS_SCHEMA = {
    "api_version": "int",
    "has_reference": "bool",
    "divergences": [_DIVERGENCE],
}

#: The `snapshot.take` payload.
SNAPSHOT_TAKE_SCHEMA = {
    "api_version": "int",
    "taken": "bool",
    "path": "str?",
    "refused": "str?",
}

#: The payload of every write. `diagnostics` is populated only when a write was undone.
WRITE_SCHEMA = {
    "api_version": "int",
    "written": "bool",
    "file": "str?",
    "refused": "str?",
    "diagnostics": [_DIAGNOSTIC],
}

#: The `repair.list` payload. `mechanical` is the subset of `resolutions` the toolchain can
#: carry out itself; everything else is handed to the agent as `request`.
REPAIR_LIST_SCHEMA = {
    "api_version": "int",
    "repairs": [{**_DIVERGENCE, "mechanical": ["str"], "request": "str"}],
}

#: The `repair.apply` payload.
REPAIR_APPLY_SCHEMA = {
    "api_version": "int",
    "applied": "bool",
    "snapshot_updated": "bool",
    "file": "str?",
    "refused": "str?",
    "diagnostics": [_DIAGNOSTIC],
    "unproven": ["str"],
}

#: The `graph.kinds` payload.
GRAPH_KINDS_SCHEMA = {
    "api_version": "int",
    "kinds": [
        {
            "name": "str",
            "carriers": ["str"],
            "top_level": "bool",
            "check": "str",
            "description": "str",
        }
    ],
}

_BLUEPRINT_ENTRY = {
    "id": "str",
    "title": "str",
    "summary": "str",
    "path": "str",
    "section": "str",
}

#: The `agent.blueprints` payload. `catalog` is null when there is no catalog to read --
#: input B is then unavailable, and input A is untouched by that (§3).
AGENT_BLUEPRINTS_SCHEMA = {
    "api_version": "int",
    "catalog": "str?",
    "blueprints": [_BLUEPRINT_ENTRY],
}

#: The `agent.brief` payload: one request to the code-generation agent, whichever input
#: produced it. `system_prompt` is the same text in both -- the rules do not come from the
#: blueprint (§3), and a client comparing two briefs can see that for itself.
AGENT_BRIEF_SCHEMA = {
    "api_version": "int",
    "refused": "str?",
    "brief": _null_or(
        {
            "source": "str",
            "request": "str",
            "system_prompt": "str",
            "instructions": "str",
            "project_exists": "bool",
            "kinds": ["str"],
            "outline": [
                {
                    "id": "str",
                    "kind": "str",
                    "title": "str?",
                    "carrier": "str",
                    "file": "str",
                    "members": ["str"],
                }
            ],
            "blueprint": _null_or({**_BLUEPRINT_ENTRY, "text": "str?", "carries_markup": "bool"}),
        }
    ),
}

_LOG_ENTRY = {
    "at": "str",
    "source": "str",
    "blueprint": "str?",
    "request": "str",
    "observed": "bool",
    # Which turn of which conversation produced this (Q16). Null when nothing drove it
    # from a session -- the entry then stands alone, as every entry used to.
    "session": "str?",
    "turn": "int?",
    "diagnostics": [
        {"code": "str", "severity": "str", "rule": "str", "node": "str?", "address": "str"}
    ],
    "verdicts": {"<key>": "str"},
    "accepted": "bool",
    "versions": {"<key>": "str?"},
}

#: The payload of every `agent.*` session verb. One schema because they are one shape: an
#: agent was found, a session was opened, something was said, or events came back. `events`
#: is what an interface can act on -- what is happening, which file, what was refused -- and
#: the raw stream stays in the log where it can be read whole.
AGENT_SESSION_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "session": "str?",
    "running": "bool",
    "available": "bool",
    "version": "str",
    "events": [{"kind": "str", "text": "str", "file": "str"}],
    # Where the reader got to. Events are polled, never pushed (P13).
    "offset": "int",
    # The conversations this project has had -- ids and labels, never a transcript.
    "sessions": [{"id": "str", "label": "str", "at": "str"}],
    # Tokens the last turn carried. A **number, never a percentage**: the stream declares no
    # context window, so whoever draws a ring has to say what they divided by.
    "context": "int",
}

#: The `agent.record` payload: what the gates said about one generation, as it was logged.
AGENT_RECORD_SCHEMA = {"api_version": "int", "entry": _LOG_ENTRY}

#: The `agent.failures` payload: the agent's failure modes, tallied over the log.
AGENT_FAILURES_SCHEMA = {
    "api_version": "int",
    "generations": "int",
    "clean": "int",
    "codes": [
        {
            "code": "str",
            "count": "int",
            "rule": "str",
            "severity": "str",
            "addresses": ["str"],
        }
    ],
}


def read_graph(
    project: Path | str,
    *,
    mode: GateMode = GateMode.SOFT,
    observe: bool = False,
    observations: dict[str, Observation] | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Parse a project, judge it, and return the whole answer in one envelope.

    One call rather than "parse" plus "check": a client that could ask for the graph
    without its diagnostics would eventually draw one, and a graph rendered without its
    badges is a graph that lies.

    `observe` additionally runs the observable checks, which **imports and executes the
    project** in a subprocess. It is off by default because reading a graph should not
    start a database connection as a side effect -- and because without it every node is
    honestly `unproven` rather than falsely fine.
    """
    root = Path(project)
    graph = read_project(root)

    skipped: dict[str, str] = {}
    environment: dict[str, Any] | None = None
    flow: list[dict[str, str]] = []
    completeness: dict[str, Any] = {
        "state": "unproven",
        "detail": "nothing was run, so nothing was asked",
        "undeclared": [],
    }
    if observe and observations is None:
        run = run_observations(graph, root, python=python)
        observations, skipped = run.observations, run.skipped
        environment = None if run.environment is None else run.environment.as_dict()
        flow = [dict(edge) for edge in run.flow]
        completeness = dict(run.completeness)

    result = check_graph(graph, mode=mode, observations=observations)

    # The undeclared carriers join the gate's findings as ordinary addressed diagnostics --
    # but they are not gate findings and they do not touch `accepted`: the gate is a static
    # judgement and this one needed a run. Mixing them would make a hard gate depend on
    # whether anybody had pressed observe.
    incomplete = [_undeclared(entry) for entry in completeness.get("undeclared", [])]

    return {
        "api_version": GRAPH_API_VERSION,
        "root": graph.root,
        "graph": graph.to_dict(),
        "diagnostics": [asdict(diagnostic) for diagnostic in [*result.diagnostics, *incomplete]],
        "verdicts": result.verdicts,
        "observations": {
            node: {"passed": o.passed, "check": o.check, "detail": o.detail}
            for node, o in (observations or {}).items()
        },
        "skipped": skipped,
        "environment": environment,
        "flow": flow,
        "completeness": {
            "state": str(completeness.get("state", "unproven")),
            "detail": str(completeness.get("detail", "")),
            "undeclared": [asdict(diagnostic.location) for diagnostic in incomplete],
        },
        "mode": result.mode,
        "accepted": result.accepted,
    }


def _undeclared(entry: dict[str, Any]) -> Any:
    """One carrier the libraries hold that no node declares, as an addressed diagnostic."""
    return describe(
        Code.UNDECLARED_CARRIER,
        f"{entry.get('what', 'something')} is in the code but not on the graph",
        Location(
            file=str(entry.get("file", "?")),
            object=str(entry.get("object", "?")),
            start_line=int(entry.get("line", 1) or 1),
            end_line=int(entry.get("line", 1) or 1),
        ),
    )


def environment_status(project: Path | str, python: str | None = None) -> dict[str, Any]:
    """What the project runs in: its interpreter, its services, and what is up right now."""
    return {
        "api_version": GRAPH_API_VERSION,
        "environment": describe_environment(project, python).as_dict(),
    }


def services_start(project: Path | str, python: str | None = None) -> dict[str, Any]:
    """Bring the project's declared services up. Only ever because a person asked (P11)."""
    return {"api_version": GRAPH_API_VERSION, **start_services(project, python).as_dict()}


def services_stop(project: Path | str) -> dict[str, Any]:
    """Take them down again."""
    return {"api_version": GRAPH_API_VERSION, **stop_services(project).as_dict()}


def run_start(
    project: Path | str, python: str | None = None, port: int | None = None
) -> dict[str, Any]:
    """Start the project's application and return once it answers."""
    return {"api_version": GRAPH_API_VERSION, **start_application(project, python, port).as_dict()}


def run_stop(project: Path | str) -> dict[str, Any]:
    """Stop it -- whether this session started it or a crashed one did."""
    return {"api_version": GRAPH_API_VERSION, **stop_application(project).as_dict()}


def run_state(project: Path | str) -> dict[str, Any]:
    """Is it running? Asked of the operating system and the port, never of a memory."""
    return {"api_version": GRAPH_API_VERSION, **run_status(project).as_dict()}


def run_logs(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What it has printed since `offset`. Polled by the caller, never pushed."""
    return {"api_version": GRAPH_API_VERSION, **read_logs(project, offset).as_dict()}


def run_call(project: Path | str, path: str = "/", method: str = "GET") -> dict[str, Any]:
    """Call the running application: the verb a person pressing a route node wants."""
    return {"api_version": GRAPH_API_VERSION, **call_endpoint(project, path, method).as_dict()}


def work_start(project: Path | str, python: str | None = None) -> dict[str, Any]:
    """Start a worker for the project's queue -- the button on the queue's node (P14)."""
    return {"api_version": GRAPH_API_VERSION, **start_worker(project, python).as_dict()}


def work_stop(project: Path | str) -> dict[str, Any]:
    """Stop it -- this session's worker, or one a crashed session left behind."""
    return {"api_version": GRAPH_API_VERSION, **stop_worker(project).as_dict()}


def work_state(project: Path | str, python: str | None = None) -> dict[str, Any]:
    """Is a worker running? Asked of the operating system, then of the queue itself."""
    return {"api_version": GRAPH_API_VERSION, **worker_status(project, python).as_dict()}


def work_logs(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What the worker has printed since `offset`. Polled, like the application's."""
    return {"api_version": GRAPH_API_VERSION, **read_worker_logs(project, offset).as_dict()}


def create_new_project(parent: Path | str, name: str) -> dict[str, Any]:
    """Make an empty directory for a project. `detail` is the path when it worked."""
    return {"api_version": GRAPH_API_VERSION, **create_project(parent, name).as_dict()}


def layout_get(project: Path | str) -> dict[str, Any]:
    """Where the person put things. Empty is the ordinary first answer, not a failure."""
    return {"api_version": GRAPH_API_VERSION, "layout": read_layout(project)}


def layout_put(project: Path | str, layout: dict[str, Any]) -> dict[str, Any]:
    """Store the whole layout. The client holds it; the core keeps it and reads nothing."""
    return {"api_version": GRAPH_API_VERSION, **write_layout(project, layout).as_dict()}


def mcp_inspect(project: Path | str, node: str, python: str | None = None) -> dict[str, Any]:
    """Connect to a consumed server and list what it offers -- the button on its node."""
    return {"api_version": GRAPH_API_VERSION, **inspect_server(project, node, python)}


def mcp_call(
    project: Path | str,
    node: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Call one of that server's tools with input a person typed. Never invented (Q7)."""
    return {
        "api_version": GRAPH_API_VERSION,
        **call_server_tool(project, node, tool, arguments, python),
    }


def run_build(project: Path | str) -> dict[str, Any]:
    """Build the images the compose file declares -- the button on the `Dockerfile` node."""
    return {"api_version": GRAPH_API_VERSION, **build_image(project).as_dict()}


def take_project_snapshot(project: Path | str) -> dict[str, Any]:
    """Record the current outline as the reference -- but only from a state that passed.

    A snapshot taken from broken code would make the breakage the thing everything after
    it is measured against, and the first honest repair would then read as a divergence.
    So the gate decides: static errors mean no snapshot, and the caller is told why.
    """
    root = Path(project)
    graph = read_project(root)
    result = check_graph(graph)

    if result.errors:
        return {
            "api_version": GRAPH_API_VERSION,
            "taken": False,
            "path": None,
            "refused": (
                f"the project has {len(result.errors)} unresolved error(s); a reference "
                "taken now would make the breakage the baseline"
            ),
        }

    path = save_snapshot(take_snapshot(graph), root)
    return {
        "api_version": GRAPH_API_VERSION,
        "taken": True,
        "path": str(path),
        "refused": None,
    }


def snapshot_status(project: Path | str) -> dict[str, Any]:
    """What no longer matches the reference. The `git status` question (§8)."""
    root = Path(project)
    snapshot = load_snapshot(root)
    if snapshot is None:
        return {"api_version": GRAPH_API_VERSION, "has_reference": False, "divergences": []}

    divergences = reconcile(snapshot, read_project(root))
    return {
        "api_version": GRAPH_API_VERSION,
        "has_reference": True,
        "divergences": [asdict(divergence) for divergence in divergences],
    }


def write_knob(project: Path | str, node: str, knob: str, value: Any) -> dict[str, Any]:
    """Write a knob's value into code, through the syntax tree."""
    result = set_knob(project, node, knob, value)
    return {"api_version": GRAPH_API_VERSION, **result.as_dict()}


def write_node_title(project: Path | str, node: str, title: str) -> dict[str, Any]:
    """Rename a node by editing the declaration it is named on."""
    result = set_node_title(project, node, title)
    return {"api_version": GRAPH_API_VERSION, **result.as_dict()}


def write_body(project: Path | str, node: str, function: str, source: str) -> dict[str, Any]:
    """Write a new body for one editable function of a node's carrier (Q15).

    The same `WRITE_SCHEMA` as the other two verbs, because it is the same kind of answer:
    a refusal is a result the panel shows, never a protocol fault -- a locked signature and
    a generated zone are both ordinary things for a person to try.
    """
    result = set_body(project, node, function, source)
    return {"api_version": GRAPH_API_VERSION, **result.as_dict()}


def repairs_available(project: Path | str) -> dict[str, Any]:
    """Every divergence, what may be done about it, and the request text for an agent."""
    return {"api_version": GRAPH_API_VERSION, "repairs": list_repairs(project)}


def repair_divergence(
    project: Path | str, code: str, target: str, resolution: str, observe: bool = True
) -> dict[str, Any]:
    """Resolve one divergence the way the caller chose.

    `resolution` is required here as it is everywhere below: §9's second case has two
    non-equivalent answers, and offering a default would be the toolchain choosing.
    """
    result = apply_repair(project, code=code, target=target, resolution=resolution, observe=observe)
    return {"api_version": GRAPH_API_VERSION, **result.as_dict()}


def agent_blueprints(catalog: Path | str | None = None) -> dict[str, Any]:
    """What input B can be given: the catalog's entries, without their texts."""
    root = find_catalog(catalog)
    # Resolved first, and listed only from what was resolved: `None` means "look for one"
    # further down, so passing it through would answer with a catalog nobody asked for.
    entries = list_blueprints(root) if root is not None else []
    return {
        "api_version": GRAPH_API_VERSION,
        "catalog": None if root is None else str(root),
        "blueprints": [
            {
                "id": blueprint.id,
                "title": blueprint.title,
                "summary": blueprint.summary,
                "path": blueprint.path,
                "section": blueprint.section,
            }
            for blueprint in entries
        ],
    }


def agent_brief(
    project: Path | str,
    request: str | None = None,
    blueprint: str | None = None,
    catalog: Path | str | None = None,
) -> dict[str, Any]:
    """Assemble the brief for either input.

    A brief that cannot be assembled -- nothing asked, or a blueprint the catalog does not
    have -- comes back as a refusal with its reason, the way a rejected write does. It is a
    normal answer to a normal question, not a fault in the call.
    """
    try:
        brief = build_brief(project, request=request, blueprint=blueprint, catalog=catalog)
    except ValueError as exc:
        return {"api_version": GRAPH_API_VERSION, "refused": str(exc), "brief": None}

    return {"api_version": GRAPH_API_VERSION, "refused": None, "brief": brief.as_dict()}


def agent_record(
    project: Path | str,
    source: str,
    request: str = "",
    blueprint: str | None = None,
    observe: bool = False,
    session: str | None = None,
    turn: int | None = None,
) -> dict[str, Any]:
    """Run the gates over what the agent produced and log what they said (§7).

    `session` and `turn` address the conversation turn this came from (Q16); both absent
    means nothing drove it from a session.
    """
    entry = record_outcome(
        project,
        source=source,
        request=request,
        blueprint=blueprint,
        observe=observe,
        session=session,
        turn=turn,
    )
    return {"api_version": GRAPH_API_VERSION, "entry": entry}


def agent_session(project: Path | str) -> dict[str, Any]:
    """Is there an agent on this machine, and is a session open? Starts nothing."""
    return {"api_version": GRAPH_API_VERSION, **session_status(project).as_dict()}


def agent_open(
    project: Path | str, resume: str | None = None, fork: bool = False
) -> dict[str, Any]:
    """Open a session: a new one, one continued by id, or one forked from it (Q16)."""
    return {"api_version": GRAPH_API_VERSION, **start_session(project, resume, fork).as_dict()}


def agent_say(project: Path | str, text: str) -> dict[str, Any]:
    """Send one turn. What comes back arrives through `agent.poll`, never through here."""
    return {"api_version": GRAPH_API_VERSION, **say(project, text).as_dict()}


def agent_poll(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What the agent has said since `offset`. The caller keeps the offset it was given."""
    return {"api_version": GRAPH_API_VERSION, **poll_session(project, offset).as_dict()}


def agent_shut(project: Path | str) -> dict[str, Any]:
    """Close the session -- this sidecar's, or one a crashed sidecar left behind."""
    return {"api_version": GRAPH_API_VERSION, **stop_session(project).as_dict()}


def agent_failures(project: Path | str) -> dict[str, Any]:
    """The agent's failure modes, tallied over every generation recorded here."""
    return {"api_version": GRAPH_API_VERSION, **failure_modes(project)}


def describe_kinds() -> dict[str, Any]:
    """The node-kind registry, for a client that has to pick shapes (§5.6)."""
    return {
        "api_version": GRAPH_API_VERSION,
        "kinds": [
            {
                "name": kind.name,
                "carriers": sorted(carrier.value for carrier in kind.carriers),
                "top_level": kind.top_level,
                "check": kind.check,
                "description": kind.description,
            }
            for kind in sorted(REGISTRY.values(), key=lambda kind: kind.name)
        ],
    }
