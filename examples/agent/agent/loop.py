"""How a message becomes a reply: read the message, call the tools it names, answer.

Deliberately a loop and not a framework. What the convention asks of this package is one
export; whether the inside is LangGraph, Pydantic AI or thirty lines is nobody's business but
this package's, and thirty lines is what an example should be.
"""

from __future__ import annotations

import re

from agent.settings import AgentSettings
from agent.tools import TOOLS

#: `calculate: 2 + 2` — the smallest way to name a tool that a person can also type by hand.
CALL = re.compile(r"(?P<tool>[a-z_]+)\s*:\s*(?P<argument>.*)", re.IGNORECASE)


def steps(message: str, settings: AgentSettings) -> list[str]:
    """The tool results this message asks for, in the order it asks for them."""
    done: list[str] = []
    for line in message.splitlines():
        found = CALL.match(line.strip())
        if not found:
            continue
        tool = TOOLS.get(found.group("tool").lower())
        if tool is None:
            done.append(f"there is no tool called {found.group('tool')!r}")
        else:
            done.append(tool(found.group("argument").strip()))
        if len(done) >= settings.steps:
            break
    return done


def answer(message: str, settings: AgentSettings) -> str:
    """The reply. With `offline` on, it is the tool results and nothing else.

    The line where a model belongs is marked, and it is one line: everything around it —
    which tools ran, in what order, with what — is this file's business and stays testable
    without a network or a key.
    """
    done = steps(message, settings)
    if not done:
        return (
            "Name a tool to use one: `calculate: 2 + 2`, `today:`, `remember: buy milk`. "
            f"I have {', '.join(sorted(TOOLS))}."
        )
    if settings.offline:
        return " ".join(done)
    # A model would be called here, given the message and the results above. Nothing in this
    # example does, because an example that needed a key would be one nobody could run.
    return " ".join(done)
