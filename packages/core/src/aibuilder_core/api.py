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
from aibuilder_core.gate import GateMode, check_graph
from aibuilder_core.kinds import REGISTRY
from aibuilder_core.observe import run_observations
from aibuilder_core.parser import parse_project
from aibuilder_core.reconcile import reconcile
from aibuilder_core.repair import apply_repair, list_repairs
from aibuilder_core.snapshot import load_snapshot, save_snapshot, take_snapshot
from aibuilder_core.verdict import Observation
from aibuilder_core.writer import set_knob, set_node_title

__all__ = [
    "AGENT_BLUEPRINTS_SCHEMA",
    "AGENT_BRIEF_SCHEMA",
    "AGENT_FAILURES_SCHEMA",
    "AGENT_RECORD_SCHEMA",
    "GRAPH_API_VERSION",
    "GRAPH_KINDS_SCHEMA",
    "GRAPH_READ_SCHEMA",
    "SNAPSHOT_STATUS_SCHEMA",
    "SNAPSHOT_TAKE_SCHEMA",
    "REPAIR_APPLY_SCHEMA",
    "REPAIR_LIST_SCHEMA",
    "WRITE_SCHEMA",
    "agent_blueprints",
    "agent_brief",
    "agent_failures",
    "agent_record",
    "describe_kinds",
    "read_graph",
    "snapshot_status",
    "take_project_snapshot",
    "repair_divergence",
    "repairs_available",
    "write_knob",
    "write_node_title",
]

#: Bumped when the payload's shape changes in a way a client would notice. Additive fields
#: do not bump it; removing or retyping one does.
GRAPH_API_VERSION = 1


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
    "mode": "str",
    "accepted": "bool",
}

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
    "diagnostics": [
        {"code": "str", "severity": "str", "rule": "str", "node": "str?", "address": "str"}
    ],
    "verdicts": {"<key>": "str"},
    "accepted": "bool",
    "versions": {"<key>": "str?"},
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
    graph = parse_project(root)

    skipped: dict[str, str] = {}
    if observe and observations is None:
        run = run_observations(graph, root)
        observations, skipped = run.observations, run.skipped

    result = check_graph(graph, mode=mode, observations=observations)

    return {
        "api_version": GRAPH_API_VERSION,
        "root": graph.root,
        "graph": graph.to_dict(),
        "diagnostics": [asdict(diagnostic) for diagnostic in result.diagnostics],
        "verdicts": result.verdicts,
        "observations": {
            node: {"passed": o.passed, "check": o.check, "detail": o.detail}
            for node, o in (observations or {}).items()
        },
        "skipped": skipped,
        "mode": result.mode,
        "accepted": result.accepted,
    }


def take_project_snapshot(project: Path | str) -> dict[str, Any]:
    """Record the current outline as the reference -- but only from a state that passed.

    A snapshot taken from broken code would make the breakage the thing everything after
    it is measured against, and the first honest repair would then read as a divergence.
    So the gate decides: static errors mean no snapshot, and the caller is told why.
    """
    root = Path(project)
    graph = parse_project(root)
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

    divergences = reconcile(snapshot, parse_project(root))
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
) -> dict[str, Any]:
    """Run the gates over what the agent produced and log what they said (§7)."""
    entry = record_outcome(
        project, source=source, request=request, blueprint=blueprint, observe=observe
    )
    return {"api_version": GRAPH_API_VERSION, "entry": entry}


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
