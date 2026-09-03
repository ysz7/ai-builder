"""What day it is, asked of the machine rather than remembered by a model."""

from __future__ import annotations

from datetime import datetime, timezone


def today(_: str = "") -> str:
    """The current date in UTC, as `2026-09-03`."""
    return datetime.now(timezone.utc).date().isoformat()
