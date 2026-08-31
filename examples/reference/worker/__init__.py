"""Background work.

`HANDLERS` is the whole boundary: a name, and the function that answers to it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from worker.handlers import echo, reindex
from worker.settings import WorkerSettings

__all__ = ["HANDLERS", "WorkerSettings"]

HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "reindex": reindex,
    "echo": echo,
}
