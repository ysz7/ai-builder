"""The tools this agent can call.

One file per tool, and this module only gathers them: each file is a node in the builder, so
a module holding several would be one box where there should be several — and a person could
not see what the agent can do.
"""

from __future__ import annotations

from collections.abc import Callable

from agent.tools.arithmetic import calculate
from agent.tools.clock import today
from agent.tools.notes import remember

TOOLS: dict[str, Callable[[str], str]] = {
    "calculate": calculate,
    "today": today,
    "remember": remember,
}

__all__ = ["TOOLS", "calculate", "remember", "today"]
