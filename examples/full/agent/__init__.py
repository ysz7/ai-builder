"""The agent this project answers questions with.

`run` takes a message and returns a reply. What it is built on is nobody's business but
this package's -- the boundary is the export.
"""

from __future__ import annotations

from agent.settings import AgentSettings
from agent.tools import look_up

__all__ = ["AgentSettings", "run"]


def run(message: str, **kw: object) -> str:
    """Answer `message`, using the project's documents where they help.

    There is no model call here, which is why this is testable without a network and
    without a key. Where a model belongs is between the passages and the reply, and it is
    the one line that would change.
    """
    settings = AgentSettings()
    passages = kw.get("passages")
    if isinstance(passages, int):
        settings = settings.model_copy(update={"passages": passages})

    found = look_up(message, settings.passages)
    if not found:
        return f"I have nothing on file about {message!r}."

    body = " ".join(piece.strip() for piece in found)
    if not settings.cite_sources:
        return body
    return f"{body} ({len(found)} passage(s) from the index.)"
