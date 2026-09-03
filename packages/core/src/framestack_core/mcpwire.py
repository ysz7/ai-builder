"""Speaking MCP to one server, far enough to be told what it offers (Phase 10).

## Why this exists at all

Until this phase nothing here asked a server anything, and a node could not say whether it
was connected — only the server knew, and finding out meant becoming an MCP client. This is
that client, and it is deliberately the smallest one that can exist: it says hello, asks for
the tool list, and hangs up.

**The tool count is the evidence.** It is the same rule the verdicts follow — a claim is
earned by something that actually happened, never by a configuration existing. `connected`
means *this server answered `tools/list` at this time*, and where it did not, the reason is
the server's own words rather than a colour. Nothing is remembered on disk: an answer about a
live process goes stale the moment the process does, and a stored one would be a claim
outliving the thing it was about.

## Two transports, because `mcp.json` has two kinds of entry

A `command` entry is a **stdio** server: a child process spoken to over its pipes, one JSON
object per line — the same wire shape this application's own core uses, which is not a
coincidence. A `url` entry is an **HTTP** server: one POST per request, answered either as
JSON or as an event stream, and carrying whatever `Authorization` header the project's `.env`
supplies.

## What it refuses

**It calls no tool, ever.** `tools/list` is a question; `tools/call` is somebody's mailbox.
Nothing in this file can invoke anything a server offers, and nothing above it can ask it to.

**It never holds a credential.** A token is read out of `.env` at the moment a request is
built and goes into a header; it is not stored here, not logged, and never put in a payload.

**It starts nothing implicitly (P11).** A probe spawns a process, so it happens because
somebody pressed something — never because a panel opened or a graph was read.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framestack_core.envfile import read_value

__all__ = ["Answer", "ask_http", "ask_stdio"]

#: The protocol version this client speaks. A server that wants another one says so in its
#: `initialize` answer, and we do not argue: this asks one question and leaves.
PROTOCOL = "2025-06-18"

#: Who is asking. Servers log it, and a server's log saying `framestack` is the truth.
CLIENT = {"name": "framestack", "version": "0.1.0"}

#: How long a whole probe may take. A server that has to install itself on first run (`npx
#: -y`) is slow once and fast afterwards, so this is generous rather than snappy -- but it is
#: bounded, because a probe that hung would hold the panel that asked for it.
SECONDS = 60

#: `${VAR}` in a header value. The **name** of a variable is what an entry may hold; the
#: value comes out of `.env` here and goes straight into a request.
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class Answer:
    """What a server said, or why it said nothing."""

    ok: bool
    detail: str
    tools: tuple[str, ...] = ()
    #: What the server calls itself, from its `initialize` answer. Its own words, unedited.
    server: str = ""


def _expand(value: str, project: Path) -> str:
    """`${VAR}` filled in from the project's `.env`.

    The one place a secret is read, and it is read into a request. An unset variable is left
    as it stands rather than replaced with an empty string: a header reading `Bearer ${X}` is
    a fault a person can see, and `Bearer ` is one they cannot.
    """
    return PLACEHOLDER.sub(
        lambda found: read_value(project, found.group(1)) or found.group(0), value
    )


def _headers(entry: dict[str, Any], project: Path) -> dict[str, str]:
    given = entry.get("headers")
    if not isinstance(given, dict):
        return {}
    return {
        str(key): _expand(str(value), project)
        for key, value in given.items()
        if isinstance(value, (str, int, float))
    }


def _request(id_: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _tools_of(result: Any) -> tuple[str, ...]:
    """The names in a `tools/list` result. A shape we do not recognise yields none.

    Reported as an empty list rather than as an error: "this server offers no tools" and
    "this answer was not what the spec describes" both mean there is nothing to show, and
    inventing a failure out of the second would put our confusion in front of a person as
    though it were the server's.
    """
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return ()
    return tuple(str(tool["name"]) for tool in tools if isinstance(tool, dict) and "name" in tool)


# -- stdio ------------------------------------------------------------------------------


def _reader(stream: Any, into: queue.Queue[str]) -> None:
    for line in iter(stream.readline, b""):
        into.put(line.decode("utf-8", "replace"))
    into.put("")


def _await(answers: queue.Queue[str], want: int, deadline: float) -> dict[str, Any] | None:
    """The response with this id, ignoring everything else on the pipe.

    A server may log, notify, or answer out of order; only the id matters. `None` is "it did
    not answer in time", which is a different claim from "it refused" and is said as one.
    """
    import time

    while time.monotonic() < deadline:
        try:
            line = answers.get(timeout=max(0.05, deadline - time.monotonic()))
        except queue.Empty:
            return None
        if line == "":
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue  # a server printing to stdout. Not ours to interpret.
        if isinstance(message, dict) and message.get("id") == want:
            return message
    return None


def ask_stdio(project: Path, entry: dict[str, Any], command: str, args: tuple[str, ...]) -> Answer:
    """Start the server, say hello, ask for its tools, and stop it again.

    The process is the server's own, run exactly as the file declares it — this adds no flag
    and edits no argument. It is killed on the way out, because a probe that left a process
    behind would be this application deciding to run somebody's server.
    """
    import time

    environment = {**os.environ}
    for key, value in (entry.get("env") or {}).items():
        if isinstance(value, (str, int, float)):
            environment[str(key)] = _expand(str(value), project)

    try:
        process = subprocess.Popen(  # noqa: S603 -- the entry's own command, unedited
            [command, *args],
            cwd=project,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
    except OSError as exc:
        return Answer(False, f"{command} could not be started: {exc}")

    answers: queue.Queue[str] = queue.Queue()
    assert process.stdout is not None and process.stdin is not None
    threading.Thread(target=_reader, args=(process.stdout, answers), daemon=True).start()
    deadline = time.monotonic() + SECONDS

    def send(message: dict[str, Any]) -> bool:
        try:
            assert process.stdin is not None
            process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            process.stdin.flush()
        except (OSError, ValueError):
            return False
        return True

    try:
        hello = _request(
            1,
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT},
        )
        if not send(hello):
            return Answer(False, f"{command} closed its input before it could be greeted")
        opened = _await(answers, 1, deadline)
        if opened is None:
            return Answer(False, f"{command} did not answer `initialize` within {SECONDS}s")
        if "error" in opened:
            return Answer(False, f"initialize was refused: {_said(opened)}")

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if not send(_request(2, "tools/list")):
            return Answer(False, f"{command} closed its input after the greeting")
        listed = _await(answers, 2, deadline)
        if listed is None:
            return Answer(False, f"{command} did not answer `tools/list` within {SECONDS}s")
        if "error" in listed:
            return Answer(False, f"tools/list was refused: {_said(listed)}")

        return Answer(True, "the server answered", _tools_of(listed.get("result")), _named(opened))
    finally:
        # Always. A probe that left the server running would be this application starting
        # somebody's program and walking away from it.
        _end(process)


def _end(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _said(message: dict[str, Any]) -> str:
    """A JSON-RPC error, in the server's own words. Never rewritten into ours."""
    error = message.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def _named(opened: dict[str, Any]) -> str:
    result = opened.get("result")
    info = result.get("serverInfo") if isinstance(result, dict) else None
    return str(info.get("name", "")) if isinstance(info, dict) else ""


# -- http -------------------------------------------------------------------------------


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[Any, dict[str, str]]:
    """One JSON-RPC POST. The answer, and the response's own headers.

    Streamable HTTP allows either a JSON body or an event stream, and a server picks. Both
    are read here, because which one arrives is not something a caller should have to know.
    """
    request = urllib.request.Request(  # noqa: S310 -- an http(s) url out of the project's file
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
    )
    with urllib.request.urlopen(request, timeout=SECONDS) as answer:  # noqa: S310
        raw = answer.read().decode("utf-8", "replace")
        kind = answer.headers.get("Content-Type", "")
        back = {key: value for key, value in answer.headers.items()}
    if "text/event-stream" in kind:
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip()), back
                except json.JSONDecodeError:
                    continue
        return None, back
    if not raw.strip():
        return None, back
    return json.loads(raw), back


def ask_http(project: Path, entry: dict[str, Any], url: str) -> Answer:
    """Say hello over HTTP, ask for the tools, and keep nothing.

    A 401 is the ordinary answer for a server nobody has authorised yet, and it is reported
    as that rather than as a failure: it is the sentence that tells a person to press
    `Connect`.
    """
    headers = _headers(entry, project)
    try:
        opened, back = _post(
            url,
            headers,
            _request(
                1,
                "initialize",
                {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT},
            ),
        )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return Answer(False, "the server refused: it has not been authorised yet")
        return Answer(False, f"the server answered {exc.code}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return Answer(False, f"the server could not be reached: {exc}")

    if not isinstance(opened, dict) or "error" in opened:
        return Answer(False, f"initialize was refused: {_said(opened or {})}")

    # A session id, where the server issued one. Sent back on the next request because the
    # spec says so; nothing here interprets it.
    session = back.get("Mcp-Session-Id") or back.get("mcp-session-id")
    if session:
        headers["Mcp-Session-Id"] = session
    try:
        _post(url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed, _ = _post(url, headers, _request(2, "tools/list"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return Answer(False, f"tools/list could not be asked: {exc}")

    if not isinstance(listed, dict) or "error" in listed:
        return Answer(False, f"tools/list was refused: {_said(listed or {})}")
    return Answer(True, "the server answered", _tools_of(listed.get("result")), _named(opened))
