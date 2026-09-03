"""What a person tunes about the agent."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    max_steps: int = 3
    passages: int = 2
    cite_sources: bool = True
