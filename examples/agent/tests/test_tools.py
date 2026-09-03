"""Each tool, called directly. One file per tool means one set of tests per tool."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.tools.arithmetic import calculate
from agent.tools.clock import today
from agent.tools.notes import remember


@pytest.fixture(autouse=True)
def notes_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTES_PATH", str(tmp_path / "notes.txt"))


def test_arithmetic_is_worked_out_rather_than_guessed() -> None:
    assert calculate("2 ** 10") == "1024.0"
    assert calculate("10 / 4") == "2.5"


def test_anything_that_is_not_arithmetic_is_refused_rather_than_run() -> None:
    """The argument comes from a model, so this is parsed rather than evaluated."""
    assert "not arithmetic" in calculate("__import__('os').system('echo no')")
    assert "not arithmetic" in calculate("2 +")


def test_the_date_comes_from_the_machine() -> None:
    assert today() == datetime.now(timezone.utc).date().isoformat()


def test_a_note_is_kept_between_calls() -> None:
    assert "noted" in remember("buy milk")
    remember("feed otters")

    assert remember("") == "buy milk\nfeed otters"


def test_nothing_remembered_says_so() -> None:
    assert remember("") == "nothing yet"
