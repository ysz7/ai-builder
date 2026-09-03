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


@pytest.fixture(autouse=True)
def fresh(tmp_path: Path) -> None:
    """An empty index and a database of this test's own.

    SQLite in a temporary file rather than the Postgres the compose stack runs: a test that
    needed a server would fail on a laptop for a reason that is not about the code.
    """
    clear()
    repositories.use(create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True))


def call(path: str, query: str = "") -> tuple[int, Any]:
    """Drive the ASGI application directly. No server, no port, no client library."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query.encode(),
    }
    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], json.loads(sent[1]["body"])


def test_health_answers() -> None:
    status, body = call("/health")

    assert status == 200
    assert body["status"] == "ok"


def test_an_unknown_route_is_a_404() -> None:
    status, body = call("/nowhere")

    assert status == 404
    assert "no route" in body["error"]


def test_asking_reaches_the_agent(tmp_path: Path) -> None:
    path = tmp_path / "otters.txt"
    path.write_text("Otters hold hands while they sleep.", encoding="utf-8")
    index([str(path)])

    status, body = call("/ask", "q=otters")

    assert status == 200
    assert "hold hands" in body["answer"]


def test_asking_nothing_is_refused() -> None:
    _, body = call("/ask")

    assert body["error"] == "ask what?"
