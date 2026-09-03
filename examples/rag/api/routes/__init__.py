"""What the service answers.

One handler is a call and a return: upload writes a file and hands it to `index`, ask hands a
query to `search`. Everything either of them knows about retrieval is in `rag/`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from api.settings import ApiSettings
from rag import index, search


def health(_: str) -> dict[str, Any]:
    return {"status": "ok"}


def upload(query: str) -> dict[str, Any]:
    """Write a document and index it. `?name=notes.txt&text=...`."""
    values = parse_qs(query)
    name = values.get("name", [""])[0]
    text = values.get("text", [""])[0]
    if not name or not text:
        return {"error": "a name and some text, please"}

    where = Path(ApiSettings().upload_dir)
    where.mkdir(parents=True, exist_ok=True)
    document = where / name
    document.write_text(text, encoding="utf-8")
    index([str(document)])
    return {"indexed": str(document)}


def ask(query: str) -> dict[str, Any]:
    """The passages that answer `?q=...`, most alike first."""
    values = parse_qs(query)
    question = values.get("q", [""])[0]
    if not question:
        return {"error": "ask what?"}
    found = search(question)
    return {
        "question": question,
        "passages": [{"source": one.source, "text": one.text} for one in found],
    }


ROUTES: dict[str, Callable[[str], dict[str, Any]]] = {
    "/health": health,
    "/upload": upload,
    "/ask": ask,
}
