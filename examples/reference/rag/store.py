"""The index this package searches.

It is held in memory for the length of the process. That is a real limitation and a
deliberate one: a store on disk needs a path, a path shared between test runs is shared
state, and shared state is the first thing that makes a test suite non-deterministic.
Swapping this for pgvector or Qdrant changes nothing outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag.settings import RagSettings


@dataclass(frozen=True)
class Chunk:
    source: str
    text: str


_CHUNKS: list[Chunk] = []


def clear() -> None:
    """Empty the index. Ordinary housekeeping, and what a test uses instead of a temp path."""
    _CHUNKS.clear()


def add(paths: list[str], settings: RagSettings) -> None:
    for raw in paths:
        path = Path(raw)
        text = path.read_text(encoding="utf-8")
        for piece in _split(text, settings.chunk_size, settings.overlap):
            _CHUNKS.append(Chunk(source=str(path), text=piece))


def matches(query: str, settings: RagSettings) -> list[Chunk]:
    """Rank by how many of the query's words a chunk holds. Ties keep insertion order.

    Deliberately the dumbest thing that can be called retrieval: the point of this package
    is its boundary, and a scoring function nobody can predict makes the boundary harder to
    read rather than easier.
    """
    words = {word.lower() for word in query.split() if word}
    scored = [(sum(word in chunk.text.lower() for word in words), chunk) for chunk in _CHUNKS]
    hits = [(score, chunk) for score, chunk in scored if score]
    hits.sort(key=lambda pair: -pair[0])
    return [chunk for _, chunk in hits[: settings.top_k]]


def _split(text: str, size: int, overlap: float) -> list[str]:
    step = max(1, int(size * (1 - overlap)))
    return [text[start : start + size] for start in range(0, max(len(text), 1), step)]
