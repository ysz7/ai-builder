from __future__ import annotations

from pathlib import Path

import pytest

from rag import index, search
from rag.store import clear


@pytest.fixture(autouse=True)
def empty_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets its own index file, and starts with nothing in it.

    The path rather than the process is what isolates these now. `RagSettings` reads it from
    the environment, so pointing it at a temporary file is all it takes -- and it is what
    keeps the suite deterministic when the index itself outlives a process.
    """
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "index.json"))
    clear()


def document(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_indexing_makes_a_document_findable(tmp_path: Path) -> None:
    index([document(tmp_path, "otters.txt", "Otters hold hands while they sleep.")])

    found = search("otters")

    assert found
    assert "hold hands" in found[0].text


def test_searching_an_empty_index_finds_nothing() -> None:
    assert search("otters") == []


def test_a_query_with_no_match_finds_nothing(tmp_path: Path) -> None:
    index([document(tmp_path, "otters.txt", "Otters hold hands while they sleep.")])

    assert search("locomotives") == []


def test_top_k_bounds_how_much_comes_back(tmp_path: Path) -> None:
    index(
        [
            document(tmp_path, "one.txt", "otters swim"),
            document(tmp_path, "two.txt", "otters float"),
            document(tmp_path, "three.txt", "otters dive"),
        ]
    )

    assert len(search("otters", top_k=2)) == 2
