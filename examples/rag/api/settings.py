"""What a person tunes about the web layer."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class ApiSettings(BaseSettings):
    upload_dir: str = "uploads"
    page_size: int = 10
