"""What the package promises: a message in, a reply out, with no model and no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import run


@pytest.fixture(autouse=True)
def notes_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTES_PATH", str(tmp_path / "notes.txt"))


def test_a_message_naming_a_tool_gets_that_tool_s_answer() -> None:
    assert run("calculate: 2 * (3 + 4)") == "14.0"


def test_a_message_naming_nothing_says_what_there_is() -> None:
    reply = run("hello")

    assert "calculate" in reply and "remember" in reply


def test_a_tool_that_does_not_exist_is_said_rather_than_guessed_at() -> None:
    assert "no tool called" in run("teleport: to mars")


def test_steps_are_capped_per_call() -> None:
    message = "calculate: 1 + 1\ncalculate: 2 + 2\ncalculate: 3 + 3"

    assert run(message, steps=2) == "2.0 4.0"
