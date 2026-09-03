"""A note the agent can keep between turns.

A file, because turns may be separate processes: something remembered in memory would be
remembered only for as long as one reply took.
"""

from __future__ import annotations

from pathlib import Path

from agent.notes_settings import NotesSettings


def remember(note: str) -> str:
    """Append a note, or list what is remembered when given nothing."""
    path = Path(NotesSettings().notes_path)
    if not note.strip():
        return path.read_text(encoding="utf-8").strip() if path.is_file() else "nothing yet"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(note.strip() + "\n")
    return f"noted: {note.strip()}"
