"""What the service answers, and with what.

A route is a plain function from a query string to a JSON-serialisable object. Handing it
an ASGI framework is the next module's job; keeping the two apart is what makes these
testable without a client.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from agent import run
from api.settings import ApiSettings


def health(_: str) -> dict[str, Any]:
    return {"status": "ok", "service": ApiSettings().greeting}


def ask(query: str) -> dict[str, Any]:
    """Put a question to the agent and hand back what it said."""
    values = parse_qs(query)
    message = values.get("q", [""])[0]
    if not message:
        return {"error": "ask what?"}
    return {"question": message, "answer": run(message)}


ROUTES: dict[str, Callable[[str], dict[str, Any]]] = {
    "/health": health,
    "/ask": ask,
}
