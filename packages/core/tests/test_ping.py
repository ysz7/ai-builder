"""The core answers over the same wire the Rust shell uses."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time

from framestack_core.__main__ import handle_line, serve
from framestack_core.handlers import HANDLERS


def response(line: str) -> dict:
    out = handle_line(line)
    assert out is not None
    return json.loads(out)


def test_ping_answers() -> None:
    r = response('{"id": 1, "method": "ping", "params": {"echo": "hi"}}')

    assert r["id"] == 1
    assert r["ok"] is True
    assert r["result"]["pong"] is True
    assert r["result"]["echo"] == "hi"


def test_id_is_echoed_verbatim() -> None:
    """The shell matches responses by id; the core must not reinterpret it."""
    assert response('{"id": "abc-1", "method": "ping"}')["id"] == "abc-1"


def test_unknown_method_is_an_error_not_a_crash() -> None:
    r = response('{"id": 2, "method": "nope"}')

    assert r["ok"] is False
    assert r["error"]["code"] == "unknown_method"


def test_malformed_json_is_reported_without_an_id() -> None:
    r = response("{not json")

    assert r["ok"] is False
    assert r["error"]["code"] == "invalid_json"


def test_blank_lines_produce_no_response() -> None:
    assert handle_line("\n") is None


def test_serve_answers_every_request_exactly_once() -> None:
    """One line per request, and **not** one in request order.

    The core answers on a thread per request, so the order is whatever the handlers
    finish in. `id` is what matches an answer to its caller, which is why that is a
    change to this file and to nothing on the other side of the wire.
    """
    requests = [
        '{"id": 1, "method": "ping"}',
        "",  # a blank line must not produce an answer of its own
        '{"id": 2, "method": "ping"}',
        '{"id": 3, "method": "nope"}',
    ]
    stdin = io.StringIO("\n".join(requests) + "\n")
    stdout = io.StringIO()

    serve(stdin, stdout)

    lines = stdout.getvalue().strip().split("\n")
    assert sorted(json.loads(line)["id"] for line in lines) == [1, 2, 3]


def test_a_slow_handler_does_not_stop_the_core_answering(monkeypatch) -> None:
    """The reason this concurrency exists, stated as a test.

    A handler that spawns a subprocess -- classifying a chat message, probing a server,
    asking `docker compose` -- used to hold up every other request behind it, and the
    window froze around it: a palette opened during a chat turn showed no blocks until
    the turn's first subprocess had returned.
    """
    started = threading.Event()

    def slow(params: dict) -> dict:
        started.set()
        time.sleep(2)
        return {"slept": True}

    monkeypatch.setitem(HANDLERS, "test.slow", slow)

    stdout = io.StringIO()
    reader = threading.Thread(
        target=serve,
        args=(io.StringIO('{"id": 1, "method": "test.slow"}\n'), stdout),
        daemon=True,
    )
    reader.start()
    assert started.wait(5)

    began = time.monotonic()
    quick = response('{"id": 2, "method": "ping"}')
    assert quick["ok"] is True
    assert time.monotonic() - began < 1.0

    reader.join(10)


def test_two_calls_of_one_method_never_interleave(monkeypatch) -> None:
    """The half of the rule that keeps the old behaviour where it was load-bearing.

    Every long-lived thing in this core is a dict keyed by project, and "start it if it
    is not already running" read twice at once starts it twice. Same method, one at a
    time; a different method goes through beside it.
    """
    inside = 0
    most = 0

    def counted(params: dict) -> dict:
        nonlocal inside, most
        inside += 1
        most = max(most, inside)
        time.sleep(0.2)
        inside -= 1
        return {"ok": True}

    monkeypatch.setitem(HANDLERS, "test.counted", counted)

    lines = "\n".join(f'{{"id": {n}, "method": "test.counted"}}' for n in range(4)) + "\n"
    serve(io.StringIO(lines), io.StringIO())

    assert most == 1


def test_ping_over_a_real_subprocess() -> None:
    """End to end through an actual process, exactly as the sidecar is driven."""
    proc = subprocess.run(
        [sys.executable, "-m", "framestack_core"],
        input='{"id": 7, "method": "ping"}\n',
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip())["result"]["pong"] is True


def test_stdout_carries_only_the_wire() -> None:
    """Logs must go to stderr, or they corrupt the protocol stream."""
    proc = subprocess.run(
        [sys.executable, "-m", "framestack_core"],
        input='{"id": 1, "method": "ping"}\n',
        capture_output=True,
        text=True,
        timeout=60,
    )

    for line in proc.stdout.strip().split("\n"):
        json.loads(line)  # every stdout line parses as JSON
    assert "[core] ready" in proc.stderr
