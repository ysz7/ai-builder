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
    "SESSIONS_PATH",
    "SessionResult",
    "agent_available",
    "agent_binary",
    "close_everything_started_here",
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
AGENT_LOG_PATH = Path(".aibuilder") / "session.log"
#: The conversations this project has had. A list of ids the agent owns, not a transcript --
#: what was said lives in the agent's own store, and this is only how to ask for it again.
SESSIONS_PATH = Path(".aibuilder") / "sessions.json"

#: What the agent may not touch. Its own evidence about itself is in there (Q16).
DENIED = ("Edit(.aibuilder/**)", "Write(.aibuilder/**)")

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
    if state and str(state.get("session")) == identifier:
        stop_session(root)

    known = [item for item in list_sessions(root) if item.get("id") != identifier]
    _write_sessions(root, known)
    return SessionResult(
        True,
        "conversation forgotten",
        session=_current(root),
        running=str(root) in _LIVE,
        available=agent_available()[0],
        sessions=tuple(known),
    )


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
            True, "no session open", available=True, version=version, sessions=list_sessions(root)
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
        )

    if existing:
        stop_session(root)

    identifier = resume or str(uuid.uuid4())
    log = root / AGENT_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"")

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
        # the transport gives us (Q17).
        "--permission-mode",
        "acceptEdits",
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
    if resume:
        command += ["--resume", resume]
        if fork:
            command.append("--fork-session")
    else:
        command += ["--session-id", identifier]

    try:
        with log.open("wb") as sink:
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
    )


def _label(resume: str | None, fork: bool) -> str:
    if fork:
        return "fork"
    return "continued" if resume else "new"


def say(project: Path | str, text: str) -> SessionResult:
    """Send one turn to the agent.

    A session has to be *written to*, and a pipe cannot be reopened from a pid — so a session
    left by a crashed sidecar can be stopped but not continued, and this says so rather than
    pretending otherwise.
    """
    root = Path(project).resolve()
    process = _LIVE.get(str(root))
    if process is None or process.poll() is not None:
        _LIVE.pop(str(root), None)
        return SessionResult(False, "no session is open here -- start one first")

    message = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    try:
        assert process.stdin is not None
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()
    except (OSError, ValueError) as exc:
        return SessionResult(False, f"the agent stopped listening: {exc}")
    return SessionResult(True, "sent", running=True)


def poll_session(project: Path | str, offset: int = 0) -> SessionResult:
    """What the agent has said since `offset`, as events a canvas can act on.

    Polled, never pushed (P13). Each line of the stream is read once and turned into the
    smallest thing the interface needs: what is happening, which file is being touched, and
    what was refused. Everything else stays in the log, where it can be read in full.
    """
    root = Path(project).resolve()
    log = root / AGENT_LOG_PATH
    if not log.is_file():
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
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line; the next poll gets it whole
        events.extend(_read_event(raw))
        context = _context_of(raw) or context
        model = _model_of(raw) or model
        _correct_identity(root, raw)

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


def _context_of(raw: dict[str, Any]) -> int:
    """How much the last turn carried, in tokens.

    Everything the model was sent: the fresh part, plus what was cached and read back. It is
    the agent's own accounting rather than a count of our own, which is the only version that
    can be right. It is reported as **a number and never a percentage**: the window it would be
    divided by is not in this event, it is a property of the model -- which `_model_of` reads
    from the same stream, so that nobody downstream has to assume one.
    """
    usage = raw.get("message", {}).get("usage") if raw.get("type") == "assistant" else None
    usage = usage or (raw.get("usage") if raw.get("type") == "result" else None)
    if not isinstance(usage, dict):
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
        for block in raw.get("message", {}).get("content", []) or []:
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
                    )
                )
        return events

    if kind == "user":
        events = []
        for block in raw.get("message", {}).get("content", []) or []:
            if block.get("type") != "tool_result":
                continue
            # A refusal has to be visible because there is no permission round-trip to
            # intercept (Q17); an ordinary result is shown because a chain without its
            # answers is a list of intentions.
            events.append(
                _event(
                    "blocked" if block.get("is_error") else "did",
                    _cut(_text_of(block)),
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
    kind: str, text: str, file: str = "", detail: str = "", identifier: str = ""
) -> dict[str, Any]:
    return {"kind": kind, "text": text, "file": file, "detail": detail, "id": identifier}


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
