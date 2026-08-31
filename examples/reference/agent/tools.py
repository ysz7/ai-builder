"""What the agent can do besides talk.

A tool is a thin wrapper: it calls existing project code and contains no logic of its own.
The import below is the only reason there is an edge from this package to `rag`.
"""

from __future__ import annotations

from rag import search


def look_up(query: str, passages: int) -> list[str]:
    """Passages from the project's documents that bear on `query`."""
    return [chunk.text for chunk in search(query, top_k=passages)]
