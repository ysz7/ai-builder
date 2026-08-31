"""The API the shell and the UI are handed.

Versioned from the first day it exists. The UI is delivered separately and on its own
schedule, so the two sides will be out of step at some point; a payload that announces its
version can be handled, one that changes shape silently cannot.

Everything here is assembly: it puts another module's result in one envelope and adds
nothing of its own. A decision made here would be a decision made twice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from framestack_core.layout import create_project, read_layout, write_layout
from framestack_core.parser import read_graph
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

#: Bumped when the payload's shape changes in a way a client would notice. Additive fields
#: do not bump it; removing or retyping one does.
#:
#: 3: the rebuild. The annotation layer and the kind registry are gone, and with them every
#: payload that described a node, a knob, a diagnostic or a verdict. What is left is the
#: chat session, the terminal, the layout and the project directory.
#:
#: Phase 1 adds `graph.read` and does **not** move this. A new method is additive -- a
#: client that has never heard of it is unaffected -- and the version is a promise about the
#: shape of what an existing caller already receives. Spending a bump on an addition would
#: teach the far side to expect one for everything, and then the number says nothing.
GRAPH_API_VERSION = 3


# -- the contract ---------------------------------------------------------------
#
# Written out rather than derived from what the code happens to emit: a contract is a
# decision, and a schema inferred from current behaviour would ratify a mistake as readily
# as a design. The test validates real payloads against this, strictly -- an undeclared
# field fails just as loudly as a missing one.
#
# Notation: "str"/"int"/"bool" are scalars, a trailing "?" allows null, [x] is a list of
# x, {...} is an object with exactly these keys, {"<key>": x} is a map with arbitrary keys
# and values shaped like x, and {"<nullable>": x} allows a structure to be absent.


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


#: The `graph.read` payload: what the project is, read from its own directories.
#:
#: **There is no colour in here, and its absence is the contract.** A verdict is earned by a
#: run (I-3) and nothing here runs anything, so a node says what it *is* and what it depends
#: on; whether any of it works is Observe's answer, and it arrives in Phase 2 as a field of
#: its own rather than as a default somebody has to remember to disbelieve.
#:
#: `missing` and `reason` are the incomplete case, sent rather than hidden: a directory that
#: looks like a system and is not one is the state a half-written package is in, and naming
#: the export it lacks is the difference between a graph that explains itself and one that
#: quietly disagrees with the file tree.
GRAPH_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    # Absolute, so a client holding several projects can tell them apart. Every path inside
    # a node is relative to it.
    "root": "str",
    "nodes": [
        {
            "id": "str",
            "name": "str",
            # One of the four kinds, or "file". Never a framework: the stack is not part of
            # the contract, and a payload that named one would put it back in.
            "kind": "str",
            "path": "str",
            "complete": "bool",
            "exports": ["str"],
            "missing": ["str"],
            "reason": "str",
            "parent": "str",
            "children": ["str"],
            "files": ["str"],
        }
    ],
    # Read from imports and from `mcp.json`, never declared. Nothing in the UI creates one.
    "edges": [{"id": "str", "source": "str", "target": "str", "kind": "str", "label": "str"}],
}


#: The `layout.read` payload: where the person put things (Q13).
#:
#: `"<opaque>"` is not a shrug — it is the contract. The core stores this and refuses to
#: look inside, because a core that understood a coordinate would sooner or later be asked
#: to produce one, and a graph the toolchain laid out is a graph it has an opinion about.
LAYOUT_READ_SCHEMA = {"api_version": "int", "layout": {"<key>": "<opaque>"}}

#: The `layout.write` payload. A refusal is a result, as everywhere else.
LAYOUT_WRITE_SCHEMA = {"api_version": "int", "ok": "bool", "detail": "str"}


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
            # Only an `AskUserQuestion` carries these (Q37), and it carries them as the
            # agent wrote them. `<opaque>` because the fields are that tool's, not ours: a
            # contract here would go stale the first time the tool gained one.
            "questions": ["<opaque>"],
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


def create_new_project(parent: Path | str, name: str) -> dict[str, Any]:
    """Make an empty directory for a project. `detail` is the path when it worked."""
    return {"api_version": GRAPH_API_VERSION, **create_project(parent, name).as_dict()}


def graph_get(project: Path | str) -> dict[str, Any]:
    """The project as a graph. A read: it imports nothing and runs nothing."""
    return {"api_version": GRAPH_API_VERSION, **read_graph(project).as_dict()}


def layout_get(project: Path | str) -> dict[str, Any]:
    """Where the person put things. Empty is the ordinary first answer, not a failure."""
    return {"api_version": GRAPH_API_VERSION, "layout": read_layout(project)}


def layout_put(project: Path | str, layout: dict[str, Any]) -> dict[str, Any]:
    """Store the whole layout. The client holds it; the core keeps it and reads nothing."""
    return {"api_version": GRAPH_API_VERSION, **write_layout(project, layout).as_dict()}


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
    answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Answer one standing request for permission. The turn resumes from where it stopped.

    `answers` belongs to `AskUserQuestion` and is refused on anything else (Q37): that tool
    is the agent asking a person to decide rather than to permit, and its own schema names
    the field a decision travels in.
    """
    return {
        "api_version": GRAPH_API_VERSION,
        **answer_permission(project, request, allow, always, answers).as_dict(),
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
