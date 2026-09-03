"""What `mcp.json` declares about a server, how a person authorises one, and what it offers.

## Two kinds of entry, and `Connect` means something different for each

A **`command`** entry is a stdio server: a program started as a child process and spoken to
over its pipes. The MCP authorization specification does not describe those — it covers the
HTTP transports — and the ones that need an account open a browser themselves on first run.
So `Connect` there is what it always was: the server's own command, run once in the terminal
where a person can watch every line of it and stop it themselves. Nothing is orchestrated and
nothing is intercepted.

A **`url`** entry is an HTTP server, and there the authorization spec does apply. `Connect`
runs path one of Phase 10: the person registers an OAuth app in the provider's own console,
pastes the client id and secret, the system browser opens on the consent screen, and the
token lands in `.env`. `oauth.py` is that flow; there is no Framestack-owned OAuth app and
there will not be one.

## The tool count is the evidence, and nothing else is

`probe_server` speaks the protocol: `initialize`, then `tools/list`. **`connected` means a
server answered, at a time** — the same rule the verdicts follow, that a claim is earned by
something that happened rather than by a configuration existing. A server that has not been
asked has no state at all, drawn as nothing rather than as a hopeful default, and a probe
that failed reports the server's own words.

Nothing is remembered on disk. An answer about a live process goes stale the moment the
process does, and a stored one would be a claim outliving the thing it was about.

## What this module still refuses to do

**No value ever leaves in a payload.** Only the *names* of the variables an entry sets and
the names of the keys `.env` holds; whether a key is set is a fact worth sending, and what it
is set to is one console log away from being somewhere permanent. The token this application
writes is written to `.env` and read back only into an `Authorization` header.

**Nothing here calls a tool.** `tools/list` is a question; `tools/call` is somebody's
mailbox. There is no verb in this codebase that invokes anything a server offers.

**Nothing starts implicitly (P11).** A probe spawns a process or makes a request, so it
happens because somebody pressed something.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from framestack_core.envfile import names as env_names
from framestack_core.envfile import read_value, write_value
from framestack_core.mcpwire import ask_http, ask_stdio
from framestack_core.oauth import (
    Auth,
    client_id_key,
    client_secret_key,
    read_auth,
    start_auth,
    stop_auth,
    token_key,
)
from framestack_core.parser import MCP_KIND, read_graph
from framestack_core.shell import open_shell, write_shell

__all__ = [
    "McpResult",
    "Probe",
    "authorisation",
    "connect_server",
    "give_up",
    "probe_server",
    "read_server",
    "write_secret",
]

#: The file every one of these facts comes from. The parser already reads it.
MCP_FILE = "mcp.json"

#: Named in a refusal, so a person is told which file did not take the write.
ENV_NOTE = ".env"


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
    #: `stdio` for a `command` entry, `http` for a `url` one, `""` where the entry declares
    #: neither. Which one it is decides what `Connect` means, so it is stated rather than
    #: inferred by whoever draws the button.
    transport: str = ""
    #: The address of an HTTP server, as the file gives it. `""` for a stdio entry.
    url: str = ""
    #: The three variables an HTTP server's authorisation uses, **by name**. Sent so the
    #: panel can label its own fields with the exact names it is writing to.
    keys: tuple[str, ...] = ()
    #: Which of those `.env` currently sets. A fact worth sending; the values are not.
    given: tuple[str, ...] = ()

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
            "transport": self.transport,
            "url": self.url,
            "keys": list(self.keys),
            "given": list(self.given),
        }


@dataclass(frozen=True)
class Probe:
    """What a server answered when it was asked what it offers.

    **`connected` is earned.** It means this server answered `tools/list` at `at`, and
    nothing else produces it: not an entry existing, not a command being on `PATH`, not a
    token being present in `.env`. A server nobody has asked has no probe at all.
    """

    ok: bool
    detail: str
    node: str = ""
    name: str = ""
    connected: bool = False
    #: The tools it named, in its own order. The count is the proof; the names are what a
    #: person recognises the server by.
    tools: tuple[str, ...] = ()
    #: What the server calls itself, from its `initialize` answer.
    server: str = ""
    transport: str = ""
    at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "name": self.name,
            "connected": self.connected,
            "tools": list(self.tools),
            "server": self.server,
            "transport": self.transport,
            "at": self.at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    url = entry.get("url")

    keys = (client_id_key(name), client_secret_key(name), token_key(name))
    held = env_names(root)

    return McpResult(
        True,
        f"{name} is declared in {MCP_FILE}",
        node,
        name,
        command=command if isinstance(command, str) else "",
        args=tuple(str(one) for one in given) if isinstance(given, list) else (),
        # Names only. The values stay in the file.
        env=tuple(sorted(str(key) for key in environment)) if isinstance(environment, dict) else (),
        # A `url` entry is an HTTP server and `Connect` authorises it; a `command` entry is a
        # stdio one and `Connect` runs it. An entry with neither is one a person has still to
        # finish writing, and it is reported as such rather than guessed at.
        transport="http" if isinstance(url, str) and url else "stdio" if command else "",
        url=url if isinstance(url, str) else "",
        keys=keys,
        given=tuple(key for key in keys if key in held),
    )


def write_secret(project: Path | str, node: str, field: str, value: str) -> McpResult:
    """Put a client id or secret in `.env`, under the name this server's flow will look for.

    Two fields and no others: these are the credentials a person registered in the provider's
    own console, and there is no third thing this application would know what to do with. The
    token is not among them — that is written by the flow, never typed.

    What comes back is the entry **re-read**, so the panel learns which keys are now set from
    the file rather than from its own optimism. No value is ever in that answer.
    """
    root = Path(project).expanduser()
    declared = read_server(root, node)
    if not declared.ok:
        return declared

    wanted = {"client_id": client_id_key, "client_secret": client_secret_key}.get(field)
    if wanted is None:
        return McpResult(
            False,
            f"{field!r} is not a credential of this server -- only client_id, client_secret",
            node,
            declared.name,
        )
    if not write_value(root, wanted(declared.name), value.strip()):
        return McpResult(False, f"{ENV_NOTE} could not be written", node, declared.name)

    answer = read_server(root, node)
    return McpResult(
        answer.ok,
        f"{wanted(declared.name)} is set",
        node,
        answer.name,
        command=answer.command,
        args=answer.args,
        env=answer.env,
        transport=answer.transport,
        url=answer.url,
        keys=answer.keys,
        given=answer.given,
    )


def probe_server(project: Path | str, node: str) -> Probe:
    """Ask the server what it offers. Never implicit (P11): this starts a process or a request.

    The whole of what `connected` means. A stdio server is started, greeted, asked for its
    tools and stopped again; an HTTP one is asked over the wire with whatever `Authorization`
    header `.env` supplies. Either way the answer is the server's, and a failure carries its
    words rather than ours.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return Probe(False, f"there is no project at {root}", node)

    declared = read_server(root, node)
    if not declared.ok:
        return Probe(False, declared.detail, node, declared.name)

    entry, _, why = _entry(root, node)
    if entry is None:
        return Probe(False, why, node, declared.name)

    if declared.transport == "http":
        answered = ask_http(root, entry, declared.url)
    elif declared.transport == "stdio":
        answered = ask_stdio(root, entry, declared.command, declared.args)
    else:
        return Probe(
            False,
            f"{declared.name} declares neither a command nor a url, so there is nothing to ask",
            node,
            declared.name,
        )

    return Probe(
        # `ok` is "the question was asked"; `connected` is "the server answered it". A probe
        # that reached a server which refused is a successful probe with a negative answer,
        # and merging the two would lose the sentence that says what to do about it.
        True,
        answered.detail,
        node,
        declared.name,
        connected=answered.ok,
        tools=answered.tools,
        server=answered.server,
        transport=declared.transport,
        at=_now(),
    )


def authorisation(project: Path | str, node: str) -> Auth:
    """How an authorisation is going. A read: it opens no browser and asks no provider."""
    return read_auth(project, node)


def give_up(project: Path | str, node: str) -> Auth:
    """Stop waiting for a browser. The listener goes; nothing was written."""
    return stop_auth(project, node)


def connect_server(project: Path | str, node: str) -> McpResult:
    """`Connect`, which means a different thing for each of the two kinds of entry.

    Never implicit (P11): somebody pressed it.

    For a **stdio** server it runs the server's own command in the terminal, so the program
    can authorise itself the way it would have if the person had typed it. It goes to the
    terminal on purpose — this starts a program out of a file with somebody's account on the
    other end, and the honest place for that is where they can read every line and stop it.

    For an **HTTP** server it starts path one of Phase 10: the browser opens on the
    provider's consent screen with the client id the person registered, and the token lands
    in `.env`. Whether they finished is polled through `authorisation`, because a verb that
    waited would hold the window while somebody signed in on their phone.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return McpResult(False, f"there is no project at {root}", node)

    declared = read_server(root, node)
    if not declared.ok:
        return declared

    if declared.transport == "http":
        # The credentials are the person's own, registered in the provider's console. There
        # is no Framestack OAuth app and there will not be one: every user under one
        # registration is one revocation away from everybody stopping at once.
        started = start_auth(
            root,
            node,
            declared.name,
            declared.url,
            read_value(root, client_id_key(declared.name)),
            read_value(root, client_secret_key(declared.name)),
        )
        return McpResult(
            started.ok,
            started.detail,
            node,
            declared.name,
            transport=declared.transport,
            url=declared.url,
            keys=declared.keys,
            given=declared.given,
        )

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
