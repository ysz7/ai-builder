"""The models on this machine, and pulling one.

## Why this node earns extra work

Ollama is the only node in the graph that makes "no data leaves this machine" literally true.
For a European company evaluating the tool, that is the first question their legal team asks,
and it is answered by a model list a person can look at rather than by a paragraph on a
website. So this dependency gets panel content the others do not: what is pulled, how large
it is, and a way to pull another.

## What it is, and what it is not

**Not a catalogue.** Nothing here ships a list of models, ranks them, or knows what any of
them is for. The list is whatever `GET /api/tags` says is on *this* machine, asked at the
moment somebody looks; a registry of names we maintained would be stale the week after it
shipped and would be the "catalogue of databases or MCP servers" the plan puts out of scope.

**Not a client library.** Ollama is an HTTP endpoint and the standard library speaks HTTP.
Adding a vendor SDK to the core to call two endpoints would be a connector written and
therefore a connector maintained.

## Pulling follows the shape everything long-running follows

`POST /api/pull` answers with a stream of JSON lines and can take many minutes. So it runs in
a thread that appends to a file under `.framestack/`, and the caller **polls with an offset it
keeps** -- nothing is pushed, and a record on disk survives a crash. It is the same contract
Observe, `Run` and `Deploy` have, for the same reasons, and it is the only reason a pull can be
watched from a panel that was opened after it started.

**Nothing starts implicitly.** No model is ever pulled because a panel was opened.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["Model", "OllamaResult", "pull_model", "read_models", "read_pull", "stop_pull"]

#: Where the daemon listens, by its own default. The one address this codebase knows.
BASE = "http://127.0.0.1:11434"

#: Where a pull's output goes, so a panel opened after it started can still watch it.
LOG_PATH = Path(".framestack") / "ollama.log"

#: How long a read of the model list may take. Local, so a slow answer is a broken one.
SECONDS = 5


@dataclass
class _Pull:
    """One pull in flight. Held in memory; its output is on disk."""

    model: str
    thread: threading.Thread
    stop: threading.Event = field(default_factory=threading.Event)


#: Keyed by project, because two windows on two projects are two pulls.
_PULLS: dict[str, _Pull] = {}


@dataclass(frozen=True)
class Model:
    """One model this machine has pulled."""

    name: str
    #: As the daemon reports it, in bytes. Formatting is the interface's business.
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size}


@dataclass(frozen=True)
class OllamaResult:
    """The answer to every verb here. A refusal is a result, never a protocol fault."""

    ok: bool
    detail: str
    #: What is on this machine. Empty where the daemon did not answer.
    models: tuple[Model, ...] = ()
    #: Which model a pull is fetching, or `""` when none is.
    pulling: str = ""
    #: Whether a pull is still going. The caller polls until this is false.
    running: bool = False
    #: New output since the offset the caller sent.
    output: str = ""
    #: Where to resume from next time. The caller keeps it; nothing is pushed.
    offset: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "models": [model.as_dict() for model in self.models],
            "pulling": self.pulling,
            "running": self.running,
            "output": self.output,
            "offset": self.offset,
        }


def _get(path: str, timeout: int = SECONDS) -> tuple[dict[str, Any] | None, str]:
    """One GET against the local daemon. `(body, "")` or `(None, why not)`."""
    request = urllib.request.Request(f"{BASE}{path}", method="GET")  # noqa: S310 -- fixed http
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
            body = json.loads(answer.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"ollama did not answer at {BASE}: {exc}"
    except (ValueError, json.JSONDecodeError):
        return None, f"ollama answered {path} with something that is not JSON"
    return (body if isinstance(body, dict) else {}), ""


def read_models(project: Path | str) -> OllamaResult:
    """What is pulled on this machine. A read: it fetches nothing and starts nothing.

    The project is taken so a pull in flight can be reported beside the list -- the list
    itself is a fact about the machine, not about the project, and it is the same list every
    window would see.
    """
    root = Path(project).expanduser()
    body, refused = _get("/api/tags")
    if body is None:
        return OllamaResult(False, refused, (), *_pull_state(root))

    raw = body.get("models")
    found: list[Model] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            size = item.get("size")
            if isinstance(name, str) and name:
                found.append(Model(name=name, size=size if isinstance(size, int) else 0))
    # Sorted, so two reads of an unchanged machine answer identically. The daemon's own
    # order is a detail of how it stores them, not a fact anybody chose.
    found.sort(key=lambda model: model.name)
    return OllamaResult(True, f"{len(found)} model(s)", tuple(found), *_pull_state(root))


def _pull_state(root: Path) -> tuple[str, bool]:
    pull = _PULLS.get(str(root))
    if pull is None:
        return "", False
    return pull.model, pull.thread.is_alive()


def _log(root: Path) -> Path:
    return root / LOG_PATH


def _read_log(root: Path, offset: int) -> tuple[str, int]:
    """Everything written since `offset`. The caller keeps the offset; nothing is pushed."""
    log = _log(root)
    where = max(offset, 0)
    if not log.is_file():
        return "", where
    try:
        with log.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(where)
            text = handle.read()
            return text, handle.tell()
    except OSError:
        return "", where


def _stream(root: Path, model: str, stop: threading.Event) -> None:
    """`POST /api/pull`, one JSON line at a time, appended to the log as it arrives.

    Progress is turned into a sentence here rather than in the interface, because what the
    daemon sends is a status and two byte counts and the useful reading of it is one line. A
    caller that had to do arithmetic on a stream would be a caller reimplementing this.
    """
    log = _log(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"model": model, "stream": True}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 -- a fixed http URL on this machine
        f"{BASE}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def say(line: str) -> None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    # The first line is already on disk: `pull_model` wrote it before this thread existed,
    # so a caller that polls immediately sees the pull rather than an empty log it would
    # have to read as nothing happening.
    seen = ""
    try:
        with urllib.request.urlopen(request) as answer:  # noqa: S310
            for raw in answer:
                if stop.is_set():
                    say("stopped")
                    return
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(body, dict):
                    continue
                if isinstance(body.get("error"), str):
                    say(f"error: {body['error']}")
                    return
                status = body.get("status")
                if not isinstance(status, str):
                    continue
                done, total = body.get("completed"), body.get("total")
                if isinstance(done, int) and isinstance(total, int) and total > 0:
                    share = int(done * 100 / total)
                    line = f"{status} {share}%"
                else:
                    line = status
                # One line per change, not one per packet: the daemon repeats itself many
                # times a second, and a log that kept every repetition would be unreadable.
                if line != seen:
                    say(line)
                    seen = line
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        say(f"error: {exc}")
        return
    say("done")


def pull_model(project: Path | str, model: str) -> OllamaResult:
    """Start pulling one model. **Never implicit**: only a press gets here.

    A refusal is a result. Two pulls at once in one project is refused rather than queued --
    a queue would be a thing to manage, and the honest answer is that one is already running.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return OllamaResult(False, f"there is no project at {root}")
    if not model.strip():
        return OllamaResult(False, "no model was named")

    running = _PULLS.get(str(root))
    if running is not None and running.thread.is_alive():
        return OllamaResult(
            False,
            f"{running.model} is already being pulled here",
            pulling=running.model,
            running=True,
        )

    # A fresh log per pull, with the first line written **here** rather than in the thread.
    # Keeping the last pull's log would make a panel opened during the second show the end of
    # the first, which reads as progress that is not happening; and writing the first line
    # after the thread starts would leave a caller that polled at once with an empty answer.
    log = _log(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"pulling {model.strip()}\n", encoding="utf-8")

    stop = threading.Event()
    thread = threading.Thread(
        target=_stream, args=(root, model.strip(), stop), name=f"ollama-pull-{model}", daemon=True
    )
    _PULLS[str(root)] = _Pull(model=model.strip(), thread=thread, stop=stop)
    thread.start()
    return OllamaResult(True, f"pulling {model.strip()}", pulling=model.strip(), running=True)


def read_pull(project: Path | str, offset: int = 0) -> OllamaResult:
    """What the pull has printed since `offset`, and whether it is still going."""
    root = Path(project).expanduser()
    output, where = _read_log(root, offset)
    model, running = _pull_state(root)
    return OllamaResult(
        ok=True,
        detail=f"{model} is being pulled" if running else "nothing is being pulled",
        pulling=model,
        running=running,
        output=output,
        offset=where,
    )


def stop_pull(project: Path | str) -> OllamaResult:
    """Ask the pull to stop. It stops at the next line the daemon sends.

    The daemon keeps whatever it has already written to its own store; this ends *watching*
    rather than undoing, and the log says `stopped` so nobody reads the last percentage as
    where it finished.
    """
    root = Path(project).expanduser()
    pull = _PULLS.get(str(root))
    if pull is None or not pull.thread.is_alive():
        return OllamaResult(True, "nothing is being pulled")
    pull.stop.set()
    return OllamaResult(True, f"{pull.model} was asked to stop", pulling=pull.model)
