"""What a person tunes about the agent.

The model name is a setting rather than a constant so it can be changed from the interface
without editing code. `offline` is what keeps this project's own tests honest: with it on,
nothing here reaches a network, which is the state the suite runs in.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    model: str = "ollama/llama3.1"
    #: How many tool results the reply may quote.
    steps: int = 3
    #: When true the agent answers from its tools alone and calls no model.
    offline: bool = True
