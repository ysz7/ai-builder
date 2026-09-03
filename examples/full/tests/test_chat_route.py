"""The chat route: the page it serves and the stream it answers with.

Driven through the ASGI application itself — no server, no port, no client library — because
that is what a browser will do to it, and a test of anything less would be a test of a mock.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

import repositories
from api import app
from rag import index
from rag.store import clear
from repositories import recent_turns


@pytest.fixture(autouse=True)
def fresh(tmp_path: Path) -> None:
    clear()
    repositories.use(create_engine(f"sqlite:///{tmp_path / 'chat.db'}", future=True))


def call(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, bytes, str]:
    sent: list[dict[str, Any]] = []
    payload = json.dumps(body or {}).encode()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(
        app({"type": "http", "method": method, "path": path, "query_string": b""}, receive, send)
    )
    head = sent[0]
    chunks = b"".join(part.get("body", b"") for part in sent[1:])
    kind = dict(head["headers"])[b"content-type"].decode()
    return head["status"], chunks, kind


def test_the_page_is_served_as_html() -> None:
    status, body, kind = call("GET", "/chat")

    assert status == 200
    assert kind.startswith("text/html")
    assert b"<title>chat</title>" in body


def test_the_page_needs_nothing_installed() -> None:
    """It opens in a browser with no build step and no network: no bundler, no CDN."""
    source = (Path(__file__).resolve().parents[1] / "api" / "static" / "chat.html").read_text()

    assert "http://" not in source and "https://" not in source
    assert "<script src" not in source


def test_asking_streams_the_answer_and_records_it(tmp_path: Path) -> None:
    document = tmp_path / "otters.txt"
    document.write_text("Otters hold hands while they sleep.", encoding="utf-8")
    index([str(document)])

    status, body, kind = call("POST", "/chat", {"message": "otters"})

    assert status == 200
    assert kind == "text/event-stream"
    assert b"event: done" in body
    # It arrives in pieces, which is the whole reason it is a stream.
    assert body.count(b"data:") > 1
    assert [turn.question for turn in recent_turns()] == ["otters"]


def test_an_empty_message_is_refused_without_reaching_the_agent() -> None:
    status, body, _ = call("POST", "/chat", {"message": "   "})

    assert status == 200
    assert b"event: error" in body
    assert recent_turns() == []
