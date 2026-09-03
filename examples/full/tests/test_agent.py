from __future__ import annotations

from pathlib import Path

import pytest

from agent import run
from rag import index
from rag.store import clear


@pytest.fixture(autouse=True)
def empty_index() -> None:
    clear()


def test_it_answers_from_what_is_indexed(tmp_path: Path) -> None:
    path = tmp_path / "otters.txt"
    path.write_text("Otters hold hands while they sleep.", encoding="utf-8")
    index([str(path)])

    reply = run("otters")

    assert "hold hands" in reply


def test_it_says_so_when_it_has_nothing() -> None:
    assert "nothing on file" in run("locomotives")
