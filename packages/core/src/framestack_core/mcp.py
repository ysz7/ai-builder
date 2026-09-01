"""What `mcp.json` declares about a server, and how a person authorises one.

## What `Connect` actually is

An MCP server configured in `mcp.json` is a **stdio** server: a `command` and its `args`,
started as a child process and spoken to over its pipes. The MCP authorization specification
does not apply to it — that describes the HTTP transports — so there is no protocol handshake
here to drive, and becoming an MCP client would not produce a `Connect` button. What these
servers do is far simpler: on first run, the ones that need an account **open a browser
themselves** and write their own token wherever they keep it.

So `Connect` runs the server's own command, once, in the terminal, where the person can see
it. That is the whole feature, and its honesty is the point: nothing is orchestrated, nothing
is intercepted, and the thing that happens is the thing that would have happened if they had
typed the command themselves.

## What this module refuses to do

**It stores no credential.** Not in `.framestack/`, not in a keychain, not in memory. There
is no HTTP client to anybody's API in this codebase and no reason to acquire one: the token
is the server's, it never passes through here, and a builder holding somebody's Gmail
credentials would be a liability offered in exchange for nothing.

**It never sends a value out of `.env` or out of the entry's `env` block.** Only the *names*.
A server's entry may legitimately hold a secret inline, and a payload crossing into a webview
is the wrong place for it to appear — one console log or one crash report away from being
somewhere permanent.

**It does not ask the server anything, and it cannot say whether a server is connected.**
Only the server knows that, and finding out means speaking the protocol to it. So this
reports what *this application did* — a command was run, at a time — and never makes a claim
about the far side. A green tick nobody verified is the same defect as a green node nobody
ran a test for.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framestack_core.parser import MCP_KIND, read_graph
from framestack_core.shell import open_shell, write_shell

__all__ = ["McpResult", "connect_server", "read_server"]

#: The file every one of these facts comes from. The parser already reads it.
MCP_FILE = "mcp.json"


@dataclass(frozen=True)
class McpResult:
    """What one entry declares, and what pressing `Connect` did."""

    ok: bool
    detail: str
    node: str = ""
    name: str = ""
    #: The program that starts it, exactly as the file gives it. `""` where none is declared.
    command: str = ""
    args: tuple[str, ...] = ()
    #: The **names** of the environment variables the entry sets. Never the values (see the
    #: module docstring): a secret that reaches a webview is a secret in somebody's console.
    env: tuple[str, ...] = ()
    #: The shell `Connect` opened, so the caller can show the terminal it is happening in.
    shell: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "env": list(self.env),
            "shell": self.shell,
        }


def _entry(root: Path, node: str) -> tuple[dict[str, Any] | None, str, str]:
    """`(the entry, the server's name, why not)`.

    Resolved through the **graph** rather than by splitting the node id, so a caller cannot
    ask about a server the parser does not report. The parser is the one reader of this file
    and this stays downstream of it.
    """
    found = [item for item in read_graph(root).nodes if item.id == node]
    if not found or found[0].kind != MCP_KIND:
        return None, "", f"there is no MCP server called {node!r} here"

    name = found[0].name
    try:
        loaded = json.loads((root / MCP_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # The parser tolerates a broken file by drawing no servers; this one was drawn, so
        # the file changed underneath us. Said plainly rather than treated as a fault.
        return None, name, f"{MCP_FILE} could not be read: {exc}"

    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    entry = servers.get(name) if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        return None, name, f"{MCP_FILE} no longer declares {name!r}"
    return entry, name, ""


def read_server(project: Path | str, node: str) -> McpResult:
    """What the file says about one server. A read: it starts nothing and asks nobody."""
    root = Path(project).expanduser()
    if not root.is_dir():
        return McpResult(False, f"there is no project at {root}", node)

    entry, name, why = _entry(root, node)
    if entry is None:
        return McpResult(False, why, node, name)

    command = entry.get("command")
    given = entry.get("args")
    environment = entry.get("env")

    return McpResult(
        True,
        f"{name} is declared in {MCP_FILE}",
        node,
        name,
        command=command if isinstance(command, str) else "",
        args=tuple(str(one) for one in given) if isinstance(given, list) else (),
        # Names only. The values stay in the file.
        env=tuple(sorted(str(key) for key in environment)) if isinstance(environment, dict) else (),
    )


def connect_server(project: Path | str, node: str) -> McpResult:
    """Run the server's own command in a terminal, so it can authorise itself.

    Never implicit (P11): somebody pressed `Connect`. It goes to the **terminal** rather than
    to a hidden process on purpose — this starts a program out of a file with a person's
    account on the other end of it, and the honest place for that is where they can read
    every line of what it prints and stop it themselves.

    What comes back is which shell it is running in. Whether the server ended up authorised
    is the server's business and is never claimed here.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return McpResult(False, f"there is no project at {root}", node)

    declared = read_server(root, node)
    if not declared.ok:
        return declared
    if not declared.command:
        # No command is not a failure of ours, and it is not repaired into a guess: an entry
        # with nothing to run is one a person has to finish writing.
        return McpResult(
            False,
            f"{declared.name} declares no command to run, so there is nothing to connect",
            node,
            declared.name,
        )

    opened = open_shell(root, declared.name)
    if not opened.ok:
        return McpResult(False, opened.detail, node, declared.name)

    # Quoted with `shlex`, because the args come out of a file a person edits by hand and go
    # into a shell. A path with a space in it is the ordinary case, not the adversarial one.
    line = shlex.join([declared.command, *declared.args])
    typed = write_shell(root, opened.shell, line + "\n")
    if not typed.ok:
        return McpResult(False, typed.detail, node, declared.name, shell=opened.shell)

    return McpResult(
        True,
        # Said as what happened, never as what it achieved. See the module docstring: only the
        # server knows whether it is connected, and this never asks it.
        f"running {declared.name} in a terminal — it authorises itself, and keeps its own token",
        node,
        declared.name,
        command=declared.command,
        args=declared.args,
        env=declared.env,
        shell=opened.shell,
    )
