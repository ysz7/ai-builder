"""Where the storage is.

The URL is a setting rather than a constant so it can be pointed at a test database, and its
default is the local development one the compose stack brings up. Nothing secret is here: a
real deployment sets `DATABASE_URL` in its own environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class StorageSettings(BaseSettings):
    database_url: str = "postgresql+psycopg://reference:reference@localhost:5432/reference"
    echo_sql: bool = False
