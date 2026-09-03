"""The HTTP service: a plain ASGI application over the handlers in `routes/`.

No framework is required at this boundary. FastAPI or Litestar would each satisfy it, and one
of them is what this becomes the first time it needs middleware.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from api.routes import ROUTES
from api.settings import ApiSettings

__all__ = ["ApiSettings", "app"]

Message = dict[str, Any]


async def app(
    scope: Message,
    receive: Callable[[], Awaitable[Message]],
    send: Callable[[Message], Awaitable[None]],
) -> None:
    if scope["type"] != "http":
        return

    route = ROUTES.get(scope["path"])
    if route is None:
        status, payload = 404, {"error": f"no route {scope['path']}"}
    else:
        status, payload = 200, route(scope.get("query_string", b"").decode())

    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(payload).encode()})
