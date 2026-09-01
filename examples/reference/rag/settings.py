"""What a person tunes about retrieval.

Only behavioural values live here: change one and the answers change. Anything that only
matters to the implementation stays in the implementation.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class RagSettings(BaseSettings):
    #: Where the index is kept. A behavioural value like the rest: point it somewhere else
    #: and this package searches something else. It is a setting rather than a constant so a
    #: test can give each run its own file -- an index shared between runs is shared state.
    index_path: str = ".rag-index.json"
    chunk_size: int = 500
    overlap: float = 0.15
    top_k: int = 4
    hybrid: bool = True
    reranker: bool = False
