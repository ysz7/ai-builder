"""Method handlers.

Every capability the shell can reach is a method here. That is the whole extension point:
the Rust side has one command and forwards it, so a new capability is a new entry in
`HANDLERS` and never a new command in Rust.

Handlers assemble; they do not decide. `graph.read` calls the parser and the gate and
returns what the two of them said.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from typing import Any

from aibuilder_core.api import (
    agent_blueprints,
    agent_brief,
    agent_failures,
    agent_record,
    describe_kinds,
    environment_status,
    mcp_call,
    mcp_inspect,
    read_graph,
    repair_divergence,
    repairs_available,
    run_build,
    run_call,
    run_logs,
    run_start,
    run_state,
    run_stop,
    services_start,
    services_stop,
    snapshot_status,
    take_project_snapshot,
    work_logs,
    work_start,
    work_state,
    work_stop,
    write_knob,
    write_node_title,
)
from aibuilder_core.gate import GateMode
from aibuilder_core.protocol import PROTOCOL_VERSION, ProtocolError

Handler = Callable[[dict[str, Any]], Any]


def _libcst_version() -> str:
    """libcst exposes no __version__; ask the installed distribution instead.

    A PyInstaller bundle may carry no distribution metadata, so this must not be
    allowed to fail -- it is diagnostic information, not a dependency.
    """
    import importlib.metadata

    try:
        return importlib.metadata.version("libcst")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def ping(params: dict[str, Any]) -> dict[str, Any]:
    """Liveness probe. Echoes back enough to prove which core answered."""
    import libcst  # imported here so a broken install surfaces as a ping failure

    assert libcst is not None

    return {
        "pong": True,
        "echo": params.get("echo"),
        "protocol_version": PROTOCOL_VERSION,
        "python": platform.python_version(),
        "libcst": _libcst_version(),
        "frozen": getattr(sys, "frozen", False),
    }


def graph_read(params: dict[str, Any]) -> dict[str, Any]:
    """Read a project into a graph, with its diagnostics and verdicts.

    `mode` selects gate strictness. It defaults to soft (§7): in v0 a violation flags the
    node and offers a repair, it does not refuse the code.

    `observe` runs the observable checks as well, which executes the project. Off by
    default: a read must not have side effects the caller did not ask for.
    """
    project = _project_of(params)

    requested = params.get("mode", GateMode.SOFT.value)
    try:
        mode = GateMode(requested)
    except ValueError:
        allowed = ", ".join(sorted(item.value for item in GateMode))
        raise ProtocolError("invalid_params", f"'mode' must be one of: {allowed}") from None

    observe = params.get("observe", False)
    if not isinstance(observe, bool):
        raise ProtocolError("invalid_params", "'observe' must be true or false")

    return read_graph(project, mode=mode, observe=observe, python=_optional_str(params, "python"))


def env_status(params: dict[str, Any]) -> dict[str, Any]:
    """Describe the environment. Reads; starts nothing."""
    return environment_status(_project_of(params), _optional_str(params, "python"))


def env_up(params: dict[str, Any]) -> dict[str, Any]:
    """Bring the declared services up -- the button on the compose file's node (§5.7).

    A method of its own rather than a flag on `graph.read`: starting containers is not
    something a caller should be able to do by accident while asking a question.
    """
    return services_start(_project_of(params), _optional_str(params, "python"))


def env_down(params: dict[str, Any]) -> dict[str, Any]:
    """Take them down again."""
    return services_stop(_project_of(params))


def _project_of(params: dict[str, Any]) -> str:
    project = params.get("project")
    if not isinstance(project, str) or not project:
        raise ProtocolError("invalid_params", "'project' must be a non-empty path string")
    return project


def snapshot_take(params: dict[str, Any]) -> dict[str, Any]:
    """Make the current outline the reference, if the gate lets it."""
    return take_project_snapshot(_project_of(params))


def snapshot_status_method(params: dict[str, Any]) -> dict[str, Any]:
    """What diverged from the reference. Asked on open and on demand -- never watched."""
    return snapshot_status(_project_of(params))


def _required_str(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise ProtocolError("invalid_params", f"{name!r} must be a non-empty string")
    return value


def knob_set(params: dict[str, Any]) -> dict[str, Any]:
    """Set a knob's value. Refusals come back as a result, not as an error.

    A value outside the knob's declared bounds is a normal answer to a normal question --
    the UI shows why and the user picks again -- not a protocol fault.
    """
    if "value" not in params:
        raise ProtocolError("invalid_params", "'value' is required")

    return write_knob(
        _project_of(params),
        _required_str(params, "node"),
        _required_str(params, "knob"),
        params["value"],
    )


def node_set_title(params: dict[str, Any]) -> dict[str, Any]:
    """Rename a node."""
    return write_node_title(
        _project_of(params),
        _required_str(params, "node"),
        _required_str(params, "title"),
    )


def repair_list(params: dict[str, Any]) -> dict[str, Any]:
    """What diverged, and what may be done about each."""
    return repairs_available(_project_of(params))


def repair_apply(params: dict[str, Any]) -> dict[str, Any]:
    """Resolve one divergence.

    `resolution` is required with no default. A generated-zone divergence has two
    non-equivalent answers (§9 case 2), and a default here would be the toolchain making
    the choice while appearing not to.
    """
    observe = params.get("observe", True)
    if not isinstance(observe, bool):
        raise ProtocolError("invalid_params", "'observe' must be true or false")

    return repair_divergence(
        _project_of(params),
        _required_str(params, "code"),
        _required_str(params, "target"),
        _required_str(params, "resolution"),
        observe,
    )


def _optional_str(params: dict[str, Any], name: str) -> str | None:
    value = params.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError("invalid_params", f"{name!r} must be a non-empty string when given")
    return value


def agent_blueprints_method(params: dict[str, Any]) -> dict[str, Any]:
    """What input B can be given. An absent catalog is an answer, not an error."""
    return agent_blueprints(_optional_str(params, "catalog"))


def agent_brief_method(params: dict[str, Any]) -> dict[str, Any]:
    """Assemble the brief for a chat request, a blueprint, or both (§3).

    The two inputs are one method because they are one mechanism: they differ in how
    detailed the request is and in nothing else. A second method here would be the first
    step towards two sets of rules.
    """
    return agent_brief(
        _project_of(params),
        _optional_str(params, "request"),
        _optional_str(params, "blueprint"),
        _optional_str(params, "catalog"),
    )


def agent_record_method(params: dict[str, Any]) -> dict[str, Any]:
    """Log what the gates said about a generation -- the soft mode's whole purpose (§7)."""
    observe = params.get("observe", False)
    if not isinstance(observe, bool):
        raise ProtocolError("invalid_params", "'observe' must be true or false")

    return agent_record(
        _project_of(params),
        _required_str(params, "source"),
        _optional_str(params, "request") or "",
        _optional_str(params, "blueprint"),
        observe,
    )


def agent_failures_method(params: dict[str, Any]) -> dict[str, Any]:
    """The agent's failure modes, tallied."""
    return agent_failures(_project_of(params))


def run_start_method(params: dict[str, Any]) -> dict[str, Any]:
    """Start the application. Returns when it answers; never holds the wire open (P13)."""
    port = params.get("port")
    if port is not None and not isinstance(port, int):
        raise ProtocolError("invalid_params", "'port' must be a number when given")

    return run_start(_project_of(params), _optional_str(params, "python"), port)


def run_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    return run_stop(_project_of(params))


def run_status_method(params: dict[str, Any]) -> dict[str, Any]:
    return run_state(_project_of(params))


def run_logs_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll the log. The caller keeps the offset it was last given."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")

    return run_logs(_project_of(params), offset)


def run_call_method(params: dict[str, Any]) -> dict[str, Any]:
    """Call the running application and hand back what it said."""
    return run_call(
        _project_of(params),
        _optional_str(params, "path") or "/",
        _optional_str(params, "method") or "GET",
    )


def run_build_method(params: dict[str, Any]) -> dict[str, Any]:
    return run_build(_project_of(params))


def work_start_method(params: dict[str, Any]) -> dict[str, Any]:
    """Start a worker. Refuses when the broker is down; never starts it (P11)."""
    return work_start(_project_of(params), _optional_str(params, "python"))


def work_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    return work_stop(_project_of(params))


def work_status_method(params: dict[str, Any]) -> dict[str, Any]:
    return work_state(_project_of(params), _optional_str(params, "python"))


def work_logs_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll the worker's log. The caller keeps the offset it was last given."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")

    return work_logs(_project_of(params), offset)


def mcp_inspect_method(params: dict[str, Any]) -> dict[str, Any]:
    """Connect to a consumed server and list what it offers.

    A method of its own rather than a flag on `graph.read`, for the same reason `env.up` is:
    reaching a third party's program is not something a caller should be able to do by
    accident while asking a question (P11).
    """
    return mcp_inspect(
        _project_of(params), _required_str(params, "node"), _optional_str(params, "python")
    )


def mcp_call_method(params: dict[str, Any]) -> dict[str, Any]:
    """Call one tool on that server. `arguments` is what a person typed -- never invented."""
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ProtocolError("invalid_params", "'arguments' must be an object")

    return mcp_call(
        _project_of(params),
        _required_str(params, "node"),
        _required_str(params, "tool"),
        arguments,
        _optional_str(params, "python"),
    )


def graph_kinds(params: dict[str, Any]) -> dict[str, Any]:
    """The node-kind registry, so a client can pick shapes without guessing."""
    return describe_kinds()


HANDLERS: dict[str, Handler] = {
    "ping": ping,
    "graph.read": graph_read,
    "graph.kinds": graph_kinds,
    "snapshot.take": snapshot_take,
    "snapshot.status": snapshot_status_method,
    "knob.set": knob_set,
    "node.set_title": node_set_title,
    "repair.list": repair_list,
    "repair.apply": repair_apply,
    "agent.brief": agent_brief_method,
    "agent.blueprints": agent_blueprints_method,
    "agent.record": agent_record_method,
    "agent.failures": agent_failures_method,
    "env.status": env_status,
    "env.up": env_up,
    "env.down": env_down,
    "run.start": run_start_method,
    "run.stop": run_stop_method,
    "run.status": run_status_method,
    "run.logs": run_logs_method,
    "run.call": run_call_method,
    "run.build": run_build_method,
    "work.start": work_start_method,
    "work.stop": work_stop_method,
    "work.status": work_status_method,
    "work.logs": work_logs_method,
    "mcp.inspect": mcp_inspect_method,
    "mcp.call": mcp_call_method,
}


def dispatch(method: str, params: dict[str, Any], request_id: Any = None) -> Any:
    handler = HANDLERS.get(method)
    if handler is None:
        raise ProtocolError("unknown_method", f"unknown method {method!r}", request_id)
    return handler(params)
