"""The index this package searches: a JSON file, and the path is a setting.

`index` and `search` are separate calls, and separate calls may be separate processes — an
index that lived in memory could be filled or queried but never both.

Swapping this for pgvector or Qdrant changes nothing outside this module, which is the whole
point of the package having a boundary.
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
    return [Chunk(source=str(one["source"]), text=str(one["text"])) for one in held]


def _save(chunks: list[Chunk], settings: RagSettings) -> None:
    Path(settings.index_path).write_text(
        json.dumps([{"source": one.source, "text": one.text} for one in chunks], indent=2),
        encoding="utf-8",
    )


def clear(settings: RagSettings | None = None) -> None:
    """Empty the index. What a test uses to start from nothing."""
    Path((settings or RagSettings()).index_path).unlink(missing_ok=True)


def add(paths: list[str], settings: RagSettings) -> None:
    chunks = _load(settings)
    for raw in paths:
        text = Path(raw).read_text(encoding="utf-8")
        for piece in _split(text, settings.chunk_size, settings.overlap):
            chunks.append(Chunk(source=raw, text=piece))
    _save(chunks, settings)


def matches(query: str, settings: RagSettings) -> list[Chunk]:
    """Rank by how many of the query's words a chunk holds. Ties keep insertion order."""
    words = {word.lower() for word in query.split() if word}
    scored = [
        (sum(word in chunk.text.lower() for word in words), chunk) for chunk in _load(settings)
    ]
    hits = sorted(((score, chunk) for score, chunk in scored if score), key=lambda one: -one[0])
    return [chunk for _, chunk in hits[: settings.top_k]]


def _split(text: str, size: int, overlap: float) -> list[str]:
    step = max(1, int(size * (1 - overlap)))
    return [text[start : start + size] for start in range(0, max(len(text), 1), step)]
