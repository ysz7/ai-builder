"""The chat: a page to type into, and a route that streams the answer back.

`POST /chat` sends the agent's reply as server-sent events, so a browser can show it
arriving; `GET /chat` serves the page that does the typing. Both are ordinary parts of this
service — deploy the project and a colleague opens the same page at the same address.

The route is transport and nothing else. It calls `run`, it records the exchange through the
repository, and every line of thinking about either lives in the package that owns it.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent import run
from repositories import save_turn

#: The page, beside the service that serves it. One file, no build step, no bundler.
PAGE = Path(__file__).resolve().parents[1] / "static" / "chat.html"


def page() -> str:
    """The chat page's HTML, read from disk so editing it needs no restart."""
    return PAGE.read_text(encoding="utf-8")


def reply(message: str) -> list[str]:
    """The agent's answer, as the event-stream lines a browser reads.

    A list rather than a generator: the whole reply is one call to `run`, and pretending
    otherwise by yielding it in pieces would be a stream that only looks like one.
    """
    if not message.strip():
        return [f"event: error\ndata: {json.dumps({'error': 'say something'})}\n\n"]

    answer = run(message)
    save_turn(message, answer)
    return [f"data: {json.dumps({'delta': word + ' '})}\n\n" for word in answer.split(" ")] + [
        f"event: done\ndata: {json.dumps({'answer': answer})}\n\n"
    ]
