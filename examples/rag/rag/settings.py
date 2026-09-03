"""What a person tunes about retrieval."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class RagSettings(BaseSettings):
    #: Where the index is kept. A setting rather than a constant so a test can give each run
    #: its own file: an index shared between runs is shared state.
    index_path: str = ".rag-index.json"
    chunk_size: int = 400
    overlap: float = 0.2
    top_k: int = 3
