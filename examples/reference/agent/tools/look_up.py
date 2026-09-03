"""One tool: passages from the project's documents.

A tool is a thin wrapper -- it calls existing project code and contains no logic of its own
-- and it is one file, because a module in `agent/tools/` that defines a public function is
a node. The import below is the only reason there is an edge from this tool to `rag`, and
it lands on `rag`'s `search` port because that is the name it takes.
"""

from __future__ import annotations

from rag import search


def look_up(query: str, passages: int) -> list[str]:
    """Passages from the project's documents that bear on `query`."""
    return [chunk.text for chunk in search(query, top_k=passages)]
