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

from framestack_core.agent import build_brief, failure_modes, record_outcome
from framestack_core.catalog import find_catalog, list_blueprints
from framestack_core.converse import (
    poll_talk,
    say_to,
    start_talk,
    stop_talk,
    talk_status,
)
from framestack_core.diagnostics import Code, describe
from framestack_core.environment import describe_environment, start_services, stop_services
from framestack_core.gate import GateMode, check_graph
from framestack_core.ir import Location
from framestack_core.kinds import REGISTRY, families, family_of
from framestack_core.layout import create_project, read_layout, write_layout
from framestack_core.observe import run_observations
from framestack_core.project import read_project
from framestack_core.reconcile import reconcile
from framestack_core.repair import apply_repair, list_repairs
from framestack_core.runner import (
    build_image,
    call_endpoint,
    call_server_tool,
    call_service,
    command_status,
    index_pipeline,
    inspect_server,
    project_commands,
    read_command_logs,
    read_logs,
    read_worker_logs,
    run_status,
    start_application,
    start_command,
    start_worker,
    stop_application,
    stop_command,
    stop_worker,
    worker_status,
)
from framestack_core.session import (
    COMMANDS,
    EFFORTS,
    MODELS,
    MODES,
    account,
    answer_permission,
    configure_session,
    forget_session,
    interrupt,
    poll_session,
    rename_session,
    say,
    session_status,
    sign_in,
    sign_out,
    start_session,
    stop_session,
)
from framestack_core.shell import (
    close_shell,
    list_shells,
    open_shell,
    read_shell,
    resize_shell,
    write_shell,
)
from framestack_core.snapshot import load_snapshot, save_snapshot, take_snapshot
from framestack_core.source import node_source
from framestack_core.verdict import Observation
from framestack_core.writer import set_body, set_knob, set_node_title

__all__ = [
    "AGENT_BLUEPRINTS_SCHEMA",
    "AGENT_BRIEF_SCHEMA",
    "AGENT_CHOICES_SCHEMA",
    "AGENT_SESSION_SCHEMA",
    "AGENT_FAILURES_SCHEMA",
    "AGENT_RECORD_SCHEMA",
    "ENVIRONMENT_SCHEMA",
    "GRAPH_API_VERSION",
    "RUN_CALL_SCHEMA",
    "env_call",
    "TALK_SCHEMA",
    "RUN_SCHEMA",
    "SHELL_SCHEMA",
    "SERVICE_SCHEMA",
    "GRAPH_KINDS_SCHEMA",
    "GRAPH_READ_SCHEMA",
    "LAYOUT_READ_SCHEMA",
    "LAYOUT_WRITE_SCHEMA",
    "COMMAND_LIST_SCHEMA",
    "MCP_CALL_SCHEMA",
    "MCP_INSPECT_SCHEMA",
    "RAG_INDEX_SCHEMA",
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
    "talk_close",
    "talk_open",
    "talk_poll",
    "talk_say",
    "talk_state",
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
    "agent_interrupt",
    "agent_permission",
    "agent_forget",
    "agent_rename",
    "agent_account",
    "agent_choices",
    "agent_configure",
    "agent_sign_in",
    "agent_sign_out",
    "agent_record",
    "describe_kinds",
    "create_new_project",
    "layout_get",
    "layout_put",
    "command_list",
    "command_logs",
    "shell_close",
    "shell_list",
    "shell_open",
    "shell_read",
    "shell_resize",
    "shell_write",
    "command_start",
    "command_state",
    "command_stop",
    "mcp_call",
    "mcp_inspect",
    "rag_index",
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
    "summary": "str",
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
    # Whether **anything is running**, which is what `env.up` started and therefore what the
    # button on the compose node reflects. Not the same as everything being reachable (Q24).
    "up": "bool",
    # Each declared service. `reachable` is a connection to the port it publishes -- the
    # question the application asks, and readiness is a connection rather than a status
    # field. `running` is docker's answer about the container, which is a different claim
    # and must never stand in for the first: the gap between them is where "I started it and
    # nothing works" lives.
    "services": [
        {
            "name": "str",
            "ports": ["int"],
            "reachable": "bool",
            "running": "bool",
            "dockerfile": "str?",
        }
    ],
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

#: The `talk.*` payload: one conversation with a node, in the project's own interpreter.
#:
#: The fourth instance of the P13 shape after `run.*`, `work.*` and `agent.*` -- which is why
#: it carries an offset and not a stream: the wire is one answer per request, and nothing is
#: ever pushed. What a conversation *is* belongs to the project (Q19): the events here are
#: what the project said, in the order it said it, and no history is assembled on this side.
TALK_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    # The node being talked to. A conversation is an action **on a node**, never a node of
    # its own (Q18) -- so it is addressed by one and there is nothing new on the graph.
    "node": "str",
    "running": "bool",
    # What the project said, normalised into one shape. `type` is the probe's own word for
    # what happened -- `ready`, `asked`, `answer`, `failed` -- and every event carries all
    # four fields, so a reader never has to ask whether a key is there before looking.
    "events": [{"type": "str", "text": "str", "detail": "str", "trace": "str"}],
    "offset": "int",
    # Which nodes have a conversation open here.
    "open": ["str"],
}

#: The `shell.*` payload: one terminal the person types into.
#:
#: The sixth instance of the P13 shape, and the only one that is **not a claim about the
#: graph**: a shell colours no node and proves no check, which is exactly why it may run what
#: `command.start` refuses (see `shell.py`). Output is polled with an offset the caller keeps.
SHELL_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "shell": "str",
    "running": "bool",
    "output": "str",
    "offset": "int",
    # Every terminal open for this project, so a panel draws its tabs from one answer.
    "shells": [{"id": "str", "name": "str", "running": "bool", "pid": "int"}],
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
    "observations": {"<key>": {"passed": "bool", "check": "str", "detail": "str?", "by": "str"}},
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

#: The `command.list` payload: the commands the project already has (P17.6).
#:
#: Nothing here is on the graph and nothing here has a verdict (Q20): a front end is run, not
#: modelled, and what a person gets is a list the tool itself produced and a choice. The list
#: is npm's own answer about npm's own file -- asked, never read (§5.8).
COMMAND_LIST_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "commands": [{"name": "str", "command": "str"}],
    # Where they were asked for, relative to the project. Passed in by the caller and never
    # discovered: what the tool offers must not depend on the shape of somebody's disk.
    "directory": "str",
}

#: The `rag.index` payload: what the store said after the pipeline was handed its documents.
#:
#: `held` is what the store answered `len` with, or "" when it does not answer that question
#: -- never the number of documents that went in (P17.5). Reporting our own side of the
#: exchange as though it were the store's is the one thing this verb must not do.
RAG_INDEX_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "status": "str",
    "detail": "str",
    "held": "str",
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

#: The `node.source` payload: the code a node carries, read from disk.
#:
#: A read of its own rather than a field on `graph.read`, because the IR deliberately holds no
#: editable body (I-1: one copy of the code, and it is the file). So the panel that shows code
#: asks for it, for one node, at the moment somebody opens the tab.
NODE_SOURCE_SCHEMA = {
    "api_version": "int",
    "node": "str",
    "file": "str",
    "source": "str",
    "functions": [
        {
            "path": "str",
            "zone": "str?",
            "signature": "str",
            "signature_locked": "bool",
            "location": _LOCATION,
            "source": "str",
        }
    ],
    # A node that is not on the graph is a normal answer, not a fault in the call.
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
    # Every family, in the order the registry declares them -- which is grouped by
    # technology and ordered by the phase that added each, and is more use to a reader than
    # the alphabet. Sent rather than derived by the client for the same reason `family` is:
    # a family exists because a kind named it, and there is no second list to disagree.
    "families": ["str"],
    "kinds": [
        {
            "name": "str",
            # The family the kind belongs to, from the registry's own rule rather than from
            # a client splitting the name on a dot. The library groups by it (P19), and a
            # family exists because a kind named it -- there is no separate list of families
            # anywhere, here or in the interface, that could disagree with the registry.
            "family": "str",
            "carriers": ["str"],
            # The paths that carry a file-carried kind, or []. For those kinds "what carries
            # this" is a filename, and answering it with `file` alone tells a reader nothing
            # about which file (§5.7).
            "artifact": ["str"],
            "top_level": "bool",
            "check": "str",
            # How a person talks to this kind, or "" for the ones nobody can talk to. This
            # is what decides whether a node gets the button at all -- so a client shows one
            # because the registry said so, never because a carrier looked conversational.
            "converses": "str",
            # And whether it holds an index somebody can hand documents to (P17.5). Same
            # rule as `converses`: the button exists because the registry named a way in.
            "indexes": "str",
            # Which family of process verb starts and stops it -- `run`, `work`, `env` -- or
            # "" for the kinds nothing starts. The same opt-in again, and it answers the one
            # question the graph cannot: a graph is a projection of code, and whether a pid
            # is alive is not in the code.
            "starts": "str",
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
    # One step of a turn. `detail` is what a tool was called with, or what it answered;
    # `id` is the agent's own `tool_use_id`, which is what lets a result be shown against the
    # call it answers rather than merely after it. Both are "" where they do not apply.
    # One step of a turn. `detail` is what a tool was called with or what it answered; `id`
    # is the agent's own `tool_use_id`, which is what pairs a result with the call it answers
    # rather than merely following it; `tool` is the agent's name for what it called.
    "events": [
        {
            "kind": "str",
            "text": "str",
            "file": "str",
            "detail": "str",
            "id": "str",
            "tool": "str",
            # Only an `asking` carries this, and only once somebody has pressed something:
            # `""` is a request still waiting, and it is a different state from "denied"
            # (Q21). `id` on an `asking` is the agent's `request_id` -- what an answer is
            # addressed by -- rather than a `tool_use_id`.
            "answer": "str",
        }
    ],
    # Where the reader got to. Events are polled, never pushed (P13).
    "offset": "int",
    # The conversations this project has had -- ids and labels, never a transcript.
    "sessions": [{"id": "str", "label": "str", "at": "str"}],
    # Tokens the last turn carried. A **number, never a percentage**: the window to divide by
    # belongs to the model, which is reported beside it rather than assumed.
    "context": "int",
    # Which model is answering, as the agent named it. Empty until it has said.
    "model": "str",
    # The agent's own running estimate of what the turn has cost so far. Usage proper is
    # reported exactly twice in a turn -- at the start of a message and at its end -- so a
    # number that *moves* while it works is the agent's estimate or it is nobody's.
    "spending": "int",
    # What the agent says it can be asked to do -- **names only**, because names only is what
    # it sends. Empty from a poll that carried no `init`; the caller keeps the last list.
    "commands": ["str"],
    # How this project's sessions are started. All three are **flags at spawn** -- there is no
    # way to change one in a running conversation -- so setting one restarts the process under
    # `--resume`, which keeps the conversation and not the process it was being had in.
    # Null where the verb was not asked -- absent is not the same as "no model, no effort".
    "settings": {
        "<nullable>": {
            "model": "str",
            "effort": "str",
            "mode": "str",
            # Whether the agent may run commands. Not the mode: no permission mode grants
            # Bash, and a person saying "yes" once is what makes the project's tests runnable.
            "commands": "str",
        }
    },
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
            node: {"passed": o.passed, "check": o.check, "detail": o.detail, "by": o.by}
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


def talk_open(project: Path | str, node: str, python: str | None = None) -> dict[str, Any]:
    """Open a conversation with one node. Never implicit -- somebody pressed a button (P11)."""
    return {"api_version": GRAPH_API_VERSION, **start_talk(project, node, python).as_dict()}


def talk_say(project: Path | str, node: str, text: str) -> dict[str, Any]:
    """Ask one thing. What comes back arrives through `talk.poll`, never through here."""
    return {"api_version": GRAPH_API_VERSION, **say_to(project, node, text).as_dict()}


def talk_poll(project: Path | str, node: str, offset: int = 0) -> dict[str, Any]:
    """What the node has said since `offset`. The caller keeps the offset it was given."""
    return {"api_version": GRAPH_API_VERSION, **poll_talk(project, node, offset).as_dict()}


def talk_state(project: Path | str) -> dict[str, Any]:
    """Which nodes have a conversation open. Reads; starts nothing."""
    return {"api_version": GRAPH_API_VERSION, **talk_status(project).as_dict()}


def talk_close(project: Path | str, node: str) -> dict[str, Any]:
    """Close one conversation -- this sidecar's, or one a crashed sidecar left behind."""
    return {"api_version": GRAPH_API_VERSION, **stop_talk(project, node).as_dict()}


def env_call(
    project: Path | str,
    service: str,
    path: str = "/",
    method: str = "GET",
    port: int = 0,
) -> dict[str, Any]:
    """Call a declared service on the port it publishes. The port is asked of docker (Q24)."""
    return {
        "api_version": GRAPH_API_VERSION,
        **call_service(project, service, path, method, port).as_dict(),
    }


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


def command_list(project: Path | str, directory: str = "") -> dict[str, Any]:
    """The commands this project already has, asked of npm itself (P17.6)."""
    return {"api_version": GRAPH_API_VERSION, **project_commands(project, directory).as_dict()}


def command_start(project: Path | str, command: str, directory: str = "") -> dict[str, Any]:
    """Run one of them and leave it running. Each process is started on its own (Q20)."""
    started = start_command(project, command, directory)
    return {"api_version": GRAPH_API_VERSION, **started.as_dict()}


def command_state(project: Path | str) -> dict[str, Any]:
    """Is it still running? That question and no other -- readiness is not ours to claim."""
    return {"api_version": GRAPH_API_VERSION, **command_status(project).as_dict()}


def shell_open(project: Path | str, name: str = "") -> dict[str, Any]:
    """Open one terminal in the project's directory. Never implicit (P11)."""
    return {"api_version": GRAPH_API_VERSION, **open_shell(project, name).as_dict()}


def shell_write(project: Path | str, shell: str, text: str) -> dict[str, Any]:
    """Type into it. What is sent is what was typed -- not even a newline is added."""
    return {"api_version": GRAPH_API_VERSION, **write_shell(project, shell, text).as_dict()}


def shell_read(project: Path | str, shell: str, offset: int = 0) -> dict[str, Any]:
    """What it printed since `offset`. The caller keeps the offset it was given (P13)."""
    return {"api_version": GRAPH_API_VERSION, **read_shell(project, shell, offset).as_dict()}


def shell_resize(project: Path | str, shell: str, columns: int, rows: int) -> dict[str, Any]:
    """Tell it how wide its window is -- the one thing wrapping programs read."""
    return {
        "api_version": GRAPH_API_VERSION,
        **resize_shell(project, shell, columns, rows).as_dict(),
    }


def shell_close(project: Path | str, shell: str) -> dict[str, Any]:
    """Close it, and the process group it started with it."""
    return {"api_version": GRAPH_API_VERSION, **close_shell(project, shell).as_dict()}


def shell_list(project: Path | str) -> dict[str, Any]:
    """The terminals open here. A read: it opens nothing."""
    return {"api_version": GRAPH_API_VERSION, **list_shells(project).as_dict()}


def command_logs(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What it has printed since `offset`. Polled by the caller, never pushed (P13)."""
    return {"api_version": GRAPH_API_VERSION, **read_command_logs(project, offset).as_dict()}


def command_stop(project: Path | str) -> dict[str, Any]:
    """Stop it -- this session's, or one a crashed session left behind."""
    return {"api_version": GRAPH_API_VERSION, **stop_command(project).as_dict()}


def rag_index(project: Path | str, node: str, python: str | None = None) -> dict[str, Any]:
    """Hand the pipeline its documents (P17.5). A press, never a consequence of reading."""
    return {"api_version": GRAPH_API_VERSION, **index_pipeline(project, node, python)}


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


def read_source(project: Path | str, node: str) -> dict[str, Any]:
    """The code one node carries, as it is on disk -- what the node's code tab shows."""
    return {"api_version": GRAPH_API_VERSION, **node_source(project, node).as_dict()}


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


def agent_say(
    project: Path | str,
    text: str,
    images: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    """Send one turn. What comes back arrives through `agent.poll`, never through here."""
    return {"api_version": GRAPH_API_VERSION, **say(project, text, images).as_dict()}


def agent_poll(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What the agent has said since `offset`. The caller keeps the offset it was given."""
    return {"api_version": GRAPH_API_VERSION, **poll_session(project, offset).as_dict()}


def agent_permission(
    project: Path | str,
    request: str,
    allow: bool,
    always: bool = False,
) -> dict[str, Any]:
    """Answer one standing request for permission. The turn resumes from where it stopped."""
    return {
        "api_version": GRAPH_API_VERSION,
        **answer_permission(project, request, allow, always).as_dict(),
    }


def agent_interrupt(project: Path | str) -> dict[str, Any]:
    """Stop the turn that is running. The conversation and its process both survive."""
    return {"api_version": GRAPH_API_VERSION, **interrupt(project).as_dict()}


def agent_shut(project: Path | str) -> dict[str, Any]:
    """Close the session -- this sidecar's, or one a crashed sidecar left behind."""
    return {"api_version": GRAPH_API_VERSION, **stop_session(project).as_dict()}


def agent_forget(project: Path | str, session: str) -> dict[str, Any]:
    """Drop one conversation from this project's list -- our reference, not the transcript."""
    return {"api_version": GRAPH_API_VERSION, **forget_session(project, session).as_dict()}


#: The `agent.account` payload: who the agent is signed in as.
#:
#: Read from the CLI, never held here. The credential belongs to the agent, which put it on
#: this machine through its own browser flow -- the core has no HTTP client to a model and no
#: SDK (Q16), so there is nothing to store. What this answers is the question the application
#: could not answer before: whose account is a turn about to spend?
AGENT_ACCOUNT_SCHEMA = {
    "api_version": "int",
    "signed_in": "bool",
    "method": "str",
    "email": "str",
    "plan": "str",
    "organisation": "str",
    # Why not, when the answer is no. Never a guess about what went wrong.
    "detail": "str",
}


def agent_account() -> dict[str, Any]:
    """Who the agent is signed in as. Asks; signs nobody in."""
    return {"api_version": GRAPH_API_VERSION, **account().as_dict()}


def agent_sign_in(console: bool = False) -> dict[str, Any]:
    """Run the agent's own browser sign-in and report what it left behind."""
    return {"api_version": GRAPH_API_VERSION, **sign_in(console).as_dict()}


def agent_sign_out() -> dict[str, Any]:
    """Sign the agent out. Ours to ask for, the CLI's to carry out."""
    return {"api_version": GRAPH_API_VERSION, **sign_out().as_dict()}


def agent_rename(project: Path | str, session: str, label: str) -> dict[str, Any]:
    """Name one conversation. The label is the person's; everything else about it is not."""
    return {"api_version": GRAPH_API_VERSION, **rename_session(project, session, label).as_dict()}


#: The `agent.choices` payload: what a session may be set to.
#:
#: Asked rather than hard-coded on the far side: the offered set is a fact about which flags
#: this agent honours, and one of them (`manual`) is accepted and ignored, which is exactly
#: the kind of thing a menu written from documentation gets wrong.
AGENT_CHOICES_SCHEMA = {
    "api_version": "int",
    "models": ["str"],
    "efforts": ["str"],
    "modes": ["str"],
    "commands": ["str"],
}


def agent_choices() -> dict[str, Any]:
    """What a session may be set to. A statement about the agent, not about the project."""
    return {
        "api_version": GRAPH_API_VERSION,
        "models": list(MODELS),
        "efforts": list(EFFORTS),
        "modes": list(MODES),
        # Whether the agent may run commands. A separate choice from the mode because it is
        # a separate mechanism: no permission mode grants Bash, and this is what does.
        "commands": list(COMMANDS),
    }


def agent_configure(
    project: Path | str,
    model: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    commands: str | None = None,
) -> dict[str, Any]:
    """Set what sessions here are started with, restarting the open one onto it."""
    return {
        "api_version": GRAPH_API_VERSION,
        **configure_session(
            project, model=model, effort=effort, mode=mode, commands=commands
        ).as_dict(),
    }


def agent_failures(project: Path | str) -> dict[str, Any]:
    """The agent's failure modes, tallied over every generation recorded here."""
    return {"api_version": GRAPH_API_VERSION, **failure_modes(project)}


def describe_kinds() -> dict[str, Any]:
    """The node-kind registry, for a client that has to pick shapes (§5.6)."""
    return {
        "api_version": GRAPH_API_VERSION,
        "families": list(families()),
        "kinds": [
            {
                "name": kind.name,
                "family": family_of(kind.name),
                "carriers": sorted(carrier.value for carrier in kind.carriers),
                "artifact": list(kind.artifact),
                "top_level": kind.top_level,
                "check": kind.check,
                "converses": kind.converses,
                "indexes": kind.indexes,
                "starts": kind.starts,
                "description": kind.description,
            }
            for kind in sorted(REGISTRY.values(), key=lambda kind: kind.name)
        ],
    }
