"""Where the notes tool keeps what it is told.

Its own settings class rather than a field on the agent's: `settings.py` is the one class the
builder edits, and it holds what changes the agent's *behaviour*. A file path the tool needs
is the implementation's business.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class NotesSettings(BaseSettings):
    notes_path: str = ".agent-notes.txt"
