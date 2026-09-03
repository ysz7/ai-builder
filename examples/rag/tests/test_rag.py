"""What the package promises: put documents in, get passages out."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag import RagSettings, index, search
from rag.store import clear


@pytest.fixture(autouse=True)
def own_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An index per test. A shared one is shared state, and shared state is a flaky suite."""
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "index.json"))
    clear(RagSettings())


def document(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_document_can_be_found_after_it_is_indexed(tmp_path: Path) -> None:
    index([document(tmp_path, "otters.txt", "Otters hold hands while they sleep.")])

    found = search("otters")

    assert len(found) == 1
    assert "hold hands" in found[0].text


def test_nothing_indexed_is_an_empty_answer_and_not_an_error() -> None:
    assert search("anything") == []


def test_the_closest_passage_comes_first(tmp_path: Path) -> None:
    index([document(tmp_path, "a.txt", "otters eat urchins")])
    index([document(tmp_path, "b.txt", "otters hold hands and otters float")])

    found = search("otters hold")

    assert "hold hands" in found[0].text


def test_top_k_is_honoured_per_call(tmp_path: Path) -> None:
    for number in range(4):
        index([document(tmp_path, f"{number}.txt", f"otters number {number}")])

    assert len(search("otters", top_k=2)) == 2
