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
    path = project / AGENT_LOG_PATH
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
    ids = [item["id"] for item in answer.sessions]
    assert "grown-up-id" in ids
    # The id we started with was never a conversation; leaving it in the list offers a
    # person something to resume that does not exist.
    assert "abc-123" not in ids


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
