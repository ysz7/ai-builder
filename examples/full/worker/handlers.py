"""The work this project does out of band.

A handler takes a payload and returns a result. It is an ordinary function: what puts it
on a queue is the deployment's business, and a decorator here would make the function
something a test can no longer call directly.
"""

from __future__ import annotations

from typing import Any

from rag import index
from worker.settings import WorkerSettings


def reindex(payload: dict[str, Any]) -> dict[str, Any]:
    """Put a batch of documents into the index."""
    paths = [str(one) for one in payload.get("paths", [])][: WorkerSettings().batch_size]
    index(paths)
    return {"indexed": len(paths)}


def echo(payload: dict[str, Any]) -> dict[str, Any]:
    """The smallest handler there is. It exists so the table has more than one entry."""
    return dict(payload)
