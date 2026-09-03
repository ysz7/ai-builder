"""Method handlers.

Every capability the shell can reach is a method here. That is the whole extension point:
the Rust side has one command and forwards it, so a new capability is a new entry in
`HANDLERS` and never a new command in Rust.

Handlers assemble; they do not decide.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from typing import Any

from framestack_core.api import (
    agent_account,
    agent_choices,
    agent_configure,
    agent_forget,
    agent_interrupt,
    agent_open,
    agent_permission,
    agent_poll,
    agent_rename,
    agent_session,
    agent_shut,
    agent_sign_in,
    agent_sign_out,
    chat_changes,
    chat_choices,
    chat_send,
    create_new_project,
    database_read,
    deploy_down,
    deploy_poll,
    deploy_status,
    deploy_up,
    editor_open,
    graph_get,
    layout_get,
    layout_put,
    mcp_connect,
    mcp_read,
    observe_last,
    observe_read,
    observe_start,
    ollama_models,
    ollama_pull,
    ollama_read,
    ollama_stop,
    routes_read,
    run_last,
    run_read,
    run_start,
    run_stop,
    settings_get,
    settings_put,
    shell_close,
    shell_list,
    shell_open,
    shell_read,
    shell_resize,
    shell_write,
    status_read,
)
from framestack_core.protocol import PROTOCOL_VERSION, ProtocolError

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


def _project_of(params: dict[str, Any]) -> str:
    project = params.get("project")
    if not isinstance(project, str) or not project:
        raise ProtocolError("invalid_params", "'project' must be a non-empty path string")
    return project


def _required_str(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise ProtocolError("invalid_params", f"{name!r} must be a non-empty string")
    return value


def _optional_str(params: dict[str, Any], name: str) -> str | None:
    value = params.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError("invalid_params", f"{name!r} must be a non-empty string when given")
    return value


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
    for name in ("model", "effort", "mode", "commands"):
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
        commands=given["commands"],
    )


def agent_permission_method(params: dict[str, Any]) -> dict[str, Any]:
    """Answer one standing request for permission (Q21).

    Three parameters and no default for `allow`: a verb that decided for itself what an
    unanswered press meant would be answering on the person's behalf, and this is the one
    call in the session surface where the whole point is that a person answered.
    """
    allow = params.get("allow")
    if not isinstance(allow, bool):
        raise ProtocolError("invalid_params", "'allow' must be true or false")
    always = params.get("always", False)
    if not isinstance(always, bool):
        raise ProtocolError("invalid_params", "'always' must be true or false")
    # Optional, and only an `AskUserQuestion` takes it (Q37). Validated as a flat map of
    # strings because that is what the agent's own tool declares; anything else is a caller
    # confused about which tool they are answering, and it is a fault rather than a drop.
    answers = params.get("answers")
    if answers is not None and (
        not isinstance(answers, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in answers.items())
    ):
        raise ProtocolError("invalid_params", "'answers' must be a map of strings to strings")
    return agent_permission(
        _project_of(params), _required_str(params, "request"), allow, always, answers
    )


def agent_interrupt_method(params: dict[str, Any]) -> dict[str, Any]:
    """Stop the running turn. Not the session -- see `interrupt`."""
    return agent_interrupt(_project_of(params))


def agent_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    return agent_shut(_project_of(params))


def project_create(params: dict[str, Any]) -> dict[str, Any]:
    """Make an empty directory for a project the agent has not written yet."""
    return create_new_project(_required_str(params, "parent"), _required_str(params, "name"))


def graph_read(params: dict[str, Any]) -> dict[str, Any]:
    """Read the project into a graph.

    The one method that answers "what is in this project?", and it answers it from the
    directory tree and the imports in it -- never from a stored document. There is no
    counterpart that *writes* a graph, and there will not be one: a structural change is a
    code edit, made through the chat and read back by this.
    """
    return graph_get(_project_of(params))


def observe_start_method(params: dict[str, Any]) -> dict[str, Any]:
    """Run the project's own tests under measurement and colour the nodes from the result.

    A method of its own, for the reason `shell.open` is one: this starts somebody's test
    suite, which is not something a caller should do by accident (P11). A window opening must
    never run a stranger's code -- that is why `graph.read` is a separate, static read.
    """
    return observe_start(_project_of(params))


def observe_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll the run. The caller keeps the offset it was last given (P13)."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")
    return observe_read(_project_of(params), offset)


def observe_last_method(params: dict[str, Any]) -> dict[str, Any]:
    """The last verdict set. A read: it starts no suite and changes no colour."""
    return observe_last(_project_of(params))


def _images_in(params: dict[str, Any]) -> tuple[dict[str, str], ...]:
    """Any pictures pasted into the turn.

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
    return tuple(images)


def chat_send_method(params: dict[str, Any]) -> dict[str, Any]:
    """Send one message to the agent, as exactly one command.

    **This replaces `agent.say` as the way a person's words reach the agent**, and the
    difference is the whole of Phase 4: `agent.say` sends whatever it is given, and this
    sends nothing that is not one of four commands with its own prompt in front of it.

    `command` and `stack` are answers to questions a previous call asked, never options a
    caller invents -- an unrecognised value is refused rather than passed along.
    """
    return chat_send(
        _project_of(params),
        _required_str(params, "text"),
        params.get("command", "") if isinstance(params.get("command"), str) else "",
        params.get("stack", "") if isinstance(params.get("stack"), str) else "",
        _images_in(params),
    )


def chat_changes_method(params: dict[str, Any]) -> dict[str, Any]:
    """What changed in the working tree. A read: it runs no tests and observes nothing."""
    return chat_changes(_project_of(params))


def chat_choices_method(params: dict[str, Any]) -> dict[str, Any]:
    """The commands and the stacks. A statement about this build, not about the project."""
    return chat_choices()


def _offset_of(params: dict[str, Any]) -> int:
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")
    return offset


def run_start_method(params: dict[str, Any]) -> dict[str, Any]:
    """Call one system's export, once. Never implicit (P11), and it colours nothing.

    A method of its own for the reason `observe.start` is one: this runs somebody's code.
    What it is **not** is an execution of the graph -- one node, one export, no traversal and
    no order. If a caller ever needs "and then the next node", that is Python's job.

    `input` is whatever the action takes and is checked no further here: what a `search`
    accepts is the project's business, and the driver is where a wrong shape becomes a
    traceback the person can read.
    """
    given = params.get("input", {})
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise ProtocolError("invalid_params", "'input' must be an object")
    return run_start(
        _project_of(params),
        _required_str(params, "node"),
        _required_str(params, "action"),
        given,
    )


def run_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll the call. The caller keeps the offset it was last given (P13)."""
    return run_read(_project_of(params), _required_str(params, "node"), _offset_of(params))


def run_last_method(params: dict[str, Any]) -> dict[str, Any]:
    """What this node last returned. A read: it starts nothing and proves nothing new."""
    return run_last(_project_of(params), _required_str(params, "node"))


def run_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    return run_stop(_project_of(params), _required_str(params, "node"))


def deploy_status_method(params: dict[str, Any]) -> dict[str, Any]:
    """Whether this project can be deployed, and whether it already is.

    A read, and it spawns `docker compose config` to answer -- which is not a contradiction
    of P11. Asking a file what it says brings nothing up, and it is the only way to answer
    without this codebase learning YAML.
    """
    return deploy_status(_project_of(params))


def deploy_up_method(params: dict[str, Any]) -> dict[str, Any]:
    """`docker compose up`. A method of its own: somebody pressed `Deploy` (P11)."""
    return deploy_up(_project_of(params))


def deploy_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll the stack's log. The caller keeps the offset (P13)."""
    return deploy_poll(_project_of(params), _offset_of(params))


def deploy_down_method(params: dict[str, Any]) -> dict[str, Any]:
    """Take the stack down -- the client and the containers both, or stopping means detaching."""
    return deploy_down(_project_of(params))


def settings_read(params: dict[str, Any]) -> dict[str, Any]:
    """The knobs of one system. A read: it opens the file and imports nothing."""
    return settings_get(_project_of(params), _required_str(params, "node"))


def settings_write(params: dict[str, Any]) -> dict[str, Any]:
    """Set one field's default.

    `value` is checked here only for being one of the four things a control can carry. What
    it is *allowed* to be for this particular field -- a whole number, one of a Literal's
    choices -- is the writer's decision, because that is where the annotation is known, and a
    rule enforced in two places is a rule that will one day disagree with itself.
    """
    value = params.get("value")
    if not isinstance(value, (str, int, float, bool)):
        raise ProtocolError("invalid_params", "'value' must be text, a number or true/false")
    return settings_put(
        _project_of(params),
        _required_str(params, "node"),
        _required_str(params, "field"),
        value,
    )


def ollama_models_method(params: dict[str, Any]) -> dict[str, Any]:
    """What this machine has pulled. A read: it fetches nothing."""
    return ollama_models(_project_of(params))


def ollama_pull_method(params: dict[str, Any]) -> dict[str, Any]:
    """Start pulling one model. A method of its own because it starts something (P11)."""
    return ollama_pull(_project_of(params), _required_str(params, "model"))


def ollama_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll a pull with the offset the caller keeps. Nothing is pushed."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")
    return ollama_read(_project_of(params), offset)


def ollama_stop_method(params: dict[str, Any]) -> dict[str, Any]:
    """Stop watching a pull."""
    return ollama_stop(_project_of(params))


def status_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """Whether one dependency can be reached.

    One node per request, because the polling policy is per node: a local check is cheap and
    asked often, a network one is not. A verb that checked everything at once would make the
    caller pick one interval for both.
    """
    return status_read(_project_of(params), _required_str(params, "node"))


def database_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """What the project's storage is. A read: it opens no connection and asks no server."""
    return database_read(_project_of(params))


def routes_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """The routes one service declares. Asked when a panel opens, never on every parse."""
    return routes_read(_project_of(params), _required_str(params, "node"))


def mcp_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """What the file declares about one server. A read: it starts nothing and asks nobody."""
    return mcp_read(_project_of(params), _required_str(params, "node"))


def mcp_connect_method(params: dict[str, Any]) -> dict[str, Any]:
    """Run one server's own command in a terminal, so it can authorise itself.

    A method of its own for the reason `shell.open` is one: this starts somebody else's
    program (P11). It goes to the terminal rather than to a hidden process deliberately --
    the person's own account is on the other end of it, and the honest place for that is
    where they can read every line and stop it themselves.

    **Nothing here stores a credential**, and there is nowhere in this codebase one would go.
    """
    return mcp_connect(_project_of(params), _required_str(params, "node"))


def editor_open_method(params: dict[str, Any]) -> dict[str, Any]:
    """Open one of the project's files in the person's own editor.

    A method of its own because it starts somebody else's program (P11), and it refuses a
    path outside the project: this takes a path from a webview and hands it to an editor.
    """
    line = params.get("line", 0)
    if not isinstance(line, int) or isinstance(line, bool) or line < 0:
        raise ProtocolError("invalid_params", "'line' must be a number, zero or more")
    return editor_open(_project_of(params), _required_str(params, "path"), line)


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


def shell_open_method(params: dict[str, Any]) -> dict[str, Any]:
    """Open a terminal. A method of its own, for the reason `run.start` is one: starting a
    process is not something a caller should do by accident (P11)."""
    name = params.get("name", "")
    if not isinstance(name, str):
        raise ProtocolError("invalid_params", "'name' must be a string")
    return shell_open(_project_of(params), name)


def shell_write_method(params: dict[str, Any]) -> dict[str, Any]:
    """Type into one. `text` is sent verbatim -- the newline is the caller's to send, and so
    is the `\x03` that interrupts what is running."""
    return shell_write(
        _project_of(params),
        _required_str(params, "shell"),
        _required_str(params, "text"),
    )


def shell_read_method(params: dict[str, Any]) -> dict[str, Any]:
    """Poll one. The caller keeps the offset it was last given (P13)."""
    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProtocolError("invalid_params", "'offset' must be a number")
    return shell_read(_project_of(params), _required_str(params, "shell"), offset)


def shell_resize_method(params: dict[str, Any]) -> dict[str, Any]:
    """Tell one how wide its window is."""
    size = []
    for name in ("columns", "rows"):
        value = params.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ProtocolError("invalid_params", f"'{name}' must be a positive number")
        size.append(value)
    return shell_resize(_project_of(params), _required_str(params, "shell"), size[0], size[1])


def shell_close_method(params: dict[str, Any]) -> dict[str, Any]:
    return shell_close(_project_of(params), _required_str(params, "shell"))


def shell_list_method(params: dict[str, Any]) -> dict[str, Any]:
    """Which terminals are open here. A read: it opens nothing."""
    return shell_list(_project_of(params))


HANDLERS: dict[str, Handler] = {
    "ping": ping,
    "project.create": project_create,
    "graph.read": graph_read,
    "observe.start": observe_start_method,
    "observe.read": observe_read_method,
    "observe.last": observe_last_method,
    "run.start": run_start_method,
    "run.read": run_read_method,
    "run.last": run_last_method,
    "run.stop": run_stop_method,
    "deploy.status": deploy_status_method,
    "deploy.start": deploy_up_method,
    "deploy.read": deploy_read_method,
    "deploy.stop": deploy_down_method,
    "chat.send": chat_send_method,
    "chat.changes": chat_changes_method,
    "chat.choices": chat_choices_method,
    "settings.read": settings_read,
    "settings.write": settings_write,
    "status.read": status_read_method,
    "ollama.models": ollama_models_method,
    "ollama.pull": ollama_pull_method,
    "ollama.read": ollama_read_method,
    "ollama.stop": ollama_stop_method,
    "database.read": database_read_method,
    "routes.read": routes_read_method,
    "mcp.read": mcp_read_method,
    "mcp.connect": mcp_connect_method,
    "editor.open": editor_open_method,
    "layout.read": layout_read,
    "layout.write": layout_write,
    "agent.session": agent_session_method,
    "agent.start": agent_start_method,
    "agent.poll": agent_poll_method,
    "agent.stop": agent_stop_method,
    "agent.interrupt": agent_interrupt_method,
    "agent.permission": agent_permission_method,
    "agent.choices": agent_choices_method,
    "agent.configure": agent_configure_method,
    "agent.forget": agent_forget_method,
    "agent.rename": agent_rename_method,
    "agent.account": agent_account_method,
    "agent.sign_in": agent_sign_in_method,
    "agent.sign_out": agent_sign_out_method,
    "shell.open": shell_open_method,
    "shell.write": shell_write_method,
    "shell.read": shell_read_method,
    "shell.resize": shell_resize_method,
    "shell.close": shell_close_method,
    "shell.list": shell_list_method,
}


def dispatch(method: str, params: dict[str, Any], request_id: Any = None) -> Any:
    handler = HANDLERS.get(method)
    if handler is None:
        raise ProtocolError("unknown_method", f"unknown method {method!r}", request_id)
    return handler(params)
