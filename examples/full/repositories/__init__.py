"""Everything that talks to the database, and the only place that does.

The rest of the project asks for a conversation or saves a turn; it never holds a session and
never writes SQL. That is what makes a route traceable — a handler calls `save_turn`, and the
answer to "where does this request go next" is one hop rather than a search.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from repositories.models import Base, Conversation, Turn
from repositories.settings import StorageSettings

__all__ = [
    "Conversation",
    "StorageSettings",
    "Turn",
    "engine_for",
    "recent_turns",
    "save_turn",
    "session",
]

_ENGINE: Engine | None = None


def engine_for(settings: StorageSettings | None = None) -> Engine:
    """The one engine this process uses. Built on first ask, never at import time."""
    global _ENGINE
    if _ENGINE is None:
        chosen = settings or StorageSettings()
        _ENGINE = create_engine(chosen.database_url, echo=chosen.echo_sql, future=True)
        Base.metadata.create_all(_ENGINE)
    return _ENGINE


def use(engine: Engine) -> None:
    """Point this module at another database. What a test does instead of a live server."""
    global _ENGINE
    _ENGINE = engine
    Base.metadata.create_all(engine)


@contextmanager
def session() -> Iterator[Session]:
    maker = sessionmaker(bind=engine_for(), future=True)
    with maker() as open_session:
        yield open_session


def save_turn(question: str, answer: str, title: str = "") -> int:
    """Record one exchange, starting a conversation for it. Returns the turn's id."""
    with session() as open_session:
        conversation = Conversation(title=title or question[:200])
        open_session.add(conversation)
        open_session.flush()
        turn = Turn(conversation_id=conversation.id, question=question, answer=answer)
        open_session.add(turn)
        open_session.commit()
        return int(turn.id)


def recent_turns(limit: int = 20) -> list[Turn]:
    """The last exchanges, newest first."""
    with session() as open_session:
        found = open_session.execute(select(Turn).order_by(Turn.id.desc()).limit(limit)).scalars()
        return list(found)
