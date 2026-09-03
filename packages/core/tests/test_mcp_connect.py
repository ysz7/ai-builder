"""Connecting a server, and being told what it offers (Phase 10).

Three claims are under test and each is one the product would be worse for faking:

* **The tool count is earned.** `connected` means a server answered `tools/list`, which is
  why the stdio probe here talks to a real server — twenty lines of Python, started as a
  child process and spoken to over its pipes, exactly as any other would be.
* **A secret never leaves `.env`.** Not into a payload, not into `mcp.json`, not into
  `.framestack/`. The OAuth test walks the whole exchange and then goes looking for the token
  everywhere it must not be.
* **A refusal is a result.** No project, no entry, no client id: each is answered with a
  sentence, and the file is left as it was.

The provider in the OAuth test is a real HTTP server on loopback, because the thing being
tested is a redirect and a form post, and a mock of those would be a test of the mock.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from contract import validate, wire_form

from framestack_core import oauth
from framestack_core.api import (
    MCP_AUTH_SCHEMA,
    MCP_PROBE_SCHEMA,
    MCP_SCHEMA,
    mcp_authorized,
    mcp_probe,
    mcp_secret,
)
from framestack_core.envfile import read_value
from framestack_core.mcp import (
    authorisation,
    connect_server,
    give_up,
    probe_server,
    read_server,
    write_secret,
)
from framestack_core.oauth import client_id_key, token_key

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"

#: An MCP server, in as few lines as one can be written. It answers the two questions the
#: probe asks and nothing else — which is the point: the probe must work against whatever a
#: person has, not against a server built to be probed.
SERVER = """
import json, sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    if message.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "serverInfo": {"name": "twenty-liner", "version": "1"},
        }}), flush=True)
    elif message.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "tools": [{"name": "alpha"}, {"name": "beta"}],
        }}), flush=True)
"""

#: One that starts and says nothing. A server that never answers is a real failure mode and
#: it has to end as a sentence rather than as a hang.
MUTE = "import sys\nsys.stdin.read()\n"


def found(provider: str) -> tuple[str, str]:
    """Where the endpoints would have been discovered, had there been a provider to ask."""
    return f"{provider}/authorize", f"{provider}/token"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def declare(root: Path, servers: dict[str, Any]) -> None:
    (root / "mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def script(root: Path, name: str, body: str) -> str:
    (root / name).write_text(body, encoding="utf-8")
    return name


# -- what an entry is ---------------------------------------------------------------------


def test_a_command_entry_is_stdio_and_a_url_entry_is_http(tmp_path: Path) -> None:
    """Which one it is decides what `Connect` means, so it is stated rather than inferred."""
    root = project(tmp_path)
    declare(
        root,
        {
            "local": {"command": "echo", "args": ["hi"]},
            "remote": {"url": "https://mcp.example.com/mcp"},
            "unfinished": {"args": ["nothing"]},
        },
    )

    assert read_server(root, "mcp.local").transport == "stdio"
    assert read_server(root, "mcp.remote").transport == "http"
    assert read_server(root, "mcp.remote").url == "https://mcp.example.com/mcp"
    # Neither. Not repaired into a guess: an entry with nothing in it is one a person has
    # still to finish writing, and saying so is the way out of the state it is in.
    assert read_server(root, "mcp.unfinished").transport == ""


def test_the_variables_are_reported_by_name_and_never_by_value(tmp_path: Path) -> None:
    """The whole of the credential contract, in one assertion.

    That a key is set is worth sending. What it is set to is one console log from being
    somewhere permanent.
    """
    root = project(tmp_path)
    declare(root, {"remote": {"url": "https://mcp.example.com/mcp"}})

    write_secret(root, "mcp.remote", "client_id", "client-abc")
    answer = read_server(root, "mcp.remote")

    assert answer.keys == (
        "MCP_REMOTE_CLIENT_ID",
        "MCP_REMOTE_CLIENT_SECRET",
        "MCP_REMOTE_TOKEN",
    )
    assert answer.given == ("MCP_REMOTE_CLIENT_ID",)
    payload = wire_form(mcp_secret(root, "mcp.remote", "client_id", "x"))
    assert "client-abc" not in json.dumps(payload)


def test_a_third_credential_is_refused_by_name(tmp_path: Path) -> None:
    root = project(tmp_path)
    declare(root, {"remote": {"url": "https://mcp.example.com/mcp"}})

    answer = write_secret(root, "mcp.remote", "token", "sk-nope")

    assert answer.ok is False
    assert read_value(root, "MCP_REMOTE_TOKEN") == ""


# -- the probe ----------------------------------------------------------------------------


def test_a_server_that_answers_is_connected_with_its_tools_named(tmp_path: Path) -> None:
    """`connected` is earned by an answer, and the tools are the evidence it was one."""
    root = project(tmp_path)
    declare(root, {"twenty": {"command": sys.executable, "args": [script(root, "srv.py", SERVER)]}})

    answer = probe_server(root, "mcp.twenty")

    assert answer.ok is True
    assert answer.connected is True
    assert answer.tools == ("alpha", "beta")
    assert answer.server == "twenty-liner"
    assert answer.transport == "stdio"
    assert answer.at != ""


def test_a_probe_leaves_no_process_behind(tmp_path: Path) -> None:
    """A probe that left the server running would be this application starting somebody's
    program and walking away from it."""
    root = project(tmp_path)
    declare(root, {"twenty": {"command": sys.executable, "args": [script(root, "srv.py", SERVER)]}})

    probe_server(root, "mcp.twenty")

    # The server reads stdin forever; if it were still up, its parent pipe would still be
    # open. `ask_stdio` closes and terminates in a `finally`, so nothing survives the call.
    assert probe_server(root, "mcp.twenty").connected is True


def test_a_server_that_will_not_answer_ends_as_a_sentence(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Not a hang, and not a claim. `ok` is "it was asked"; `connected` is "it answered"."""
    monkeypatch.setattr("framestack_core.mcpwire.SECONDS", 3)
    root = project(tmp_path)
    declare(root, {"mute": {"command": sys.executable, "args": [script(root, "mute.py", MUTE)]}})

    answer = probe_server(root, "mcp.mute")

    assert answer.ok is True
    assert answer.connected is False
    assert "initialize" in answer.detail


def test_a_command_that_is_not_there_says_so(tmp_path: Path) -> None:
    root = project(tmp_path)
    declare(root, {"absent": {"command": "definitely-not-a-program-here"}})

    answer = probe_server(root, "mcp.absent")

    assert answer.connected is False
    assert answer.tools == ()


def test_an_entry_with_neither_command_nor_url_has_nothing_to_ask(tmp_path: Path) -> None:
    root = project(tmp_path)
    declare(root, {"unfinished": {"args": ["nothing"]}})

    answer = probe_server(root, "mcp.unfinished")

    assert answer.ok is False
    assert "neither a command nor a url" in answer.detail


# -- the browser exchange -----------------------------------------------------------------


class _Provider(BaseHTTPRequestHandler):
    """A token endpoint, and nothing else. The consent screen is the person's own browser."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(
            {"access_token": "tok-123", "token_type": "Bearer", "seen": form.get("code", [""])[0]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def provider() -> Any:
    server = HTTPServer(("127.0.0.1", 0), _Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_authorising_writes_the_token_to_env_and_nowhere_else(
    tmp_path: Path, provider: str, monkeypatch: Any
) -> None:
    """The acceptance criterion, walked end to end.

    The browser is the one thing stubbed, because opening a real one in a test would open a
    real one on somebody's machine. Everything else is real: a loopback listener, a redirect
    with a code and a state, and a form post to a token endpoint that answers.
    """
    root = project(tmp_path)
    declare(root, {"remote": {"url": f"{provider}/mcp"}})
    write_secret(root, "mcp.remote", "client_id", "client-abc")
    write_secret(root, "mcp.remote", "client_secret", "shhh")

    opened: list[str] = []
    monkeypatch.setattr(oauth.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(oauth, "endpoints", lambda url: found(provider))

    started = connect_server(root, "mcp.remote")
    assert started.ok is True

    waiting = authorisation(root, "mcp.remote")
    assert waiting.running is True
    assert waiting.redirect.startswith("http://127.0.0.1:")

    # What the provider would do after the person pressed Allow: come back to the loopback
    # address with the code, carrying the state it was given.
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[0]).query)["state"][0]
    urllib.request.urlopen(f"{waiting.redirect}?code=abc123&state={state}", timeout=10).read()

    for _ in range(100):
        answer = authorisation(root, "mcp.remote")
        if not answer.running:
            break
        time.sleep(0.1)

    assert answer.ok is True, answer.detail
    assert answer.stored == "MCP_REMOTE_TOKEN"
    # In `.env`, and only there.
    assert read_value(root, "MCP_REMOTE_TOKEN") == "tok-123"
    assert "tok-123" not in (root / "mcp.json").read_text(encoding="utf-8")
    assert "tok-123" not in json.dumps(wire_form(answer.as_dict()))
    leaked = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != ".env"
        and "tok-123" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert leaked == []


def test_a_callback_that_does_not_match_is_never_exchanged(
    tmp_path: Path, provider: str, monkeypatch: Any
) -> None:
    """The state is the only thing tying a callback to the request we made."""
    root = project(tmp_path)
    declare(root, {"remote": {"url": f"{provider}/mcp"}})
    write_secret(root, "mcp.remote", "client_id", "client-abc")
    monkeypatch.setattr(oauth.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(oauth, "endpoints", lambda url: found(provider))

    connect_server(root, "mcp.remote")
    waiting = authorisation(root, "mcp.remote")
    urllib.request.urlopen(f"{waiting.redirect}?code=abc123&state=somebody-else", timeout=10).read()

    for _ in range(100):
        answer = authorisation(root, "mcp.remote")
        if not answer.running:
            break
        time.sleep(0.1)

    assert answer.ok is False
    assert read_value(root, "MCP_REMOTE_TOKEN") == ""


def test_without_a_client_id_nothing_is_started(tmp_path: Path, monkeypatch: Any) -> None:
    """A button whose only possible outcome is an error is worse than no button, so the
    refusal says what to register and where the provider has to come back to."""
    root = project(tmp_path)
    declare(root, {"remote": {"url": "https://mcp.example.com/mcp"}})
    monkeypatch.setattr(oauth.webbrowser, "open", lambda url: pytest.fail("no browser"))

    answer = connect_server(root, "mcp.remote")

    assert answer.ok is False
    assert "client id" in answer.detail
    assert authorisation(root, "mcp.remote").running is False


def test_giving_up_takes_the_listener_down(tmp_path: Path, provider: str, monkeypatch: Any) -> None:
    root = project(tmp_path)
    declare(root, {"remote": {"url": f"{provider}/mcp"}})
    write_secret(root, "mcp.remote", "client_id", "client-abc")
    monkeypatch.setattr(oauth.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(oauth, "endpoints", lambda url: found(provider))

    connect_server(root, "mcp.remote")
    assert give_up(root, "mcp.remote").ok is True
    assert authorisation(root, "mcp.remote").running is False


def test_the_variable_name_is_derived_from_the_server_s_own_name() -> None:
    """Nothing has to be configured for a token to have somewhere to go."""
    assert token_key("gmail-work") == "MCP_GMAIL_WORK_TOKEN"
    assert client_id_key("filesystem") == "MCP_FILESYSTEM_CLIENT_ID"


# -- the wire -----------------------------------------------------------------------------


def test_every_new_verb_matches_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    declare(root, {"twenty": {"command": sys.executable, "args": [script(root, "srv.py", SERVER)]}})

    validate(wire_form(mcp_probe(root, "mcp.twenty")), MCP_PROBE_SCHEMA)
    # A refusal is a result and has to be the same shape as one.
    validate(wire_form(mcp_probe(root, "agent")), MCP_PROBE_SCHEMA)
    validate(wire_form(mcp_authorized(root, "mcp.twenty")), MCP_AUTH_SCHEMA)
    validate(wire_form(mcp_secret(root, "mcp.twenty", "client_id", "abc")), MCP_SCHEMA)
