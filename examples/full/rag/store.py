"""The index this package searches.

It is a **file**, and the path is a setting. It used to be a list in memory, which was
simpler and wrong for one reason that only shows up when the package is used rather than
tested: `index` and `search` are separate calls, and separate calls are separate processes.
An index that lives for the length of one process can be filled or queried but never both,
so a person who uploads a document and then searches for it finds nothing -- and the package
looks broken when the only broken thing was where its state lived.

A path shared between test runs would be shared state, which is the first thing that makes a
suite non-deterministic. That is why the path is a *setting* rather than a constant: the
suite points it at a temporary file per test, and nothing outside this module changes.

Swapping this for pgvector or Qdrant still changes nothing outside this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rag.settings import RagSettings


@dataclass(frozen=True)
class Chunk:
    source: str
    text: str


def _load(settings: RagSettings) -> list[Chunk]:
    path = Path(settings.index_path)
    if not path.is_file():
        return []
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        Chunk(source=str(one["source"]), text=str(one["text"]))
        for one in held
        if isinstance(one, dict) and "source" in one and "text" in one
    ]


def _save(chunks: list[Chunk], settings: RagSettings) -> None:
    path = Path(settings.index_path)
    if path.parent != Path():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([{"source": one.source, "text": one.text} for one in chunks], indent=2),
        encoding="utf-8",
    )


def clear(settings: RagSettings | None = None) -> None:
    """Empty the index. Ordinary housekeeping, and what a test uses to start from nothing."""
    Path((settings or RagSettings()).index_path).unlink(missing_ok=True)


def add(paths: list[str], settings: RagSettings) -> None:
    chunks = _load(settings)
    for raw in paths:
        path = Path(raw)
        text = path.read_text(encoding="utf-8")
        for piece in _split(text, settings.chunk_size, settings.overlap):
            chunks.append(Chunk(source=str(path), text=piece))
    _save(chunks, settings)


def matches(query: str, settings: RagSettings) -> list[Chunk]:
    """Rank by how many of the query's words a chunk holds. Ties keep insertion order.

    Deliberately the dumbest thing that can be called retrieval: the point of this package
    is its boundary, and a scoring function nobody can predict makes the boundary harder to
    read rather than easier.
    """
    words = {word.lower() for word in query.split() if word}
    chunks = _load(settings)
    scored = [(sum(word in chunk.text.lower() for word in words), chunk) for chunk in chunks]
    hits = [(score, chunk) for score, chunk in scored if score]
    hits.sort(key=lambda pair: -pair[0])
    return [chunk for _, chunk in hits[: settings.top_k]]


def _split(text: str, size: int, overlap: float) -> list[str]:
    step = max(1, int(size * (1 - overlap)))
    return [text[start : start + size] for start in range(0, max(len(text), 1), step)]
