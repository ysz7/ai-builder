"""What a run cost: the tokens a model was asked for, and the dollars they come to (Phase 11).

## Tokens are measured; dollars are arithmetic done later

The ledger stores **what happened** — a model name, an input count, an output count, a time —
and never a price. The dollars are computed on read from a table in this file, so a table
corrected next week corrects last week's history too. A stored total would be a number nobody
could re-derive, and the first time a price changed it would be quietly wrong.

**A model that is not in the table shows tokens and no dollar figure.** Never a guess: a cost
invented for an unknown model is the same defect as a green node nobody ran a test for, in
the currency a person actually cares about.

## Nothing is added to the user's project

The measurement is a wrapper installed **in the child process a `Run` already spawns**,
written into the run's own driver — which is a file this toolchain writes into
`.framestack/` and deletes on the next run. There is no import in the project, no decorator,
no settings key, and no dependency: delete Framestack and the project's code is byte for byte
what it was (I-6). The wrapper patches a provider's client class *if that client is already
importable*, and does nothing at all otherwise.

## Where it is stored, and why that is allowed

`.framestack/usage.db`, gitignored, SQLite from the standard library. This is Framestack's
own record of runs it started — not project data, and not a second source of truth about the
code — so it does not contradict "code is the only source of truth": **delete it and you lose
history, not behaviour.** It is the same category as the layout and the observation.

## What it does not do

It does not instrument the chat agent: that is this application's own conversation, billed to
whoever is signed in, and putting it in a project's ledger would attribute Framestack's spend
to somebody's app. It does not read Langfuse or fall back to it — where a project has
Langfuse credentials the panel offers a link out, and that is the whole of the integration.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framestack_core.envfile import names as env_names
from framestack_core.envfile import read_value

__all__ = [
    "LEDGER_PATH",
    "METER",
    "PRICES",
    "Call",
    "Usage",
    "price_of",
    "read_usage",
    "record_ledger",
]

#: Framestack's own record of runs it started. Delete it and history is lost, nothing else.
LEDGER_PATH = Path(".framestack") / "usage.db"

#: What a model costs, in dollars per million tokens: `(input, output)`.
#:
#: **A table, updated with releases, and deliberately short.** Only models whose published
#: price this build actually knows are in it; everything else is absent, and an absent model
#: shows its tokens with no dollar figure beside them. Guessing a price would be worse than
#: saying nothing, because a number in a panel is read as a fact.
#:
#: Anthropic's first-party rates. Other providers are not here for the same reason a
#: catalogue of databases is not: a table this file cannot keep true is one that will lie.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

#: The variables that mean this project sends traces to Langfuse. Read for **names only**.
LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
#: Where its UI is. A host is not a secret, and the panel needs somewhere to link to.
LANGFUSE_HOST = "LANGFUSE_HOST"


@dataclass(frozen=True)
class Call:
    """One request to a model, as the provider's own answer reported it."""

    at: str
    model: str
    input: int
    output: int
    #: Dollars, or `None` where this build does not know what the model costs. **Never a
    #: guess** — the tokens are shown either way, and the absence says which it is.
    cost: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "model": self.model,
            "input": self.input,
            "output": self.output,
            "cost": self.cost,
        }


@dataclass(frozen=True)
class Usage:
    """What one node's last run cost, step by step."""

    ok: bool
    detail: str
    node: str = ""
    calls: tuple[Call, ...] = ()
    tokens: int = 0
    #: The sum of the steps this build could price. `None` where it could price none of them
    #: — a total of `$0.00` for a run nobody has a price for would be a false statement.
    cost: float | None = None
    #: The models seen with no price. Named, so the panel can say why a figure is missing.
    unpriced: tuple[str, ...] = ()
    #: Where this project's traces go, if it says it sends any. A link, never a fetch: the
    #: plan asks for Langfuse to be linked out to and never read from.
    langfuse: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "calls": [call.as_dict() for call in self.calls],
            "tokens": self.tokens,
            "cost": self.cost,
            "unpriced": list(self.unpriced),
            "langfuse": self.langfuse,
        }


# -- what the child is told ----------------------------------------------------------------

#: The meter, as text, appended to the run driver.
#:
#: It patches a provider client **only if the project already imports one**, and it writes one
#: JSON line per call to the path in `FRAMESTACK_USAGE`. Nothing here raises into the
#: project's own code: a builder that broke somebody's agent to count its tokens would have
#: earned every complaint it got, so every hook is wrapped and every failure is silence.
#:
#: Streaming calls are not counted, and that is stated rather than approximated: the usage
#: arrives in the final event of a stream this wrapper does not hold, and inventing a number
#: from what it *can* see would be the guess the price table refuses to make.
METER = '''

def _framestack_meter():
    """Written by Framestack for one Run. Not part of this project, and not imported by it."""
    import datetime
    import json
    import os

    where = os.environ.get("FRAMESTACK_USAGE", "")
    if not where:
        return

    def note(model, given):
        try:
            entry = {
                "at": datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
                "model": str(model or ""),
                "input": int(
                    getattr(given, "input_tokens", None)
                    or getattr(given, "prompt_tokens", None)
                    or 0
                ),
                "output": int(
                    getattr(given, "output_tokens", None)
                    or getattr(given, "completion_tokens", None)
                    or 0
                ),
            }
            with open(where, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\\n")
        except Exception:
            # Counting must never be the reason somebody's run failed.
            pass

    def wrap(owner, name):
        original = getattr(owner, name, None)
        if original is None:
            return
        def counted(*args, **keywords):
            answer = original(*args, **keywords)
            usage = getattr(answer, "usage", None)
            if usage is not None:
                note(getattr(answer, "model", ""), usage)
            return answer
        try:
            setattr(owner, name, counted)
        except Exception:
            pass

    try:
        import anthropic.resources.messages as _messages
        wrap(_messages.Messages, "create")
    except Exception:
        pass
    try:
        import openai.resources.chat.completions as _completions
        wrap(_completions.Completions, "create")
    except Exception:
        pass


_framestack_meter()
'''


# -- the ledger ----------------------------------------------------------------------------


def _open(root: Path) -> sqlite3.Connection:
    path = root / LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        # No price column, and the absence is the design: dollars are computed on read, so a
        # corrected table corrects history rather than leaving a stored number behind.
        "CREATE TABLE IF NOT EXISTS calls ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  node TEXT NOT NULL,"
        "  run TEXT NOT NULL,"
        "  at TEXT NOT NULL,"
        "  model TEXT NOT NULL,"
        "  input INTEGER NOT NULL,"
        "  output INTEGER NOT NULL"
        ")"
    )
    return connection


def record_ledger(project: Path | str, node: str, run: str, lines: str) -> int:
    """Take what the child wrote and put it in the ledger. Returns how many calls it was.

    Called by the watcher when a run ends, so the ledger exists whether or not a panel is
    open — the same reason the outcome is written there rather than in `read_run`.
    """
    root = Path(project).resolve()
    entries: list[tuple[str, str, str, str, int, int]] = []
    for line in lines.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            held = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(held, dict):
            continue
        entries.append(
            (
                node,
                run,
                str(held.get("at") or run),
                str(held.get("model") or ""),
                int(held.get("input") or 0),
                int(held.get("output") or 0),
            )
        )
    if not entries:
        return 0

    try:
        with _open(root) as connection:
            connection.executemany(
                "INSERT INTO calls (node, run, at, model, input, output) VALUES (?, ?, ?, ?, ?, ?)",
                entries,
            )
    except sqlite3.Error:
        # A ledger that cannot be written loses history and nothing else. It must never be
        # the reason a run reports failure.
        return 0
    return len(entries)


def price_of(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Dollars, or `None` where this build does not know what the model costs.

    Matched on the exact id, and then on the longest prefix in the table — a dated snapshot
    (`claude-opus-5-20260101`) is the same model at the same price, and refusing to price it
    would be pedantry rather than honesty. A name that matches nothing is `None`.
    """
    if model in PRICES:
        rate = PRICES[model]
    else:
        found = [name for name in PRICES if model.startswith(name)]
        if not found:
            return None
        rate = PRICES[max(found, key=len)]
    return (input_tokens * rate[0] + output_tokens * rate[1]) / 1_000_000


def _langfuse(root: Path) -> str:
    """Where this project's traces go, if it says it sends any.

    **Read from `.env` by name, and never fetched.** The plan is explicit that Langfuse is
    linked out to and never read from — a builder that pulled traces would be taking on a
    second source of truth about a run it already measured itself.
    """
    held = env_names(root)
    if not all(key in held for key in LANGFUSE_KEYS):
        return ""
    # A host is not a secret. It is the one value here that may be shown, because it is an
    # address a person is about to be sent to.
    return read_value(root, LANGFUSE_HOST) or "https://cloud.langfuse.com"


def read_usage(project: Path | str, node: str) -> Usage:
    """What this node's last run cost. A read: it starts nothing and calls no provider."""
    root = Path(project).resolve()
    if not root.is_dir():
        return Usage(False, f"there is no project at {root}", node)
    if not (root / LEDGER_PATH).is_file():
        # A project nobody has run has no history, which is an answer rather than a failure.
        return Usage(True, "nothing has been measured here yet", node, langfuse=_langfuse(root))

    try:
        with _open(root) as connection:
            last = connection.execute(
                "SELECT run FROM calls WHERE node = ? ORDER BY id DESC LIMIT 1", (node,)
            ).fetchone()
            if last is None:
                return Usage(
                    True, "this node has not been measured yet", node, langfuse=_langfuse(root)
                )
            rows = connection.execute(
                "SELECT at, model, input, output FROM calls WHERE node = ? AND run = ? ORDER BY id",
                (node, last[0]),
            ).fetchall()
    except sqlite3.Error as exc:
        return Usage(False, f"the ledger could not be read: {exc}", node)

    calls = tuple(
        Call(
            at=str(at),
            model=str(model),
            input=int(given),
            output=int(back),
            cost=price_of(str(model), int(given), int(back)),
        )
        for at, model, given, back in rows
    )
    priced = [call.cost for call in calls if call.cost is not None]
    unpriced = tuple(dict.fromkeys(call.model for call in calls if call.cost is None))

    return Usage(
        True,
        f"{len(calls)} step(s)",
        node,
        calls=calls,
        tokens=sum(call.input + call.output for call in calls),
        # `None` rather than zero where nothing could be priced: a total of $0.00 for a run
        # nobody has a price for would be a false statement rather than a missing one.
        cost=sum(priced) if priced else None,
        unpriced=unpriced,
        langfuse=_langfuse(root),
    )
