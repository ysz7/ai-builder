from __future__ import annotations

from pathlib import Path

import pytest

from rag import search
from rag.store import clear
from worker import HANDLERS


@pytest.fixture(autouse=True)
def empty_index() -> None:
    clear()


def test_every_handler_is_callable() -> None:
    assert set(HANDLERS) == {"reindex", "echo"}
    assert all(callable(one) for one in HANDLERS.values())


def test_reindex_puts_documents_where_search_finds_them(tmp_path: Path) -> None:
    path = tmp_path / "otters.txt"
    path.write_text("Otters hold hands while they sleep.", encoding="utf-8")

    assert HANDLERS["reindex"]({"paths": [str(path)]}) == {"indexed": 1}
    assert search("otters")


def test_echo_gives_back_what_it_was_given() -> None:
    assert HANDLERS["echo"]({"a": 1}) == {"a": 1}
