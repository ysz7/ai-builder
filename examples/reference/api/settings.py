"""What a person tunes about the web layer."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class ApiSettings(BaseSettings):
    page_size: int = 20
    greeting: str = "framestack reference"
    debug: bool = False
