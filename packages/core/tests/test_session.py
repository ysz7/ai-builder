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
