"""What the project stores, exercised against a database it makes itself.

SQLite in a temporary file, because a test that needed Postgres running would be a test that
fails on a laptop for a reason that has nothing to do with the code. The models are the same
ones the deployed stack uses; only the URL differs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

import repositories
from repositories import recent_turns, save_turn


@pytest.fixture(autouse=True)
def database(tmp_path: Path) -> None:
    repositories.use(create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True))


def test_a_turn_is_saved_and_read_back() -> None:
    save_turn("what do otters do", "they hold hands")

    found = recent_turns()

    assert [turn.question for turn in found] == ["what do otters do"]
    assert found[0].answer == "they hold hands"


def test_the_newest_turn_comes_first() -> None:
    save_turn("first", "one")
    save_turn("second", "two")

    assert [turn.question for turn in recent_turns()] == ["second", "first"]


def test_the_limit_is_honoured() -> None:
    for number in range(5):
        save_turn(f"question {number}", "answer")

    assert len(recent_turns(limit=2)) == 2
