"""Knob metadata carried inside `typing.Annotated`.

`Param` is a frozen record that rides on a type annotation. Runtime never reads it;
the parser does, and the writer uses it to find where a new value goes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Param"]


@dataclass(frozen=True)
class Param:
    """Declare a field as a user-tunable knob.

    Usage::

        chunk_size: Annotated[int, Param(min=128, max=1024, widget="slider")] = 512

    The value lives in code as an ordinary field with a literal default; that
    default is the single unambiguous target the graph writes back to.
    """

    widget: str | None = None
    label: str | None = None
    help: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[Any, ...] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        widget: str | None = None,
        label: str | None = None,
        help: str | None = None,
        min: float | None = None,
        max: float | None = None,
        step: float | None = None,
        choices: Iterable[Any] | None = None,
        **extra: Any,
    ) -> None:
        object.__setattr__(self, "widget", widget)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "help", help)
        object.__setattr__(self, "min", min)
        object.__setattr__(self, "max", max)
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "choices", None if choices is None else tuple(choices))
        object.__setattr__(self, "extra", extra)
