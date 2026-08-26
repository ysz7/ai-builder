"""The agent as a process this toolchain starts and talks to (Q16, amended).

Almost none of this starts an agent. What is worth testing here is the part that would be
wrong quietly: how a line of the stream becomes something an interface can act on, and what
happens when there is no session, no agent, or a half-written line. Those are exercised
against a log written by hand -- a real turn costs somebody's tokens and proves nothing that
this does not.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_api import validate, wire_form

from aibuilder_core.api import AGENT_SESSION_SCHEMA, agent_poll, agent_session
from aibuilder_core.layout import create_project
from aibuilder_core.session import (
    AGENT_LOG_PATH,
    agent_available,
    poll_session,
    say,
    session_status,
    stop_session,
)


def log(project: Path, *lines: dict[str, object]) -> None:
    """Write a stream by hand, where the session on record would have written it.

    A transcript lives per conversation now, so "the log" is whichever file the open session
    is writing to -- and only a project with no session at all falls back to the single file.
    """
    from aibuilder_core.session import _current_log

    path = _current_log(project) or project / AGENT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def kinds(project: Path) -> list[tuple[str, str]]:
    answer = poll_session(project)
    return [(event["kind"], event["text"]) for event in answer.events]


# -- nothing is ever started implicitly -------------------------------------------


def test_asking_whether_an_agent_exists_starts_nothing(tmp_path: Path) -> None:
    """P11, in the one place it would be most tempting to be helpful."""
    answer = session_status(tmp_path)

    assert answer.running is False
    assert not (tmp_path / ".aibuilder").exists()


def test_speaking_without_a_session_is_refused_with_a_reason(tmp_path: Path) -> None:
    """And it does not open one on the way past. Refusals are results, never faults."""
    answer = say(tmp_path, "do something")

    assert answer.ok is False
    assert "start one first" in answer.detail


def test_polling_a_project_with_no_session_says_so(tmp_path: Path) -> None:
    answer = poll_session(tmp_path)

    assert answer.ok is False
    assert answer.offset == 0


def test_stopping_nothing_is_not_an_error(tmp_path: Path) -> None:
    """Stopping is idempotent: a session that is already gone is the desired state."""
    assert stop_session(tmp_path).ok is True


# -- one line of the stream, as an interface can use it ---------------------------


def test_a_tool_call_becomes_what_the_agent_is_doing(tmp_path: Path) -> None:
    """The status line wants words, and the canvas wants the file so it can light nodes."""
    log(
        tmp_path,
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "/p/app/api/reports.py"},
                    }
                ]
            },
        },
    )

    answer = poll_session(tmp_path)

    assert answer.events[0]["kind"] == "doing"
    assert answer.events[0]["text"] == "editing reports.py"
    assert answer.events[0]["file"] == "/p/app/api/reports.py"


def test_a_refused_tool_is_surfaced_rather_than_swallowed(tmp_path: Path) -> None:
    """It is the whole permission surface there is (Q17).

    The stream carries no "may I?" to intercept -- a denied tool simply comes back as a
    failed result -- so an interface that ignored this would leave the person watching an
    agent apparently do nothing.
    """
    log(
        tmp_path,
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": "File is in a directory denied by your permissions.",
                    }
                ]
            },
        },
    )

    assert kinds(tmp_path) == [("blocked", "File is in a directory denied by your permissions.")]


def test_the_effective_settings_are_read_back_rather_than_assumed(tmp_path: Path) -> None:
    """Q17's rule: `init` echoes what is actually in force, and a flag can be ignored."""
    log(
        tmp_path,
        {
            "type": "system",
            "subtype": "init",
            "model": "claude-opus-5",
            "permissionMode": "default",
        },
    )

    kind, text = kinds(tmp_path)[0]

    assert kind == "ready"
    assert "claude-opus-5" in text and "default" in text


def test_the_end_of_a_turn_is_an_event_of_its_own(tmp_path: Path) -> None:
    """It is what stops the polling and what asks for the graph again."""
    log(tmp_path, {"type": "result", "stop_reason": "end_turn"})

    assert kinds(tmp_path) == [("done", "end_turn")]


def test_a_half_written_line_costs_nothing(tmp_path: Path) -> None:
    """The log is being appended to while it is read; the next poll gets the line whole."""
    path = tmp_path / AGENT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type": "result", "stop_reason": "end_turn"}\n{"type": "assis', "utf-8")

    assert kinds(tmp_path) == [("done", "end_turn")]


def test_polling_resumes_from_the_offset_it_was_given(tmp_path: Path) -> None:
    """Nothing is pushed and nothing is buffered here (P13): the caller keeps the offset."""
    log(tmp_path, {"type": "result", "stop_reason": "end_turn"})
    first = poll_session(tmp_path)

    again = poll_session(tmp_path, first.offset)

    assert first.events and again.events == ()
    assert again.offset == first.offset


# -- a new project is an empty directory ------------------------------------------


def test_a_new_project_is_created_empty(tmp_path: Path) -> None:
    """A scaffold would put nodes on the graph nobody asked for."""
    result = create_project(tmp_path, "fresh")

    assert result.ok is True
    assert Path(result.detail).is_dir()
    assert list(Path(result.detail).iterdir()) == []


def test_a_folder_with_something_in_it_is_refused(tmp_path: Path) -> None:
    """Adopting somebody's files quietly would be a surprise with their work inside."""
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "notes.txt").write_text("mine", encoding="utf-8")

    result = create_project(tmp_path, "taken")

    assert result.ok is False
    assert "open it instead" in result.detail


def test_a_project_needs_a_name(tmp_path: Path) -> None:
    assert create_project(tmp_path, "   ").ok is False


# -- the wire ----------------------------------------------------------------------


def test_the_session_payloads_match_the_declared_contract(tmp_path: Path) -> None:
    log(tmp_path, {"type": "result", "stop_reason": "end_turn"})

    validate(wire_form(agent_session(str(tmp_path))), AGENT_SESSION_SCHEMA)
    validate(wire_form(agent_poll(str(tmp_path), 0)), AGENT_SESSION_SCHEMA)


def test_whether_an_agent_exists_is_asked_of_the_machine() -> None:
    """Asked, never assumed (§5.8). Installed is not the same as authorised, and this
    claims only the first -- the second shows up as the agent's own words, in a turn."""
    available, version = agent_available()

    assert isinstance(available, bool)
    assert version == "" or "Claude" in version or version[0].isdigit()


def test_an_agent_installed_by_a_shell_is_found_from_a_window(monkeypatch, tmp_path) -> None:
    """An application launched from Finder inherits a minimal `PATH`.

    So `which` fails in the window and succeeds in the terminal, and "no agent on this
    machine" becomes true of one and false of the other -- correct-looking, and wrong in
    exactly the place a person would be using it.
    """
    from aibuilder_core import session

    installed = tmp_path / "claude"
    installed.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(session.shutil, "which", lambda _: None)
    monkeypatch.setattr(session, "FALLBACK_PATHS", (str(installed),))

    assert session.agent_binary() == str(installed)


def test_no_agent_anywhere_is_an_answer_not_a_crash(monkeypatch) -> None:
    from aibuilder_core import session

    monkeypatch.setattr(session.shutil, "which", lambda _: None)
    monkeypatch.setattr(session, "FALLBACK_PATHS", ())

    assert session.agent_binary() is None
    assert session.agent_available() == (False, "")


# -- how the three ways in are spelled --------------------------------------------


def spawn(monkeypatch, tmp_path: Path) -> list[list[str]]:
    """Record the command `start_session` builds without letting an agent run.

    The three ways in differ only in the flags at the end of the line, and getting them wrong
    is quiet: `--resume` without an id starts a new conversation, and `--resume` *without*
    `--fork-session` overwrites the branch a person asked to keep.
    """
    from aibuilder_core import session

    seen: list[list[str]] = []

    class Fake:
        pid = 4321
        stdin = None

        def __init__(self, command: list[str], **_: object) -> None:
            seen.append(command)

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(session, "agent_available", lambda: (True, "1.0.0"))
    monkeypatch.setattr(session, "agent_binary", lambda: "claude")
    # Nothing here may signal: the recorded pid is invented, and a real process could own it.
    monkeypatch.setattr(session, "_alive", lambda _: False)
    monkeypatch.setattr(session.subprocess, "Popen", Fake)
    monkeypatch.setattr(session, "_LIVE", {})
    return seen


def test_a_new_conversation_is_given_an_id_by_us(monkeypatch, tmp_path: Path) -> None:
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    answer = start_session(tmp_path)

    command = seen[0]
    assert "--session-id" in command
    assert command[command.index("--session-id") + 1] == answer.session
    assert "--resume" not in command and "--fork-session" not in command


def test_continuing_names_the_conversation_and_does_not_fork(monkeypatch, tmp_path: Path) -> None:
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123")

    command = seen[0]
    assert command[command.index("--resume") + 1] == "abc-123"
    # A continued conversation must not carry `--session-id` as well: two ways of naming the
    # same session is how one silently wins over the other.
    assert "--session-id" not in command
    assert "--fork-session" not in command


def test_a_fork_keeps_the_branch_it_came_from(monkeypatch, tmp_path: Path) -> None:
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123", fork=True)

    command = seen[0]
    assert command[command.index("--resume") + 1] == "abc-123"
    assert "--fork-session" in command


def test_the_prompt_is_appended_on_every_way_in(monkeypatch, tmp_path: Path) -> None:
    """`--resume` restores a conversation, and what it restores of the system prompt is not
    ours to assume -- so the file is handed over again every time (§3: one set of rules)."""
    from aibuilder_core.session import prompt_path, start_session

    seen = spawn(monkeypatch, tmp_path)
    start_session(tmp_path)
    start_session(tmp_path, resume="abc-123")
    start_session(tmp_path, resume="abc-123", fork=True)

    for command in seen:
        assert command[command.index("--append-system-prompt-file") + 1] == str(prompt_path())
        assert "Write(.aibuilder/**)" in command


def test_a_forks_real_id_is_taken_from_the_agent(monkeypatch, tmp_path: Path) -> None:
    """We hand `--fork-session` over and the agent picks the new id. Predicting it would put
    a session in the list that cannot be resumed, which only shows up much later."""
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123", fork=True)
    log(tmp_path, {"type": "system", "subtype": "init", "session_id": "grown-up-id"})

    answer = poll_session(tmp_path)

    assert answer.session == "grown-up-id"
    assert "grown-up-id" in [item["id"] for item in answer.sessions]


def test_a_fork_keeps_the_conversation_it_forked(monkeypatch, tmp_path: Path) -> None:
    """Going back to the original is the entire point of forking.

    This assertion used to say the opposite -- that the id started from is gone, reasoning it
    "was never a conversation". True of a uuid the agent replaced; false of a fork, where the
    previous id is a real conversation somebody asked to keep. The claim was written from the
    mechanism rather than from what a fork is for, and it locked the bug in.
    """
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123", fork=True)
    log(tmp_path, {"type": "system", "subtype": "init", "session_id": "grown-up-id"})

    ids = [item["id"] for item in poll_session(tmp_path).sessions]

    assert "abc-123" in ids
    assert "grown-up-id" in ids


def test_an_id_the_agent_replaced_is_dropped(monkeypatch, tmp_path: Path) -> None:
    """The other half of the same rule: a uuid we invented and the agent did not use never
    named a conversation, and offering it to resume offers something that does not exist."""
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    invented = start_session(tmp_path).session
    log(tmp_path, {"type": "system", "subtype": "init", "session_id": "the-agents-own"})

    ids = [item["id"] for item in poll_session(tmp_path).sessions]

    assert ids == ["the-agents-own"]
    assert invented not in ids


def test_the_model_is_read_from_the_stream_rather_than_assumed(tmp_path: Path) -> None:
    """A context ring divides by the model's window, and the windows differ by a factor of
    five. Which model answered is the agent's decision, so it is read, never guessed."""
    log(
        tmp_path,
        {"type": "system", "subtype": "init", "model": "claude-opus-5", "session_id": "s"},
        {"type": "assistant", "message": {"content": [], "usage": {"input_tokens": 10}}},
    )

    answer = poll_session(tmp_path)

    assert answer.model == "claude-opus-5"
    assert answer.context == 10


def test_a_session_that_never_says_which_model_claims_none(tmp_path: Path) -> None:
    log(tmp_path, {"type": "assistant", "message": {"content": [], "usage": {"input_tokens": 7}}})

    assert poll_session(tmp_path).model == ""


# -- switching conversations, which is not the same as starting one twice ---------


def live(monkeypatch) -> list[int]:
    """Make the recorded session look alive, without letting a signal reach anything.

    `os.killpg` is patched on the module itself because `stop_session` imports it locally --
    and a recorded pid is invented, so a real process could own it.
    """
    import os

    signalled: list[int] = []
    from aibuilder_core import session

    monkeypatch.setattr(session, "_alive", lambda _: True)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "killpg", lambda pid, _: signalled.append(pid))
    return signalled


def test_asking_for_the_conversation_already_open_starts_nothing(monkeypatch, tmp_path) -> None:
    """The one question "already open" answers. Pressing the same chip twice must not
    tear down the session it names and build it again."""
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123")
    live(monkeypatch)

    answer = start_session(tmp_path, resume="abc-123")

    assert answer.detail == "a session is already open"
    assert len(seen) == 1


def test_another_conversation_is_switched_to_rather_than_refused(monkeypatch, tmp_path) -> None:
    """Naming a different conversation is a deliberate switch. Answering it with the session
    that happens to be running is how the conversation list came to do nothing at all."""
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123")
    live(monkeypatch)

    answer = start_session(tmp_path, resume="def-456")

    assert answer.session == "def-456"
    assert len(seen) == 2
    assert seen[1][seen[1].index("--resume") + 1] == "def-456"


def test_a_new_conversation_while_one_runs_is_a_new_conversation(monkeypatch, tmp_path) -> None:
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path)
    live(monkeypatch)

    second = start_session(tmp_path)

    assert second.session != first.session
    assert len(seen) == 2


def test_forking_the_open_conversation_is_not_already_open(monkeypatch, tmp_path) -> None:
    """A fork of the live session names the same id and means something else entirely --
    keep this branch, start another beside it."""
    from aibuilder_core.session import start_session

    seen = spawn(monkeypatch, tmp_path)
    start_session(tmp_path, resume="abc-123")
    live(monkeypatch)

    start_session(tmp_path, resume="abc-123", fork=True)

    assert len(seen) == 2
    assert "--fork-session" in seen[1]


# -- the list of conversations ----------------------------------------------------


def test_resuming_a_known_conversation_leaves_it_where_it_was(monkeypatch, tmp_path) -> None:
    """Reordering on resume makes a switch look exactly like nothing having happened: the
    chip a person pressed jumps to the front, which is where the active one already was."""
    from aibuilder_core.session import list_sessions, start_session

    spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path).session
    second = start_session(tmp_path).session
    assert first is not None and second is not None

    before = [item["id"] for item in list_sessions(tmp_path)]
    start_session(tmp_path, resume=first)

    assert [item["id"] for item in list_sessions(tmp_path)] == before
    assert before == [second, first]


def test_forgetting_drops_the_reference_and_not_the_transcript(monkeypatch, tmp_path) -> None:
    from aibuilder_core.session import forget_session, list_sessions, start_session

    spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path).session
    second = start_session(tmp_path).session
    assert first is not None and second is not None
    live(monkeypatch)

    answer = forget_session(tmp_path, first)

    assert [item["id"] for item in list_sessions(tmp_path)] == [second]
    assert first not in [item["id"] for item in answer.sessions]


def test_forgetting_the_open_conversation_closes_it_first(monkeypatch, tmp_path) -> None:
    """A list entry is the only way back to a session, so dropping it while it ran would
    leave a process nothing could name."""
    from aibuilder_core.session import forget_session, session_status, start_session

    spawn(monkeypatch, tmp_path)
    opened = start_session(tmp_path).session
    assert opened is not None
    live(monkeypatch)

    forget_session(tmp_path, opened)

    assert session_status(tmp_path).running is False


def test_a_conversation_can_be_given_a_name(monkeypatch, tmp_path) -> None:
    """The label is the only field of a conversation that belongs to the person."""
    from aibuilder_core.session import list_sessions, rename_session, start_session

    spawn(monkeypatch, tmp_path)
    opened = start_session(tmp_path).session
    assert opened is not None

    answer = rename_session(tmp_path, opened, "  the   first   try  ")

    assert answer.ok is True
    # Whitespace is collapsed rather than stored: a chip is one line, and a name typed with
    # a stray tab in it would render as a gap nobody can see the cause of.
    assert [item["label"] for item in list_sessions(tmp_path)] == ["the first try"]


def test_an_empty_name_puts_the_default_back(monkeypatch, tmp_path) -> None:
    from aibuilder_core.session import list_sessions, rename_session, start_session

    spawn(monkeypatch, tmp_path)
    opened = start_session(tmp_path).session
    assert opened is not None
    rename_session(tmp_path, opened, "something")

    rename_session(tmp_path, opened, "   ")

    assert [item["label"] for item in list_sessions(tmp_path)] == ["new"]


def test_a_name_is_capped_rather_than_refused(monkeypatch, tmp_path) -> None:
    """A chip is not a place to write in, and refusing a long name would be a dialog about
    a field that should simply hold what fits."""
    from aibuilder_core.session import NAME_LIMIT, list_sessions, rename_session, start_session

    spawn(monkeypatch, tmp_path)
    opened = start_session(tmp_path).session
    assert opened is not None

    rename_session(tmp_path, opened, "x" * 200)

    assert len(list_sessions(tmp_path)[0]["label"]) == NAME_LIMIT


def test_naming_a_conversation_that_is_not_there_is_refused(tmp_path: Path) -> None:
    from aibuilder_core.session import rename_session

    answer = rename_session(tmp_path, "no-such-id", "whatever")

    assert answer.ok is False
    assert "no-such-id" in answer.detail


# -- the chain of a turn -----------------------------------------------------------


def test_a_tool_call_carries_what_it_was_called_with(tmp_path: Path) -> None:
    """A chain of intentions with no arguments and no answers is not a chain."""
    log(
        tmp_path,
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "Bash",
                        "input": {"command": "pytest -q", "timeout": 60},
                    }
                ]
            },
        },
    )

    event = poll_session(tmp_path).events[0]

    assert event["kind"] == "doing"
    assert event["id"] == "call-1"
    assert "command: pytest -q" in event["detail"]
    assert "timeout: 60" in event["detail"]


def test_a_tool_result_is_shown_whether_or_not_it_failed(tmp_path: Path) -> None:
    """It used to be surfaced only when it was an error. A refusal has to be visible (Q17);
    an ordinary answer has to be visible too, or the chain shows only what was attempted."""
    log(
        tmp_path,
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "2 passed"}]
            },
        },
    )

    event = poll_session(tmp_path).events[0]

    assert (event["kind"], event["id"], event["text"]) == ("did", "call-1", "2 passed")


def test_a_refused_tool_is_still_told_apart_from_one_that_worked(tmp_path: Path) -> None:
    log(
        tmp_path,
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-2",
                        "is_error": True,
                        "content": "denied",
                    }
                ]
            },
        },
    )

    assert poll_session(tmp_path).events[0]["kind"] == "blocked"


def test_an_enormous_result_is_excerpted_and_says_so(tmp_path: Path) -> None:
    """A `Read` of a large file answers with the whole file. Trailing off would read as the
    whole answer; the log keeps everything either way."""
    from aibuilder_core.session import EXCERPT

    log(
        tmp_path,
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "c", "content": "x" * (EXCERPT + 500)}
                ]
            },
        },
    )

    text = poll_session(tmp_path).events[0]["text"]

    assert len(text) < EXCERPT + 200
    assert "500 more characters" in text


def test_thinking_is_kept_rather_than_dropped(tmp_path: Path) -> None:
    log(
        tmp_path,
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}},
    )

    assert poll_session(tmp_path).events[0] == {
        "kind": "thinking",
        "text": "hmm",
        "file": "",
        "detail": "",
        "id": "",
    }


def test_an_answer_arrives_as_deltas_before_it_arrives_whole(tmp_path: Path) -> None:
    """The complete message is still authoritative -- the deltas fill the gap until it comes,
    and a reader replaces them with it rather than showing the answer twice."""
    log(
        tmp_path,
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "OK"}},
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "let me see"},
            },
        },
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "OK"}]}},
    )

    events = poll_session(tmp_path).events

    assert [(e["kind"], e["detail"]) for e in events[:2]] == [
        ("delta", "text"),
        ("delta", "thinking"),
    ]
    assert events[2]["kind"] == "says"


def test_a_stream_event_that_is_not_a_delta_says_nothing(tmp_path: Path) -> None:
    """`message_start`, `content_block_stop` and the rest are the protocol talking about
    itself, and a transcript is not where that belongs."""
    log(
        tmp_path,
        {"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}},
    )

    assert poll_session(tmp_path).events == ()


# -- whose account a turn spends ---------------------------------------------------


def test_the_account_is_read_from_the_agent(monkeypatch) -> None:
    """Asked, never assumed (§5.8) -- and never held: the credential is the CLI's, put on
    this machine by its own browser flow, and the core has nothing to store."""
    from aibuilder_core import session

    told = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "email": "someone@example.com",
        "subscriptionType": "pro",
        "orgName": "Example",
    }
    monkeypatch.setattr(session, "agent_binary", lambda: "claude")
    monkeypatch.setattr(
        session.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": json.dumps(told), "returncode": 0})(),
    )

    who = session.account()

    assert (who.signed_in, who.email, who.plan) == (True, "someone@example.com", "pro")
    assert who.detail == ""


def test_an_agent_that_answers_nothing_useful_says_it_does_not_know(monkeypatch) -> None:
    """Not knowing is an answer. Guessing that somebody is signed in would put a person's
    subscription behind a button that claims to be ready."""
    from aibuilder_core import session

    monkeypatch.setattr(session, "agent_binary", lambda: "claude")
    monkeypatch.setattr(
        session.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "Logged in as someone", "returncode": 0})(),
    )

    who = session.account()

    assert who.signed_in is False
    assert "does not report" in who.detail


def test_no_agent_means_no_account_and_no_crash(monkeypatch) -> None:
    from aibuilder_core import session

    monkeypatch.setattr(session, "agent_binary", lambda: None)

    who = session.account()

    assert who.signed_in is False
    assert "no agent" in who.detail


def test_asking_who_is_signed_in_signs_nobody_in(monkeypatch) -> None:
    """A read that could start a browser flow would be P11's rule broken in the one place
    it is most surprising: looking at the panel."""
    from aibuilder_core import session

    ran: list[list[str]] = []
    monkeypatch.setattr(session, "agent_binary", lambda: "claude")
    monkeypatch.setattr(
        session.subprocess,
        "run",
        lambda command, **k: (
            ran.append(command),
            type("R", (), {"stdout": "{}", "returncode": 0})(),
        )[1],
    )

    session.account()

    assert ran == [["claude", "auth", "status"]]


def test_the_account_payload_matches_the_declared_contract(monkeypatch) -> None:
    from aibuilder_core import session
    from aibuilder_core.api import AGENT_ACCOUNT_SCHEMA, agent_account

    monkeypatch.setattr(session, "agent_binary", lambda: None)

    validate(wire_form(agent_account()), AGENT_ACCOUNT_SCHEMA)


# -- a conversation keeps what was said --------------------------------------------


def test_switching_conversations_does_not_destroy_the_one_left(monkeypatch, tmp_path) -> None:
    """One log per project, truncated on every start, meant the transcript of the
    conversation being left was gone -- the agent kept its own, ours did not exist."""
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path).session
    assert first is not None
    log(tmp_path, {"type": "assistant", "message": {"content": [{"type": "text", "text": "one"}]}})
    live(monkeypatch)

    start_session(tmp_path, resume="somewhere-else")

    assert [(e["kind"], e["text"]) for e in poll_session(tmp_path).events] == []
    # And the one that was left still has its own words, under its own name.
    kept = tmp_path / ".aibuilder" / "conversations" / f"{first}.log"
    assert "one" in kept.read_text(encoding="utf-8")


def test_coming_back_to_a_conversation_finds_what_it_said(monkeypatch, tmp_path) -> None:
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path).session
    assert first is not None
    log(tmp_path, {"type": "assistant", "message": {"content": [{"type": "text", "text": "one"}]}})
    live(monkeypatch)
    start_session(tmp_path, resume="somewhere-else")

    start_session(tmp_path, resume=first)

    assert [e["text"] for e in poll_session(tmp_path).events] == ["one"]


def test_a_fork_does_not_truncate_the_conversation_it_forks(monkeypatch, tmp_path) -> None:
    """The trap of this design: a fork spawns under the id it is forking, so a log keyed by
    that id would open the original's transcript and empty it before the real id is known."""
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path).session
    assert first is not None
    log(tmp_path, {"type": "assistant", "message": {"content": [{"type": "text", "text": "one"}]}})
    live(monkeypatch)

    start_session(tmp_path, resume=first, fork=True)

    original = tmp_path / ".aibuilder" / "conversations" / f"{first}.log"
    assert "one" in original.read_text(encoding="utf-8")


def test_a_forks_transcript_follows_the_id_the_agent_gave_it(monkeypatch, tmp_path) -> None:
    from aibuilder_core.session import start_session

    spawn(monkeypatch, tmp_path)
    first = start_session(tmp_path).session
    assert first is not None
    live(monkeypatch)
    start_session(tmp_path, resume=first, fork=True)
    log(tmp_path, {"type": "system", "subtype": "init", "session_id": "the-fork"})

    poll_session(tmp_path)

    assert (tmp_path / ".aibuilder" / "conversations" / "the-fork.log").is_file()


def test_forgetting_a_conversation_deletes_its_transcript(monkeypatch, tmp_path) -> None:
    """The one place a transcript is deleted. Everything else keeps it."""
    from aibuilder_core.session import forget_session, start_session

    spawn(monkeypatch, tmp_path)
    opened = start_session(tmp_path).session
    assert opened is not None
    log(tmp_path, {"type": "assistant", "message": {"content": [{"type": "text", "text": "one"}]}})
    live(monkeypatch)

    forget_session(tmp_path, opened)

    assert not (tmp_path / ".aibuilder" / "conversations" / f"{opened}.log").is_file()
