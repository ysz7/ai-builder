"""What the service answers, and with what.

A route is a plain function from a query string to a JSON-serialisable object. Handing it
an ASGI framework is the next module's job; keeping the two apart is what makes these
testable without a client.

One module per resource: `chat.py` is the conversation, and this one holds the two routes
that belong to the service itself. A handler here is a call and a return — the work is in
the package that owns it, which is what makes a request traceable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from agent import run
from api.settings import ApiSettings
from repositories import recent_turns, save_turn


def health(_: str) -> dict[str, Any]:
    return {"status": "ok", "service": ApiSettings().greeting}


def ask(query: str) -> dict[str, Any]:
    """Put a question to the agent, record the exchange, and hand back what it said."""
    values = parse_qs(query)
    message = values.get("q", [""])[0]
    if not message:
        return {"error": "ask what?"}
    answer = run(message)
    save_turn(message, answer)
    return {"question": message, "answer": answer}


def history(query: str) -> dict[str, Any]:
    """The exchanges already recorded, newest first."""
    values = parse_qs(query)
    limit = int(values.get("limit", [str(ApiSettings().page_size)])[0])
    return {
        "turns": [
            {"id": turn.id, "question": turn.question, "answer": turn.answer}
            for turn in recent_turns(limit)
        ]
    }


ROUTES: dict[str, Callable[[str], dict[str, Any]]] = {
    "/health": health,
    "/ask": ask,
    "/history": history,
}
