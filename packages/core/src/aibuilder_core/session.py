"""The agent, as a process this toolchain starts and talks to.

Q16 put the generation loop in the application and said the core is called before and after
but never during. **Amended here, and only about where the process lives**: a webview cannot
spawn anything, and the alternative was a filesystem-and-shell capability in Rust, which is
the door Q13 already decided to keep shut. So the process is started the way every other
process in this codebase is started -- `run.start` for uvicorn, `work.start` for celery --
and this is the third instance of one shape rather than a new mechanism.

What Q16 actually forbade is untouched: **the core contains no HTTP client to a model and no
vendor SDK.** It spawns `claude`, writes lines to its stdin and reads lines from its log, and
understands none of it beyond enough to say what the agent is doing right now. Swap the agent
for another one and this module changes; nothing else does.

Three rules carried over from P13, unchanged:

* **Nothing is pushed.** Events are polled with an offset the caller keeps, exactly like
  `run.logs`. A stream would hold the wire open, and the protocol is one answer per request.
* **What we start, we can find again** -- a record on disk, so a crashed session leaves
  something the next one can stop.
* **Nothing starts implicitly.** No read, no poll and no status check ever starts the agent;
  `agent.start` exists so that nothing else has to.

And one rule of its own, from Q16: the agent is **denied writes to `.aibuilder/`**. The
snapshot, the run records and the agent's own log live there, and an agent that could edit
the snapshot would be forging evidence about itself.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aibuilder_core.agent import prompt_path

__all__ = [
    "AGENT_LOG_PATH",
    "AGENT_STATE_PATH",
    "COMMANDS_PATH",
    "SESSIONS_PATH",
    "SETTINGS_PATH",
    "SessionResult",
    "agent_available",
    "agent_binary",
    "close_everything_started_here",
    "configure_session",
    "interrupt",
    "list_sessions",
    "poll_session",
    "say",
    "start_session",
    "session_status",
    "stop_session",
]

#: Beside the run and worker records. Tooling state; delete it and the project is unchanged.
AGENT_STATE_PATH = Path(".aibuilder") / "session.json"
#: The raw stream, one JSON object per line, exactly as the agent wrote it.
#: Where a conversation's stream is kept, one file per conversation.
#:
#: **Per conversation and not per project.** One file, truncated on every `agent.start`, meant
#: that switching conversations destroyed the transcript of the one being left: the agent
#: keeps its own, ours was gone, and "go back to that conversation" showed an empty panel.
LOGS_PATH = Path(".aibuilder") / "conversations"

#: The log of a project with no session on record. Kept for exactly that case -- reading a
#: stream that no `agent.start` produced -- and never written to by a session.
AGENT_LOG_PATH = Path(".aibuilder") / "session.log"
#: What the agent said it can be asked to do, kept from the last `init` line it sent.
#:
#: **Read rather than hard-coded.** The list belongs to the agent: it changes with its
#: plugins, its skills and its version, and a copy of ours would be a claim about somebody
#: else's installation that goes stale without ever looking wrong. Kept on disk because a
#: **resumed** session sends no `init` until its first turn -- so the alternative to
#: remembering is showing nothing at all to exactly the person who has been here before.
COMMANDS_PATH = Path(".aibuilder") / "commands.json"

#: The conversations this project has had. A list of ids the agent owns, not a transcript --
#: what was said lives in the agent's own store, and this is only how to ask for it again.
SESSIONS_PATH = Path(".aibuilder") / "sessions.json"

#: Ways out of the project, refused by name. Denials are checked before permissions.
#:
#: Absolute paths only: `cat app/main.py` is the project's own file and is nobody's business
#: but the agent's, while `cat /Users/...` is a machine somebody else lives on.
OUTSIDE = (
    "Bash(cat /*)",
    "Bash(cd /*)",
    "Bash(ls /*)",
    "Bash(find /*)",
    "Bash(cp /*)",
    "Bash(mv /*)",
    "Bash(rm /*)",
    "Bash(head /*)",
    "Bash(tail /*)",
    "Bash(grep * /*)",
)

#: What the agent may not touch. Its own evidence about itself is in there (Q16).
DENIED = ("Edit(.aibuilder/**)", "Write(.aibuilder/**)", *OUTSIDE)

#: How a session is set up, kept because the flags that set it are **flags at spawn**.
#:
#: `--model`, `--effort` and `--permission-mode` are session flags: there is no way to change
#: one in a conversation that is already running. So changing one is a restart with
#: `--resume` -- the conversation survives, its process does not -- and the setting has to be
#: written down somewhere, or the restart would not know what to start with.
SETTINGS_PATH = Path(".aibuilder") / "agent-settings.json"

#: The models a session may be asked for, as **the agent's own aliases**.
#:
#: Aliases and not identifiers: an alias means "the latest of that line" and stays right when
#: a new one ships, while a pinned id is a claim about somebody else's catalogue that goes
#: stale without ever looking wrong. Only the three the CLI documents are offered -- inventing
#: a fourth would be guessing at another program's vocabulary. `""` means the agent's own
#: choice, which is what a session gets when nobody has asked for anything.
MODELS = ("", "opus", "sonnet", "fable")

#: How hard the agent may think. `""` is its own default.
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")

#: What the agent may do without asking.
#:
#: **`manual` is not here, and its absence is the point.** The CLI lists it as a choice and
#: accepts it, and then `init` reports `default` -- it is taken and ignored. This is the
#: second time that flag has looked available and not been (Q17), so it is refused here by
#: name rather than passed along to be quietly dropped.
#:
#: **`bypassPermissions` is not here either**, and for a different reason: the agent is denied
#: writes to `.aibuilder/` because its own evidence about itself is in there, and a mode whose
#: whole purpose is to skip permission checks is not a switch this application offers over
#: that. A person who wants it has the agent's own terminal.
MODES = ("acceptEdits", "plan", "dontAsk", "auto")

#: Whether the agent may run commands, and this is **not** the permission mode (measured).
#:
#: Neither mode lets it: under `acceptEdits` a command asks for approval, and there is no
#: message shape to approve it with (Q17); under `dontAsk` the agent is told outright that
#: "permission to use Bash has been denied because Claude Code is running in don't ask mode".
#: So the mode was never the switch -- what decides is the tool policy, the same mechanism
#: `--disallowed-tools` already uses to keep the agent out of `.aibuilder/`.
#:
#: `""` leaves that policy alone and is the default: a builder that shipped shell access
#: turned on would be deciding, on everybody's behalf, that an agent may run anything in
#: their project. `"bash"` is a person saying otherwise, once, for this project -- and it is
#: what makes I-5 reachable at all, because a node cannot be proven by tests nobody may run.
COMMANDS = ("", "bash")

#: What "may run commands" grants: commands, and the ones that leave the project denied.
#:
#: The first attempt at this was a list of prefixes -- `Bash(python3*)`, `Bash(pip*)` -- and
#: it was wrong in the way prefix rules are always wrong: a project's own interpreter is
#: `/usr/bin/python3`, its pip is `.venv/bin/pip`, and a person's `cd build && make` starts
#: with neither. Every one of those was refused while the person had already said yes, which
#: is worse than not asking at all.
#:
#: So the grant is the tool, and the **boundary is a denial**: the obvious ways out of the
#: project are refused by name. It is not airtight and is not offered as such -- `python3 -c`
#: opens any file on the machine -- but it stops the ordinary drift outward, which is what
#: actually happened: the agent read the builder's own `pyproject.toml` with `cat`.
#: The real boundary is an OS sandbox, which this transport does not provide.
COMMANDS_GRANTED = ("Bash",)


#: What a project gets when nobody has asked for anything.
DEFAULT_MODE = "acceptEdits"

#: The picture formats a turn may carry, as the agent spells them.
#:
#: A closed list, checked here: what is written to the agent's stdin is a line it has to be
#: able to parse, and an unknown media type is a turn that fails somewhere we cannot see --
#: inside the agent, after the message was accepted.
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")

#: How large one pasted picture may be, measured on the base64 it arrives as.
#:
#: A limit of ours, refused here rather than sent: a picture too large for the model comes
#: back as an error about a turn the person can no longer see the cause of.
IMAGE_LIMIT_BYTES = 4 * 1024 * 1024

#: How long to wait for the agent to answer that it exists.
PROBE_TIMEOUT_S = 10

#: How long a browser sign-in may take before we stop waiting on it.
#:
#: Minutes rather than seconds: a person has to find the window, read the page and press the
#: button, and the CLI holds the process open until they do. Giving up early would report "not
#: signed in" about a sign-in that was still going on.
SIGN_IN_TIMEOUT_S = 300

#: The live process, held for the sidecar's lifetime. Unlike a web server, this one has to be
#: *written to*, and a pipe cannot be reopened from a pid -- so a session is the sidecar's
#: lifetime, and a session inherited from a crashed one can be stopped but not continued.
_LIVE: dict[str, subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class SessionResult:
    """The answer to every verb here. Refusals are results, never protocol faults."""

    ok: bool
    detail: str
    session: str | None = None
    running: bool = False
    available: bool = False
    version: str = ""
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    offset: int = 0
    #: Conversations this project has had, newest first.
    sessions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: Tokens the last turn carried. Zero until a turn has been taken.
    context: int = 0
    #: Which model is answering, as the agent itself named it. Empty until it says.
    model: str = ""
    #: The agent's own running estimate of what this turn has cost so far. Zero between turns.
    spending: int = 0
    #: What the agent says it can be asked to do -- names only, because names are all it gives.
    #: Empty from a poll that carried no `init`; the caller keeps the last list it was handed.
    commands: tuple[str, ...] = field(default_factory=tuple)
    #: How this project's sessions are started: model, effort, permission mode.
    #:
    #: `None` and not an empty map: absent means the question was not asked of this verb, and
    #: a map of empty strings would be an answer -- "no model, no effort" -- to a question
    #: nobody put. Only the verbs that read the setting report it.
    settings: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "session": self.session,
            "running": self.running,
            "available": self.available,
            "version": self.version,
            "events": [dict(event) for event in self.events],
            "offset": self.offset,
            "sessions": [dict(item) for item in self.sessions],
            "context": self.context,
            "model": self.model,
            "spending": self.spending,
            "commands": list(self.commands),
            "settings": None if self.settings is None else dict(self.settings),
        }


#: Where an agent is found when `PATH` does not have it.
#:
#: An application launched from Finder inherits a minimal `PATH` -- `/usr/bin:/bin` and
#: little else -- while the tool was installed by a shell into somewhere that is on *its*
#: path. So "no agent on this machine" would be true of the terminal and false of the
#: window, which is the worst kind of wrong: correct-looking and only in one of them.
FALLBACK_PATHS = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "~/.bun/bin/claude",
    "~/.npm-global/bin/claude",
)


def agent_binary() -> str | None:
    """Where the agent is, or `None`. `PATH` first, then the places a shell installs to."""
    found = shutil.which("claude")
    if found is not None:
        return found
    for candidate in FALLBACK_PATHS:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)
    return None


def agent_available() -> tuple[bool, str]:
    """Is there an agent on this machine, and which one?

    Asked of the binary rather than assumed (§5.8). Being installed is not the same as being
    authorised -- that only shows up when a turn is taken, and it shows up as the agent's own
    words rather than as something this module predicts.
    """
    binary = agent_binary()
    if binary is None:
        return False, ""
    try:
        answer = subprocess.run(  # noqa: S603 -- the command is ours
            [binary, "--version"], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S
        )
    except (subprocess.SubprocessError, OSError):
        return False, ""
    return answer.returncode == 0, answer.stdout.strip()


@dataclass(frozen=True)
class Account:
    """Who the agent is signed in as.

    **This is read, never held.** The credential belongs to the CLI, which put it on this
    machine through its own browser flow; the core has no HTTP client to a model and no SDK
    (Q16), so there is nothing here to store and nothing to leak. What was missing was not a
    login -- it was the application saying whose account a turn is about to spend.
    """

    signed_in: bool = False
    method: str = ""
    email: str = ""
    plan: str = ""
    organisation: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "signed_in": self.signed_in,
            "method": self.method,
            "email": self.email,
            "plan": self.plan,
            "organisation": self.organisation,
            "detail": self.detail,
        }


def account() -> Account:
    """Ask the agent who it is signed in as. Asked, never assumed (§5.8)."""
    binary = agent_binary()
    if binary is None:
        return Account(detail="no agent found on this machine")
    try:
        answer = subprocess.run(  # noqa: S603 -- the command is ours
            [binary, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return Account(detail=f"the agent could not be asked: {exc}")

    try:
        told = json.loads(answer.stdout or "{}")
    except json.JSONDecodeError:
        # An older agent may not answer in JSON. Not knowing is an answer; guessing is not.
        return Account(detail="this agent does not report its account")
    if not isinstance(told, dict):
        return Account(detail="this agent does not report its account")

    return Account(
        signed_in=bool(told.get("loggedIn")),
        method=str(told.get("authMethod") or ""),
        email=str(told.get("email") or ""),
        plan=str(told.get("subscriptionType") or ""),
        organisation=str(told.get("orgName") or ""),
        detail="" if told.get("loggedIn") else "not signed in",
    )


def sign_in(console: bool = False) -> Account:
    """Run the agent's own browser sign-in, and report what it left behind.

    **Its flow, not ours.** The browser is opened by the CLI, the credential is written where
    the CLI keeps it, and this waits for that to finish and then asks again. Building a login
    of our own would mean holding a secret, which is the one thing this design does not do.
    """
    binary = agent_binary()
    if binary is None:
        return Account(detail="no agent found on this machine")
    try:
        subprocess.run(  # noqa: S603 -- the command is ours
            [binary, "auth", "login", "--console" if console else "--claudeai"],
            capture_output=True,
            text=True,
            timeout=SIGN_IN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return Account(detail="the sign-in was not finished in time")
    except (subprocess.SubprocessError, OSError) as exc:
        return Account(detail=f"the sign-in could not be started: {exc}")
    return account()


def sign_out() -> Account:
    """Sign the agent out. Ours to ask for, the CLI's to carry out."""
    binary = agent_binary()
    if binary is None:
        return Account(detail="no agent found on this machine")
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        subprocess.run(  # noqa: S603 -- the command is ours
            [binary, "auth", "logout"], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S
        )
    return account()


def _sessions_path(project: Path) -> Path:
    return project / SESSIONS_PATH


def list_sessions(project: Path | str) -> tuple[dict[str, Any], ...]:
    """The conversations this project has had, newest first.

    Ids and labels, never what was said: the transcript belongs to the agent, and keeping a
    copy here would be a second store of something somebody else is already the source of.
    """
    path = _sessions_path(Path(project).resolve())
    if not path.is_file():
        return ()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(stored, list):
        return ()
    return tuple(item for item in stored if isinstance(item, dict))


def _write_sessions(project: Path, entries: list[dict[str, Any]]) -> None:
    # A list that cannot be written costs a convenience, never a session: the conversation
    # is the agent's and exists whether or not we managed to note its id.
    with contextlib.suppress(OSError):
        _sessions_path(project).write_text(json.dumps(entries[:40], indent=2), encoding="utf-8")


def _remember(project: Path, identifier: str, label: str) -> None:
    """Note a conversation, or note that a known one was opened again.

    **Resuming is not creating.** Moving a known conversation to the front would reorder the
    list under the person's hand every time they switched, and since the chips differ only by
    id, a switch would look exactly like nothing having happened. So a known id keeps its
    place and its label -- the label says how the conversation *began*, which does not change
    by continuing it -- and only the time is refreshed.
    """
    known = list(list_sessions(project))
    for index, item in enumerate(known):
        if item.get("id") == identifier:
            known[index] = {**item, "at": _now()}
            _write_sessions(project, known)
            return
    _write_sessions(project, [{"id": identifier, "label": label, "at": _now()}, *known])


#: The longest a conversation's name may be. A list of chips, not a place to write in.
NAME_LIMIT = 60


def rename_session(project: Path | str, identifier: str, label: str) -> SessionResult:
    """Give one conversation a name.

    **The label is the only field of a conversation that belongs to the person.** Its id is
    the agent's, its transcript is the agent's, and when it happened is a fact -- the name is
    the one thing here that is a choice, so it is the one thing that may be written. The
    default (`new`, `continued`, `fork`) says how the session was opened, which is a fine
    default and a poor name for a list where every entry says `new`.

    An empty name puts the default back rather than leaving a nameless chip.
    """
    root = Path(project).resolve()
    known = list(list_sessions(root))
    wanted = " ".join(label.split())[:NAME_LIMIT]

    for index, item in enumerate(known):
        if item.get("id") == identifier:
            known[index] = {**item, "label": wanted or "new"}
            _write_sessions(root, known)
            return SessionResult(
                True,
                "renamed",
                session=_current(root),
                running=str(root) in _LIVE,
                available=agent_available()[0],
                sessions=tuple(known),
            )

    return SessionResult(False, f"no conversation {identifier!r} in this project")


def forget_session(project: Path | str, identifier: str) -> SessionResult:
    """Drop one conversation from this project's list.

    **It forgets our reference, and nothing else.** The transcript is the agent's, stored
    where the agent stores it, and this neither reads nor deletes it -- `--resume` with the
    id would still work for anyone who kept it. Claiming otherwise would be claiming a reach
    into somebody else's storage that this toolchain deliberately does not have.

    Forgetting the conversation that is running closes it first, because a list entry is the
    only way back to a session and dropping it while it ran would leave a process nothing
    could name.
    """
    root = Path(project).resolve()
    state = _read_state(root)
    # A fork that has not taken a turn yet still writes under a key of its own, because the
    # agent has not named it. Forgetting it has to remove that file too, or it stays on disk
    # under a name nothing will ever look for again.
    spawned_as = str(state.get("log") or "") if state else ""
    if state and str(state.get("session")) == identifier:
        stop_session(root)
        if spawned_as and spawned_as != identifier:
            with contextlib.suppress(OSError):
                _log_for(root, spawned_as).unlink(missing_ok=True)
                _said_path(root, spawned_as).unlink(missing_ok=True)

    known = [item for item in list_sessions(root) if item.get("id") != identifier]
    _write_sessions(root, known)
    # Forgetting is where a transcript is actually deleted. Nothing else removes one: a
    # conversation keeps what was said until somebody says otherwise -- both halves of it,
    # the agent's stream and the person's own turns.
    with contextlib.suppress(OSError):
        _log_for(root, identifier).unlink(missing_ok=True)
        _said_path(root, identifier).unlink(missing_ok=True)
    return SessionResult(
        True,
        "conversation forgotten",
        session=_current(root),
        running=str(root) in _LIVE,
        available=agent_available()[0],
        sessions=tuple(known),
    )


def read_commands(project: Path | str) -> tuple[str, ...]:
    """The commands the agent last said it had. Reads; asks nothing and starts nothing."""
    path = Path(project).resolve() / COMMANDS_PATH
    if not path.is_file():
        return ()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(stored, list):
        return ()
    return tuple(str(name) for name in stored if isinstance(name, str))


def _commands_of(raw: dict[str, Any]) -> tuple[str, ...]:
    """The command names in an `init` line, if this line is one.

    Names and nothing else, because names and nothing else is what the agent sends. Writing
    a sentence about what `/compact` does would be this application making claims about
    somebody else's command, and the sentence would still be there after the command changed.
    """
    if raw.get("type") != "system" or raw.get("subtype") != "init":
        return ()
    listed = raw.get("slash_commands")
    if not isinstance(listed, list):
        return ()
    return tuple(str(name) for name in listed if isinstance(name, str))


def _remember_commands(project: Path, names: tuple[str, ...]) -> None:
    path = project / COMMANDS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(list(names), indent=2), encoding="utf-8")


def read_settings(project: Path | str) -> dict[str, str]:
    """How this project's sessions are started. Reads; starts nothing."""
    path = Path(project).resolve() / SETTINGS_PATH
    stored: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            stored = loaded
    model = str(stored.get("model", "") or "")
    effort = str(stored.get("effort", "") or "")
    mode = str(stored.get("mode", "") or "")
    commands = str(stored.get("commands", "") or "")
    return {
        "model": model if model in MODELS else "",
        "effort": effort if effort in EFFORTS else "",
        "mode": mode if mode in MODES else DEFAULT_MODE,
        "commands": commands if commands in COMMANDS else "",
    }


def configure_session(
    project: Path | str,
    model: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    commands: str | None = None,
) -> SessionResult:
    """Set what the next session is started with, and restart the open one onto it.

    **A restart, and it says so.** These are flags at spawn: the agent offers no way to change
    a running session's model or its permission mode, so pretending the switch is free would
    be an interface lying about the thing it is a switch for. The conversation is kept --
    `--resume` under the same id, appending to the same transcript -- and the process is not.

    Only what is passed is changed: `None` means "leave it", which is not the same as `""`,
    the deliberate choice of the agent's own default.
    """
    root = Path(project).resolve()
    settings = read_settings(root)

    for name, given, allowed in (
        ("model", model, MODELS),
        ("effort", effort, EFFORTS),
        ("mode", mode, MODES),
        ("commands", commands, COMMANDS),
    ):
        if given is None:
            continue
        if given not in allowed:
            # `manual` is the reason this refuses by name instead of passing it along: the
            # agent takes it and ignores it, and a setting that is accepted and does nothing
            # is worse than one that is refused.
            offered = ", ".join(choice or "(the agent's own)" for choice in allowed)
            return SessionResult(
                False,
                f"{name} cannot be {given!r} here -- offered: {offered}",
                settings=settings,
            )
        settings[name] = given

    path = root / SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as exc:
        return SessionResult(False, f"the setting could not be written: {exc}", settings=settings)

    state = _read_state(root)
    open_now = str(state.get("session")) if state else None
    if not (state and _alive(int(state.get("pid", 0))) and str(root) in _LIVE and open_now):
        return SessionResult(True, "saved -- it applies to the next session", settings=settings)

    label = str(state.get("label", "")) if state else ""
    stop_session(root)
    restarted = start_session(root, resume=open_now, label=label)
    if not restarted.ok:
        return SessionResult(False, restarted.detail, settings=settings)
    return SessionResult(
        True,
        "saved -- the conversation was restarted onto it",
        session=restarted.session,
        running=True,
        available=True,
        version=restarted.version,
        sessions=restarted.sessions,
        commands=restarted.commands,
        settings=settings,
    )


def _log_for(project: Path, key: str) -> Path:
    return project / LOGS_PATH / f"{key}.log"


def _current_log(project: Path) -> Path | None:
    """The log of the session on record here.

    Falls back to the single-file log for a project that has none: a stream written by
    something other than `agent.start` is still a stream, and reading it is not a guess.
    """
    state = _read_state(project)
    key = str(state.get("log") or "") if state else ""
    if key:
        return _log_for(project, key)
    legacy = project / AGENT_LOG_PATH
    return legacy if legacy.is_file() else None


def _state_path(project: Path) -> Path:
    return project / AGENT_STATE_PATH


def _read_state(project: Path) -> dict[str, Any] | None:
    path = _state_path(project)
    if not path.is_file():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return stored if isinstance(stored, dict) else None


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def session_status(project: Path | str) -> SessionResult:
    """Is there an agent, and is a session open? Reads; starts nothing."""
    root = Path(project).resolve()
    available, version = agent_available()
    state = _read_state(root)
    running = bool(state and _alive(int(state.get("pid", 0))))

    if not available:
        return SessionResult(
            False,
            "no agent found on this machine -- install Claude Code and sign in",
            available=False,
        )
    if not running:
        return SessionResult(
            True,
            "no session open",
            available=True,
            version=version,
            sessions=list_sessions(root),
            commands=read_commands(root),
            settings=read_settings(root),
        )
    return SessionResult(
        True,
        "a session is open",
        session=str(state.get("session")) if state else None,
        running=True,
        available=True,
        version=version,
        offset=int(state.get("offset", 0)) if state else 0,
        sessions=list_sessions(root),
        commands=read_commands(root),
        settings=read_settings(root),
    )


def start_session(
    project: Path | str,
    resume: str | None = None,
    fork: bool = False,
    label: str = "",
) -> SessionResult:
    """Open a session with the agent. Never implicit -- somebody pressed a button (P11).

    Three ways in, and they are the agent's own: a new conversation, one continued by id, or
    one **forked** -- "do that again differently", which keeps the original branch instead of
    overwriting it. A fork is given a new id by the agent rather than by us, so the record is
    corrected from the `init` line when it arrives (§5.8: ask, do not assume).
    """
    root = Path(project).resolve()
    available, version = agent_available()
    if not available:
        return SessionResult(False, "no agent found on this machine", available=False)

    existing = _read_state(root)
    live = bool(existing and _alive(int(existing.get("pid", 0))) and str(root) in _LIVE)

    # "Already open" is an answer to **one** question: was this same conversation asked for
    # again? Anything else -- another session by id, a fork, a new one -- is a deliberate
    # switch, and answering it with the session that happens to be running is how the
    # conversation list came to do nothing at all while one was live. The guard against a
    # button pressed twice belongs to the caller, which knows whether it has one in flight;
    # here it would have to be a guess about intent, and it guessed wrong.
    asked_for_the_open_one = (
        live and existing is not None and not fork and str(existing.get("session")) == resume
    )
    if asked_for_the_open_one and resume is not None:
        return SessionResult(
            True,
            "a session is already open",
            session=resume,
            running=True,
            available=True,
            version=version,
            sessions=list_sessions(root),
            commands=read_commands(root),
            settings=read_settings(root),
        )

    if existing:
        stop_session(root)

    identifier = resume or str(uuid.uuid4())

    # **A fork must not write into the log of the conversation it forks.** It spawns under
    # that conversation's id -- the agent gives it a new one only later -- so keying the file
    # by the id in hand would open the original's transcript and truncate it, destroying the
    # very thing a fork exists to keep. A key of its own, renamed when the identity is
    # corrected, is the only ordering that is safe at the moment the process starts.
    key = str(uuid.uuid4()) if fork else identifier
    log = _log_for(root, key)
    log.parent.mkdir(parents=True, exist_ok=True)
    # Appended to, not truncated: continuing a conversation continues its transcript.
    log.touch()

    settings = read_settings(root)
    binary = agent_binary() or "claude"
    command = [
        binary,
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        # Edits are accepted because the person asked for a change; everything the policy
        # denies comes back as a refused tool result, which is the whole permission surface
        # the transport gives us (Q17). A person can widen or narrow it in the session's
        # settings -- and because this is a flag at spawn, changing it restarts the process.
        "--permission-mode",
        settings["mode"],
        # An answer arrives as deltas as it is written, instead of whole at the end -- which
        # is the difference between silence and a wall of text, and a wall of text.
        #
        # The help says this works "only with --print", and our session is not a --print
        # session. It was **tried in our own configuration** before being relied on, because
        # a flag the CLI accepts and ignores is exactly what `--permission-mode manual` was
        # (Q17), and the way that was found was by reading the effect back rather than the
        # documentation.
        "--include-partial-messages",
        "--disallowed-tools",
        *DENIED,
        # Verbatim, and on every invocation: what `--resume` keeps is not ours to assume.
        "--append-system-prompt-file",
        str(prompt_path()),
    ]
    # What the agent may run, and only because a person said so. The mode is not this switch
    # -- neither `acceptEdits` nor `dontAsk` lets a command through -- so a project where the
    # tests are meant to be run says so here, once, and the flag is simply absent otherwise.
    if settings.get("commands") == "bash":
        command += ["--allowed-tools", *COMMANDS_GRANTED]
    # Asked for by alias and by name, never with a default of ours put in the agent's mouth:
    # an empty setting means the agent picks, and the flag is simply not passed.
    if settings["model"]:
        command += ["--model", settings["model"]]
    if settings["effort"]:
        command += ["--effort", settings["effort"]]

    if resume:
        command += ["--resume", resume]
        if fork:
            command.append("--fork-session")
    else:
        command += ["--session-id", identifier]

    try:
        with log.open("ab") as sink:
            process = subprocess.Popen(  # noqa: S603 -- the command is ours, built above
                command,
                cwd=root,
                stdin=subprocess.PIPE,
                stdout=sink,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        return SessionResult(False, f"the agent could not be started: {exc}", available=True)

    _LIVE[str(root)] = process
    # `invented` is the one fact `_correct_identity` cannot work out later: whether this id is
    # ours (a uuid the agent may replace, and then it was never a conversation) or a real
    # conversation we asked to resume (which a fork must keep, since going back to it is the
    # whole point of forking).
    _state_path(root).write_text(
        json.dumps(
            {
                "pid": process.pid,
                "session": identifier,
                "log": key,
                "started_at": _now(),
                "invented": resume is None,
                "label": label or _label(resume, fork),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _remember(root, identifier, label or _label(resume, fork))
    return SessionResult(
        True,
        "session open",
        session=identifier,
        running=True,
        available=True,
        version=version,
        sessions=list_sessions(root),
        # The list the last session left behind, so the field can offer something before the
        # first `init` arrives -- and a resumed session sends none until its first turn.
        commands=read_commands(root),
        settings=settings,
    )


def _label(resume: str | None, fork: bool) -> str:
    if fork:
        return "fork"
    return "continued" if resume else "new"


def say(
    project: Path | str,
    text: str,
    images: tuple[dict[str, str], ...] = (),
) -> SessionResult:
    """Send one turn to the agent, with any pictures that were pasted into it.

    A session has to be *written to*, and a pipe cannot be reopened from a pid — so a session
    left by a crashed sidecar can be stopped but not continued, and this says so rather than
    pretending otherwise.

    A picture goes **before** the words, which is the order the message is read in: "here is
    the thing, and here is what I am asking about it".
    """
    root = Path(project).resolve()
    process = _LIVE.get(str(root))
    if process is None or process.poll() is not None:
        _LIVE.pop(str(root), None)
        return SessionResult(False, "no session is open here -- start one first")

    blocks: list[dict[str, Any]] = []
    for picture in images:
        media = picture.get("media_type", "")
        data = picture.get("data", "")
        if media not in IMAGE_TYPES:
            return SessionResult(False, f"{media or 'that'} is not a picture the agent reads")
        if len(data) > IMAGE_LIMIT_BYTES:
            return SessionResult(False, "that picture is too large to send")
        try:
            base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return SessionResult(False, "that picture did not arrive whole")
        blocks.append(
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
        )
    blocks.append({"type": "text", "text": text})

    message = {
        "type": "user",
        "message": {"role": "user", "content": blocks},
    }
    try:
        assert process.stdin is not None
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()
    except (OSError, ValueError) as exc:
        return SessionResult(False, f"the agent stopped listening: {exc}")

    # What was said is kept beside the stream, because the agent echoes none of it. A picture
    # is noted rather than stored: without the note the person's turn reads as a question
    # about nothing, and with the picture itself the transcript would be a second copy of a
    # thing the agent already has.
    carried = f"{text}\n\n[{len(images)} image{'' if len(images) == 1 else 's'} attached]"
    _remember_said(root, carried if images else text)
    return SessionResult(True, "sent", running=True)


def interrupt(project: Path | str) -> SessionResult:
    """Stop the turn that is running. **The conversation survives it.**

    The agent accepts a `control_request` of subtype `interrupt` on the same pipe a turn is
    sent on, answers it, and ends the turn -- so stopping is not killing. Reaching for
    `stop_session` here would have thrown away the session, its process and the thread of what
    was being discussed, to cancel one answer.

    Sent, and not waited on: the answer comes back through the log like everything else, and
    the caller reads it with the offset it keeps (P13).
    """
    root = Path(project).resolve()
    process = _LIVE.get(str(root))
    if process is None or process.poll() is not None:
        _LIVE.pop(str(root), None)
        return SessionResult(False, "nothing is running here")

    message = {
        "type": "control_request",
        "request_id": f"stop-{uuid.uuid4()}",
        "request": {"subtype": "interrupt"},
    }
    try:
        assert process.stdin is not None
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()
    except (OSError, ValueError) as exc:
        return SessionResult(False, f"the agent stopped listening: {exc}")
    return SessionResult(True, "stopping", running=True)


def _said_path(project: Path, key: str) -> Path:
    return project / LOGS_PATH / f"{key}.said.json"


def _current_said(project: Path) -> Path | None:
    state = _read_state(project)
    key = str(state.get("log") or "") if state else ""
    return _said_path(project, key) if key else None


def _remember_said(project: Path, text: str) -> None:
    """Write down what the person said, because **nobody else does.**

    The agent's stream carries what the agent says and what its tools answer, and not one
    line of what it was asked -- checked, not assumed. So a conversation reopened later had
    the replies and none of the questions, which reads as the agent talking to itself.

    Recorded **beside** the log rather than into it: the log is the stream exactly as the
    agent wrote it, and a second writer appending to a file its process holds open is a race
    as well as a lie. What is stored is the position in that log where the turn was sent,
    which is what puts the line back in the right place when it is read again.
    """
    path = _current_said(project)
    if path is None:
        return
    log = _current_log(project)
    at = log.stat().st_size if log is not None and log.is_file() else 0

    known: list[dict[str, Any]] = []
    if path.is_file():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            stored = json.loads(path.read_text(encoding="utf-8"))
            known = [item for item in stored if isinstance(item, dict)]
    known.append({"offset": at, "text": text, "at": _now()})
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(known, indent=2), encoding="utf-8")


def _said_between(project: Path, start: int, stop: int) -> list[tuple[int, str]]:
    """What the person said while the log grew from `start` to `stop`.

    **The left edge is exclusive and the right edge is not**, which is not symmetry for its
    own sake. A turn is recorded at the position the log had reached when it was sent, so the
    newest one usually sits exactly at the end with nothing written after it yet: excluding
    the right edge would hide the question until the answer arrived, and including the left
    would repeat it on the next poll, whose start is this poll's end. The first read is the
    exception, because a turn sent into an empty log sits at zero and has never been read.
    """
    path = _current_said(project)
    if path is None or not path.is_file():
        return []
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(stored, list):
        return []
    picked: list[tuple[int, str]] = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        at = int(item.get("offset", 0))
        if at <= stop and (at > start or start == 0):
            picked.append((at, str(item.get("text", ""))))
    return picked


def poll_session(project: Path | str, offset: int = 0) -> SessionResult:
    """What the agent has said since `offset`, as events a canvas can act on.

    Polled, never pushed (P13). Each line of the stream is read once and turned into the
    smallest thing the interface needs: what is happening, which file is being touched, and
    what was refused. Everything else stays in the log, where it can be read in full.
    """
    root = Path(project).resolve()
    log = _current_log(root)
    if log is None or not log.is_file():
        return SessionResult(False, "no session has been opened here", offset=0)

    try:
        with log.open("rb") as handle:
            handle.seek(max(offset, 0))
            chunk = handle.read()
            here = handle.tell()
    except OSError as exc:
        return SessionResult(False, f"the session log could not be read: {exc}", offset=offset)

    events: list[dict[str, Any]] = []
    context = 0
    model = ""
    spending = 0
    commands: tuple[str, ...] = ()

    # What the person said, put back where they said it. Their turns are not in the stream
    # -- the agent echoes nothing of what it was asked -- so they are kept beside it with the
    # position the log had reached, and woven in by that position rather than appended at one
    # end, which would put every question after every answer.
    said = _said_between(root, offset, here)
    at = offset

    for line in chunk.decode("utf-8", errors="replace").splitlines(keepends=True):
        while said and said[0][0] <= at:
            events.append(_event("you", said.pop(0)[1]))
        at += len(line.encode("utf-8"))
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line; the next poll gets it whole
        events.extend(_read_event(raw))
        context = _context_of(raw) or context
        model = _model_of(raw) or model
        commands = _commands_of(raw) or commands
        if raw.get("type") == "system" and raw.get("subtype") == "thinking_tokens":
            spending = int(raw.get("estimated_tokens", 0) or 0)
        _correct_identity(root, raw)

    for _, text in said:
        events.append(_event("you", text))

    # Written only when this chunk carried an `init`, and returned only then: forty-nine
    # names on every poll would be the same answer several times a second to a question
    # nobody asked twice. The caller keeps the last list it was handed.
    if commands:
        _remember_commands(root, commands)

    process = _LIVE.get(str(root))
    running = process is not None and process.poll() is None
    return SessionResult(
        True,
        "",
        session=_current(root),
        running=running,
        events=tuple(events),
        offset=here,
        context=context,
        model=model,
        spending=spending,
        commands=commands,
        sessions=list_sessions(root),
    )


def _model_of(raw: dict[str, Any]) -> str:
    """Which model is answering, as the agent named it.

    Asked rather than assumed, and asked of the agent rather than of a model API: the context
    window a client would draw a fraction against differs by model by a factor of five, and
    which model the CLI picked is its decision -- taken from its configuration, its account and
    its flags, none of which we can see. It announces the choice in `init` and repeats it on
    every message; both are read, because a session resumed mid-stream has no `init` of its own.
    """
    if raw.get("type") == "system" and raw.get("subtype") == "init":
        return str(raw.get("model") or "")
    if raw.get("type") == "assistant":
        message = raw.get("message")
        if isinstance(message, dict):
            return str(message.get("model") or "")
    return ""


def _usage_in(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Where this line reports **what one request carried**, if it does.

    Two places, and reading them as they stream is why the counter moves while an answer is
    being written: a request's size is reported in `message_start` and again at its end, and
    reading only the finished message meant reading it once, too late to be useful.

    One request, never a sum of them. The difference is the whole of this function.
    """
    if raw.get("type") == "assistant":
        usage = raw.get("message", {}).get("usage")
        return usage if isinstance(usage, dict) else None
    # **Never `result`.** Its `usage` is the whole turn added up -- every API call the agent
    # made inside it, each one re-reading the same cached prompt -- so a turn of 19 calls
    # carrying 28k reported 542k. Summed like that it is not a context size at all, and it
    # arrived last, overwriting the honest per-request number with one 17 times too large:
    # a ring that says half the window is full is a reason to compact where there is none.
    # What `result` measures is what the turn cost, which is a different question.
    if raw.get("type") == "stream_event":
        event = raw.get("event") or {}
        usage = event.get("usage") or (event.get("message") or {}).get("usage")
        return usage if isinstance(usage, dict) else None
    return None


def _context_of(raw: dict[str, Any]) -> int:
    """How much the last turn carried, in tokens.

    Everything the model was sent: the fresh part, plus what was cached and read back. It is
    the agent's own accounting rather than a count of our own, which is the only version that
    can be right. It is reported as **a number and never a percentage**: the window it would be
    divided by is not in this event, it is a property of the model -- which `_model_of` reads
    from the same stream, so that nobody downstream has to assume one.
    """
    usage = _usage_in(raw)
    if usage is None:
        return 0
    return sum(
        int(usage.get(key, 0) or 0)
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )


def _correct_identity(project: Path, raw: dict[str, Any]) -> None:
    """A forked conversation is given its id by the agent, so the record is corrected here.

    Asked rather than assumed (§5.8): we hand `--fork-session` over and find out what it
    decided from the `init` line, instead of predicting an id it never agreed to.

    **What the previous id was decides whether it is dropped.** A uuid we invented and the
    agent replaced was never a conversation, and leaving it in the list offers a person
    something to resume that does not exist. An id we asked to *resume* is a real conversation
    -- and a fork of it must keep it, because going back to it is the entire point of forking.
    Treating both the same is how forking session 1 came to delete session 1.
    """
    if raw.get("type") != "system" or raw.get("subtype") != "init":
        return
    told = str(raw.get("session_id") or "")
    state = _read_state(project)
    if not told or not state or state.get("session") == told:
        return

    previous = str(state.get("session") or "")
    state["session"] = told

    # The transcript follows the identity. Until now it was under a key of its own -- a fork's
    # own, so that it could not truncate what it forked -- and from here it is under the id
    # the conversation will be resumed by, which is the name it has to be found under later.
    was = str(state.get("log") or "")
    if was and was != told:
        with contextlib.suppress(OSError):
            _log_for(project, was).replace(_log_for(project, told))
        if _said_path(project, was).is_file():
            with contextlib.suppress(OSError):
                _said_path(project, was).replace(_said_path(project, told))
        state["log"] = told

    with contextlib.suppress(OSError):
        _state_path(project).write_text(json.dumps(state, indent=2), encoding="utf-8")

    known = [
        item
        for item in list_sessions(project)
        if item.get("id") != told and not (state.get("invented") and item.get("id") == previous)
    ]
    entry = {"id": told, "label": str(state.get("label") or "fork"), "at": _now()}
    _write_sessions(project, [entry, *known])


def _current(project: Path) -> str | None:
    state = _read_state(project)
    return str(state.get("session")) if state and state.get("session") else None


#: The most of a tool's input or output that travels with an event.
#:
#: A `Read` of a large file answers with the whole file, and a transcript is not a place to
#: put one. The **log keeps everything** -- this is the part a panel shows, and it says when
#: it has cut something rather than trailing off as if that were all there was.
EXCERPT = 2000


def _read_event(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """One line of the agent's stream, as the events an interface can show.

    Once deliberately shallow -- a status line wants "editing app/api/reports.py" and no more.
    A transcript wants the chain: what the agent thought, which tool it called *with what*,
    and what came back. So the event carries `detail` and `id` as well, and a tool result is
    surfaced whether or not it failed. This is a change of mind rather than a correction:
    shallow was right for the thing it was written for.

    `id` is the agent's own `tool_use_id`, which is what lets a result be shown against the
    call it answers instead of merely after it.
    """
    kind = raw.get("type")

    if kind == "system" and raw.get("subtype") == "thinking_tokens":
        # **The agent's own running estimate**, not one of ours. Usage proper is reported
        # exactly twice -- once at the start of a message and once at its end -- so a number
        # that moves while it works could only have been invented here. This one is streamed,
        # it is labelled an estimate by the agent, and it is passed on as one.
        return [_event("spending", str(int(raw.get("estimated_tokens", 0) or 0)))]

    if kind == "system" and raw.get("subtype") == "init":
        # Read back rather than assumed: this is how a silently ignored flag was caught.
        return [
            _event(
                "ready",
                f"session ready · {raw.get('model', '?')} · {raw.get('permissionMode', '?')}",
            )
        ]

    if kind == "assistant":
        events: list[dict[str, Any]] = []
        for block in _blocks_of(raw):
            block_type = block.get("type")
            if block_type == "text" and block.get("text", "").strip():
                events.append(_event("says", block["text"].strip()))
            elif block_type == "thinking" and str(block.get("thinking", "")).strip():
                events.append(_event("thinking", str(block["thinking"]).strip()[:EXCERPT]))
            elif block_type == "tool_use":
                events.append(
                    _event(
                        "doing",
                        _doing(block),
                        file=str(block.get("input", {}).get("file_path", "")),
                        detail=_given(block),
                        identifier=str(block.get("id", "")),
                        tool=str(block.get("name", "")),
                    )
                )
        return events

    if kind == "user":
        events = []
        for block in _blocks_of(raw):
            if block.get("type") != "tool_result":
                continue
            # A refusal has to be visible because there is no permission round-trip to
            # intercept (Q17); an ordinary result is shown because a chain without its
            # answers is a list of intentions.
            said = _cut(_text_of(block))
            waiting = _is_waiting_for_approval(said)
            events.append(
                _event(
                    "blocked" if block.get("is_error") else "did",
                    # Cut first, then explained: the explanation is the part that must
                    # survive, and an excerpt that dropped it would be the old silence again.
                    _unanswerable(said),
                    # Marked rather than left to be recognised by its wording: an interface
                    # that matched on "requires approval" would be reading the agent's prose
                    # to decide what to offer, and prose is not an interface (§5.8, one level
                    # up). This is the one refusal a person can act on from here.
                    detail="approval" if waiting else "",
                    identifier=str(block.get("tool_use_id", "")),
                )
            )
        return events

    if kind == "stream_event":
        # A piece of the answer as it is written. The complete `assistant` message still
        # arrives at the end and is authoritative -- these are what fills the gap until it
        # does, and the reader replaces them with it rather than keeping both.
        event = raw.get("event") or {}
        if event.get("type") != "content_block_delta":
            return []
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            return [_event("delta", str(delta.get("text", "")), detail="text")]
        if delta.get("type") == "thinking_delta":
            return [_event("delta", str(delta.get("thinking", "")), detail="thinking")]
        return []

    if kind == "result":
        return [_event("done", str(raw.get("stop_reason") or "done"))]

    return []


def _event(
    kind: str,
    text: str,
    file: str = "",
    detail: str = "",
    identifier: str = "",
    tool: str = "",
) -> dict[str, Any]:
    # `tool` is the agent's own name for what it called -- `Bash`, `Read`, `Edit` -- kept
    # beside the readable phrase rather than instead of it. A transcript wants to say
    # "running pytest -q"; a block around it wants to be labelled with the tool.
    return {
        "kind": kind,
        "text": text,
        "file": file,
        "detail": detail,
        "id": identifier,
        "tool": tool,
    }


#: What a refusal says when it is waiting for an answer nobody can give.
#:
#: The agent asks for approval the only way the transport allows -- by refusing and saying
#: so -- and there is **no message shape to say yes with** (Q17). So "requires approval"
#: read, correctly and uselessly, as a prompt that never arrived: the person waited for a
#: dialogue this application cannot show them.
#:
#: Matched on the agent's own words, and added to rather than replacing them: what a tool
#: said is the tool's, and this application only says what it knows that the tool does not --
#: which of *our* settings ends the wait.
_WAITING_FOR_APPROVAL = (
    "requires approval",
    "requires permission",
    "permission to use",
    # The agent words this differently depending on what it wanted -- a command, a file
    # outside the project -- and every wording is the same question. Collected from what the
    # running CLI actually said, which is why the list grows rather than being predicted.
    "haven't granted",
    "have not granted",
    "requested permissions",
)

_NO_ONE_TO_ASK = (
    "\n\n— nothing here can approve this: the panel has no way to answer a request for"
    " permission. Set the session's mode to \"Don't ask\" to let commands run."
)


def _is_waiting_for_approval(text: str) -> bool:
    """Is this refusal one that a permission setting would have prevented?"""
    lowered = text.lower()
    return any(phrase in lowered for phrase in _WAITING_FOR_APPROVAL)


def _unanswerable(text: str) -> str:
    """A refusal that is waiting for approval, told what would end the wait."""
    if _is_waiting_for_approval(text):
        return f"{text}{_NO_ONE_TO_ASK}"
    return text


def _cut(text: str) -> str:
    """An excerpt, and it says so. Trailing off would read as the whole answer."""
    if len(text) <= EXCERPT:
        return text
    return f"{text[:EXCERPT]}\n… {len(text) - EXCERPT} more characters, in the log"


def _doing(block: dict[str, Any]) -> str:
    """What a tool call is, in the words a person would use for it."""
    name = str(block.get("name", "?"))
    given = block.get("input", {}) or {}
    target = given.get("file_path") or given.get("path") or given.get("pattern") or ""
    if name in {"Edit", "Write", "NotebookEdit"}:
        return f"editing {Path(str(target)).name or target}" if target else f"{name.lower()}ing"
    if name == "Read":
        return f"reading {Path(str(target)).name or target}" if target else "reading"
    if name == "Bash":
        return f"running {str(given.get('command', ''))[:60]}"
    return name


def _given(block: dict[str, Any]) -> str:
    """What a tool was called with, as one readable piece.

    Rendered rather than passed through: the input is the agent's JSON, and a panel showing
    it raw would be showing a data structure where a person is trying to follow a story.
    """
    given = block.get("input", {}) or {}
    if not isinstance(given, dict):
        return _cut(str(given))
    parts = []
    for name, value in given.items():
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        parts.append(f"{name}: {rendered}")
    return _cut("\n".join(parts))


def _blocks_of(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """The content blocks of one message, however this line happens to carry them.

    **A message's content is a list of blocks or a bare string**, and the second shape is not
    a curiosity: `/compact` replaces the conversation with a summary and sends it as plain
    text, and a local command's output arrives the same way. Iterating a string yields its
    characters, and the first `block.get("type")` on a character raised -- which reached the
    panel as a blocked turn, on a compaction that had in fact succeeded.

    A string has no blocks, so this returns none. What it says is not lost: the summary is
    the agent's own record of the conversation it is continuing, and the conversation is what
    the transcript already shows. `_text_of` has always known content comes in two shapes;
    this is the same knowledge one level up.
    """
    content = (raw.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _text_of(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def stop_session(project: Path | str) -> SessionResult:
    """Close the session -- this sidecar's, or one a crashed sidecar left behind."""
    import os
    import signal

    root = Path(project).resolve()
    state = _read_state(root)
    process = _LIVE.pop(str(root), None)

    if process is not None:
        with contextlib.suppress(OSError):
            if process.stdin is not None:
                process.stdin.close()

    pid = int(state.get("pid", 0)) if state else 0
    if pid and _alive(pid):
        # A session started in its own group takes its children with it. Failing to signal
        # is not a failure to stop: the record is cleared either way, and a process nobody
        # can signal is not one this session is going to talk to again.
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(pid), signal.SIGTERM)

    if process is not None:
        # Reaped, not merely killed: a child nobody waited on answers "yes" to being alive.
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover -- the agent ignored SIGTERM
            process.kill()
            process.wait(timeout=5)

    _state_path(root).unlink(missing_ok=True)
    return SessionResult(True, "session closed")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def close_everything_started_here() -> None:
    """End every session this sidecar opened. A session is the sidecar's lifetime."""
    for root in list(_LIVE):
        stop_session(root)
