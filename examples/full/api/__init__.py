"""The HTTP service.

`app` is a plain ASGI application. No framework is required here -- FastAPI, Litestar or
Starlette would each satisfy the same boundary, and one of them is what this becomes the
first time it needs middleware.

It answers three shapes of request: the JSON routes in `routes/`, the chat page, and the
chat's own event stream. Each of them is a handler somewhere else; this module is the wire.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from api.routes import ROUTES
from api.routes.chat import page, reply
from api.settings import ApiSettings

__all__ = ["ApiSettings", "app"]

Message = dict[str, Any]


async def _body(receive: Callable[[], Awaitable[Message]]) -> bytes:
    """Everything the client sent, however many chunks it arrived in."""
    chunks = b""
    while True:
        event = await receive()
        chunks += bytes(event.get("body", b""))
        if not event.get("more_body"):
            return chunks


async def _send(send: Callable[[Message], Awaitable[None]], status: int, kind: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", kind.encode())],
        }
    )


async def app(
    scope: Message,
    receive: Callable[[], Awaitable[Message]],
    send: Callable[[Message], Awaitable[None]],
) -> None:
    if scope["type"] != "http":  # websockets and lifespan are not answered here
        return

    path = scope["path"]
    method = scope.get("method", "GET").upper()

    if path == "/chat" and method == "POST":
        asked = json.loads(await _body(receive) or b"{}").get("message", "")
        await _send(send, 200, "text/event-stream")
        # Chunk by chunk, so a browser shows the reply arriving rather than appearing.
        for event in reply(str(asked)):
            await send({"type": "http.response.body", "body": event.encode(), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        return

    if path == "/chat":
        await _send(send, 200, "text/html; charset=utf-8")
        await send({"type": "http.response.body", "body": page().encode()})
        return

    route = ROUTES.get(path)
    if route is None:
        status, payload = 404, {"error": f"no route {path}"}
    else:
        status, payload = 200, route(scope.get("query_string", b"").decode())

    await _send(send, status, "application/json")
    await send({"type": "http.response.body", "body": json.dumps(payload).encode()})
