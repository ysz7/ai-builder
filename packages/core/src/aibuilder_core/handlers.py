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
    agent_account,
    agent_blueprints,
    agent_brief,
    agent_choices,
    agent_configure,
    agent_failures,
    agent_forget,
    agent_interrupt,
    agent_open,
    agent_poll,
    agent_record,
    agent_rename,
    agent_say,
    agent_session,
    agent_shut,
    agent_sign_in,
    agent_sign_out,
    command_list,
    command_logs,
    command_start,
    command_state,
    command_stop,
    create_new_project,
    describe_kinds,
    environment_status,
    layout_get,
    layout_put,
    mcp_call,
    mcp_inspect,
    rag_index,
    read_graph,
    read_source,
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
    talk_close,
    talk_open,
    talk_poll,
    talk_say,
    talk_state,
    work_logs,
    work_start,
    work_state,
    work_stop,
    write_body,
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


def node_source_method(params: dict[str, Any]) -> dict[str, Any]:
    """The code one node carries. Reads a file; runs nothing, imports nothing."""
    return read_source(_project_of(params), _required_str(params, "node"))


def node_set_body(params: dict[str, Any]) -> dict[str, Any]:
    """Write a new body for one of a node's editable functions.

    Addressed by node **and** function: I-6 says code is edited through a node, so a verb
    that took a bare path would be a second way in that quietly bypasses it.
    """
    source = params.get("source")
    if not isinstance(source, str):
        raise ProtocolError("invalid_params", "'source' must be a string")

    return write_body(
        _project_of(params),
        _required_str(params, "node"),
        _required_str(params, "function"),
        source,
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
    """Log what the gates said about a generation -- the soft mode's whole purpose (§7).

    `session` and `turn` say which turn of which conversation this was (Q16). Optional,
    because a generation driven by hand belongs in the log just as much as one from a chat.
    """
    observe = params.get("observe", False)
    if not isinstance(observe, bool):
        raise ProtocolError("invalid_params", "'observe' must be true or false")

    turn = params.get("turn")
    if turn is not None and (not isinstance(turn, int) or isinstance(turn, bool)):
        raise ProtocolError("invalid_params", "'turn' must be a number when given")

    return agent_record(
        _project_of(params),
        _required_str(params, "source"),
        _optional_str(params, "request") or "",
        _optional_str(params, "blueprint"),
        observe,
        _optional_str(params, "session"),
        turn,
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


def talk_open_method(params: dict[str, Any]) -> dict[str, Any]:
    """Open a conversation with one node, in the project's own interpreter (P17.1).

    Addressed by node, because a conversation is an action **on a node** and never a node of
    its own (Q18): there is nothing new on the graph to address it by.
    """
    return talk_open(
        _project_of(params),
        _required_str(params, "node"),
        _optional_str(params, "python") or None,
    )


def talk_say_method(params: dict[str, Any]) -> dict[str, Any]:
    """Ask one thing. The answer arrives through `talk.poll`, not through this call."""
    return talk_say(
        _project_of(params), _required_str(params, "node"), _required_str(params, "text")
    )


def talk_poll_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll one conversation. The caller keeps the offset it was last given (P13)."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")

    return talk_poll(_project_of(params), _required_str(params, "node"), offset)


def talk_state_method(params: dict[str, Any]) -> dict[str, Any]:
    """Which nodes have a conversation open. A read: it starts nothing (P11)."""
    return talk_state(_project_of(params))


def talk_close_method(params: dict[str, Any]) -> dict[str, Any]:
    """Close one conversation -- this sidecar's, or one a crashed sidecar left behind."""
    return talk_close(_project_of(params), _required_str(params, "node"))


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


def agent_session_method(params: dict[str, Any]) -> dict[str, Any]:
    """Is there an agent, and is a session open? Reads; starts nothing."""
    return agent_session(_project_of(params))


def agent_start_method(params: dict[str, Any]) -> dict[str, Any]:
    """Open a session with the agent.

    A method of its own rather than a flag on anything, for the reason `env.up` is: starting
    somebody else's program is not something a caller should do by accident (P11).

    `resume` continues a conversation the agent already has; `fork` branches from it and
    leaves the original alone -- which is what "do that again differently" has to mean if the
    first attempt is not to be lost.
    """
    fork = params.get("fork", False)
    if not isinstance(fork, bool):
        raise ProtocolError("invalid_params", "'fork' must be true or false")

    return agent_open(_project_of(params), _optional_str(params, "resume"), fork)


def agent_say_method(params: dict[str, Any]) -> dict[str, Any]:
    """Send one turn, with any pictures pasted into it.

    A picture arrives as base64 with the type it was copied as -- what is on a clipboard is
    bytes, and there is no file to point at. Whether the agent will read it is checked in
    `say`, before the line is written to a pipe nobody can take it back out of.
    """
    given = params.get("images", [])
    if not isinstance(given, list):
        raise ProtocolError("invalid_params", "'images' must be a list")
    images: list[dict[str, str]] = []
    for picture in given:
        if not isinstance(picture, dict):
            raise ProtocolError("invalid_params", "each image must be an object")
        media = picture.get("media_type")
        data = picture.get("data")
        if not isinstance(media, str) or not isinstance(data, str):
            raise ProtocolError(
                "invalid_params", "each image needs a 'media_type' and base64 'data'"
            )
        images.append({"media_type": media, "data": data})
    return agent_say(_project_of(params), _required_str(params, "text"), tuple(images))


def agent_poll_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll the session. The caller keeps the offset it was last given."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")

    return agent_poll(_project_of(params), offset)


def agent_forget_method(params: dict[str, Any]) -> dict[str, Any]:
    """Forget one conversation. Closes it first when it is the one running."""
    return agent_forget(_project_of(params), _required_str(params, "session"))


def agent_account_method(params: dict[str, Any]) -> dict[str, Any]:
    """Who is signed in. A read: it starts no session and signs nobody in."""
    return agent_account()


def agent_sign_in_method(params: dict[str, Any]) -> dict[str, Any]:
    """Open the agent's own browser sign-in. Never implicit -- somebody pressed it (P11)."""
    console = params.get("console", False)
    if not isinstance(console, bool):
        raise ProtocolError("invalid_params", "'console' must be true or false")
    return agent_sign_in(console)


def agent_sign_out_method(params: dict[str, Any]) -> dict[str, Any]:
    return agent_sign_out()


def agent_rename_method(params: dict[str, Any]) -> dict[str, Any]:
    """Name one conversation. An empty name restores the default rather than clearing it."""
    label = params.get("label", "")
    if not isinstance(label, str):
        raise ProtocolError("invalid_params", "'label' must be a string")
    return agent_rename(_project_of(params), _required_str(params, "session"), label)


def agent_choices_method(params: dict[str, Any]) -> dict[str, Any]:
    """What a session may be set to. A read about the agent; it touches no project."""
    return agent_choices()


def agent_configure_method(params: dict[str, Any]) -> dict[str, Any]:
    """Set model, effort or permission mode. Restarts the open conversation onto it.

    Absent means "leave it", which is not the same as `""` -- the deliberate choice of the
    agent's own default. So a missing key is `None` and an empty string is a value.
    """
    given: dict[str, str | None] = {}
    for name in ("model", "effort", "mode"):
        if name not in params:
            given[name] = None
            continue
        value = params[name]
        if not isinstance(value, str):
            raise ProtocolError("invalid_params", f"'{name}' must be a string")
        given[name] = value
    return agent_configure(
        _project_of(params),
        model=given["model"],
        effort=given["effort"],
        mode=given["mode"],
    )


def agent_interrupt_method(params: dict[str, Any]) -> dict[str, Any]:
    """Stop the running turn. Not the session -- see `interrupt`."""
    return agent_interrupt(_project_of(params))


def agent_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    return agent_shut(_project_of(params))


def project_create(params: dict[str, Any]) -> dict[str, Any]:
    """Make an empty directory for a project the agent has not written yet."""
    return create_new_project(_required_str(params, "parent"), _required_str(params, "name"))


def layout_read(params: dict[str, Any]) -> dict[str, Any]:
    """What the canvas stored last time. The core keeps it and looks inside none of it."""
    return layout_get(_project_of(params))


def layout_write(params: dict[str, Any]) -> dict[str, Any]:
    """Store the whole layout.

    An object is all that is checked, and it is checked here rather than in `layout.py` for
    the reason the module exists: the store must not learn what an entry means, but the
    protocol still has to know it was handed an object rather than a number.
    """
    layout = params.get("layout")
    if not isinstance(layout, dict):
        raise ProtocolError("invalid_params", "'layout' must be an object")

    return layout_put(_project_of(params), layout)


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


def command_list_method(params: dict[str, Any]) -> dict[str, Any]:
    """The commands the project already has (P17.6). Nothing here goes on the graph."""
    return command_list(_project_of(params), _optional_str(params, "directory") or "")


def command_start_method(params: dict[str, Any]) -> dict[str, Any]:
    """Run one of them. Each process is started on its own; there is no "bring it all up"."""
    return command_start(
        _project_of(params),
        _required_str(params, "command"),
        _optional_str(params, "directory") or "",
    )


def command_state_method(params: dict[str, Any]) -> dict[str, Any]:
    """Is it still running? A read: it starts nothing (P11)."""
    return command_state(_project_of(params))


def command_logs_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll its output. The caller keeps the offset it was last given (P13)."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")

    return command_logs(_project_of(params), offset)


def command_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    """Stop it -- this session's, or one a crashed session left behind."""
    return command_stop(_project_of(params))


def rag_index_method(params: dict[str, Any]) -> dict[str, Any]:
    """Hand the pipeline its documents. A write into somebody's store, so: a press (P17.5)."""
    return rag_index(
        _project_of(params), _required_str(params, "node"), _optional_str(params, "python")
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
    "node.source": node_source_method,
    "node.set_body": node_set_body,
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
    "talk.open": talk_open_method,
    "talk.say": talk_say_method,
    "talk.poll": talk_poll_method,
    "talk.state": talk_state_method,
    "talk.close": talk_close_method,
    "run.build": run_build_method,
    "work.start": work_start_method,
    "work.stop": work_stop_method,
    "work.status": work_status_method,
    "work.logs": work_logs_method,
    "agent.session": agent_session_method,
    "agent.start": agent_start_method,
    "agent.say": agent_say_method,
    "agent.poll": agent_poll_method,
    "agent.stop": agent_stop_method,
    "agent.interrupt": agent_interrupt_method,
    "agent.choices": agent_choices_method,
    "agent.configure": agent_configure_method,
    "agent.forget": agent_forget_method,
    "agent.rename": agent_rename_method,
    "agent.account": agent_account_method,
    "agent.sign_in": agent_sign_in_method,
    "agent.sign_out": agent_sign_out_method,
    "project.create": project_create,
    "layout.read": layout_read,
    "layout.write": layout_write,
    "mcp.inspect": mcp_inspect_method,
    "mcp.call": mcp_call_method,
    "rag.index": rag_index_method,
    "command.list": command_list_method,
    "command.start": command_start_method,
    "command.state": command_state_method,
    "command.logs": command_logs_method,
    "command.stop": command_stop_method,
}


def dispatch(method: str, params: dict[str, Any], request_id: Any = None) -> Any:
    handler = HANDLERS.get(method)
    if handler is None:
        raise ProtocolError("unknown_method", f"unknown method {method!r}", request_id)
    return handler(params)
