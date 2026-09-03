"""One MCP server: what the file says, and what `Connect` does for a stdio entry.

Two of these matter more than the rest, and both are about what must **not** happen:

* **No credential ever leaves the file it is in.** An entry's `env` block may hold a secret
  inline, and the payload it would land in crosses into a webview — one console log away from
  somewhere permanent. Only the names are sent.
* **Neither of these verbs claims the server is connected.** Running a command is not being
  told anything back. The verb that may claim it is `mcp.probe`, which asks — see
  `test_mcp_connect.py`, where Phase 10's half of this lives.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import MCP_SCHEMA, mcp_connect, mcp_read
from framestack_core.mcp import connect_server, read_server
from framestack_core.shell import close_everything_opened_here, list_shells, read_shell

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "reference"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def declare(root: Path, servers: dict[str, object]) -> None:
    (root / "mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


# -- what the file says -------------------------------------------------------------------


def test_a_server_reports_the_command_the_file_gives_it(tmp_path: Path) -> None:
    answer = read_server(project(tmp_path), "mcp.filesystem")

    assert answer.ok
    assert answer.name == "filesystem"
    assert answer.command == "npx"
    assert answer.args == ("-y", "@modelcontextprotocol/server-filesystem", ".")


def test_only_the_names_of_the_environment_are_ever_reported(tmp_path: Path) -> None:
    """The rule this module exists to keep, stated as the test that would catch breaking it.

    A person may well have put a real token in this file. It is theirs and it stays there;
    what a panel needs is the names, and sending the values buys nothing in exchange for
    putting a secret somewhere it can be logged.
    """
    root = project(tmp_path)
    declare(
        root,
        {"gmail": {"command": "uvx", "args": ["gmail-mcp"], "env": {"GMAIL_TOKEN": "sk-secret"}}},
    )

    answer = read_server(root, "mcp.gmail")

    assert answer.env == ("GMAIL_TOKEN",)
    assert "sk-secret" not in json.dumps(answer.as_dict())


def test_a_node_that_is_not_a_server_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert not read_server(root, "agent").ok
    assert not read_server(root, "mcp.json").ok
    assert "no MCP server" in read_server(root, "nowhere").detail


# -- what Connect does, and what it refuses to claim ----------------------------------------


def test_connecting_runs_the_server_s_own_command_in_a_terminal(tmp_path: Path) -> None:
    """The whole feature. Nothing is orchestrated: the command in the file is the command
    that runs, where a person can read it."""
    root = project(tmp_path)
    declare(root, {"greeter": {"command": "echo", "args": ["hello from the server"]}})

    try:
        answer = connect_server(root, "mcp.greeter")

        assert answer.ok, answer.detail
        assert answer.shell
        assert [one["id"] for one in list_shells(root).shells] == [answer.shell]

        # What it printed is the server's own output, in a terminal the person owns.
        seen = ""
        for _ in range(200):
            seen += read_shell(root, answer.shell, len(seen.encode())).output
            if "hello from the server" in seen:
                break
        assert "hello from the server" in seen
    finally:
        close_everything_opened_here()


def test_reading_or_connecting_never_claims_the_server_is_connected(tmp_path: Path) -> None:
    """I-3's argument, applied to somebody else's program.

    Only the server knows whether it is authorised, so neither of these verbs says. Since
    Phase 10 there *is* something that says — `mcp.probe`, which asks the server and carries
    the tool count as its evidence — and the separation is the point: a claim comes from the
    thing that asked, never from a command having been run or an entry existing.
    """
    root = project(tmp_path)
    declare(root, {"greeter": {"command": "echo", "args": ["hi"]}})

    try:
        payload = mcp_connect(root, "mcp.greeter")
        assert "connected" not in payload
        assert "connected" not in payload["detail"]
    finally:
        close_everything_opened_here()


def test_an_entry_with_no_command_offers_nothing_and_says_why(tmp_path: Path) -> None:
    root = project(tmp_path)
    declare(root, {"halfwritten": {"args": ["nothing"]}})

    answer = connect_server(root, "mcp.halfwritten")

    assert not answer.ok
    assert "declares no command" in answer.detail
    assert list_shells(root).shells == ()


def test_connecting_stores_no_credential_anywhere(tmp_path: Path) -> None:
    """There is nowhere in this application a token would go, and this is how that stays true."""
    root = project(tmp_path)
    declare(root, {"greeter": {"command": "echo", "args": ["hi"], "env": {"TOKEN": "sk-secret"}}})

    try:
        connect_server(root, "mcp.greeter")
        written = [
            path
            for path in (root / ".framestack").rglob("*")
            if path.is_file() and "sk-secret" in path.read_text(encoding="utf-8", errors="replace")
        ]
        assert written == []
    finally:
        close_everything_opened_here()


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert not read_server(tmp_path / "nothing", "mcp.x").ok
    assert not connect_server(tmp_path / "nothing", "mcp.x").ok


def test_every_verb_matches_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    declare(root, {"greeter": {"command": "echo", "args": ["hi"]}})

    try:
        validate(wire_form(mcp_read(root, "mcp.greeter")), MCP_SCHEMA)
        validate(wire_form(mcp_connect(root, "mcp.greeter")), MCP_SCHEMA)
        # And a refusal, which is a result and has to be the same shape as one.
        validate(wire_form(mcp_read(root, "agent")), MCP_SCHEMA)
    finally:
        close_everything_opened_here()
