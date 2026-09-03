"""What the agent can do besides talk.

One file per tool, which is the shape the builder reads: a module in here that defines a
public function is a node of its own, and the edge to `rag` belongs to the tool that writes
the import rather than to the whole agent. Nothing in this file is Framestack's -- it is an
ordinary package `__init__` re-exporting what the agent imports.
"""

from __future__ import annotations

from agent.tools.look_up import look_up

__all__ = ["look_up"]
