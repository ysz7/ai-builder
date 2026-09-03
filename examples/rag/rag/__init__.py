"""Retrieval over whatever documents this project is given.

`index` puts documents in, `search` gets passages out. Both are re-exported here, because
that is where the rest of the project reads them from.
"""

from __future__ import annotations

from rag.settings import RagSettings
from rag.store import Chunk, add, matches

__all__ = ["Chunk", "RagSettings", "index", "search"]


def index(paths: list[str]) -> None:
    """Read each path and add it to the index."""
    add(paths, RagSettings())


def search(query: str, **kw: object) -> list[Chunk]:
    """The passages most like `query`, most alike first."""
    settings = RagSettings()
    top_k = kw.get("top_k")
    if isinstance(top_k, int):
        settings = settings.model_copy(update={"top_k": top_k})
    return matches(query, settings)
