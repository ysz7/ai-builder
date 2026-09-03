"""What a person tunes about background work."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class WorkerSettings(BaseSettings):
    max_retries: int = 3
    batch_size: int = 10
    queue: str = "default"
