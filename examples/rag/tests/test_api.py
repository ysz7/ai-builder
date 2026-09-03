"""The service, driven through the ASGI application itself: no server, no port, no client."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from api import app
from rag import RagSettings
from rag.store import clear


@pytest.fixture(autouse=True)
def somewhere_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "index.json"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    clear(RagSettings())


def call(path: str, **query: str) -> tuple[int, Any]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": urlencode(query).encode(),
    }
    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], json.loads(sent[1]["body"])


def test_health_answers() -> None:
    assert call("/health") == (200, {"status": "ok"})


def test_an_upload_is_indexed_and_then_findable() -> None:
    status, body = call("/upload", name="otters.txt", text="Otters hold hands.")
    assert status == 200
    assert body["indexed"].endswith("otters.txt")

    _, answer = call("/ask", q="otters")

    assert [one["text"] for one in answer["passages"]] == ["Otters hold hands."]


def test_an_upload_needs_both_halves() -> None:
    _, body = call("/upload", name="empty.txt")

    assert "error" in body


def test_asking_nothing_is_refused() -> None:
    _, body = call("/ask")

    assert body["error"] == "ask what?"


def test_an_unknown_route_is_a_404() -> None:
    status, _ = call("/nowhere")

    assert status == 404
