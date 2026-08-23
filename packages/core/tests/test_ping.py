"""The core answers over the same wire the Rust shell uses."""

from __future__ import annotations

import io
import json
import subprocess
import sys

from aibuilder_core.__main__ import handle_line, serve


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


def test_serve_answers_in_order_one_line_per_request() -> None:
    requests = [
        '{"id": 1, "method": "ping"}',
        "",  # a blank line must not shift the answers that follow it
        '{"id": 2, "method": "ping"}',
        '{"id": 3, "method": "nope"}',
    ]
    stdin = io.StringIO("\n".join(requests) + "\n")
    stdout = io.StringIO()

    serve(stdin, stdout)

    lines = stdout.getvalue().strip().split("\n")
    assert [json.loads(line)["id"] for line in lines] == [1, 2, 3]


def test_ping_over_a_real_subprocess() -> None:
    """End to end through an actual process, exactly as the sidecar is driven."""
    proc = subprocess.run(
        [sys.executable, "-m", "aibuilder_core"],
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
        [sys.executable, "-m", "aibuilder_core"],
        input='{"id": 1, "method": "ping"}\n',
        capture_output=True,
        text=True,
        timeout=60,
    )

    for line in proc.stdout.strip().split("\n"):
        json.loads(line)  # every stdout line parses as JSON
    assert "[core] ready" in proc.stderr
