"""What a person tunes about retrieval.

Only behavioural values live here: change one and the answers change. Anything that only
matters to the implementation stays in the implementation.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class RagSettings(BaseSettings):
    chunk_size: int = 500
    overlap: float = 0.15
    top_k: int = 4
    hybrid: bool = True
    reranker: bool = False
