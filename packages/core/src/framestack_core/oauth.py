"""Authorising one HTTP MCP server, with credentials the person registered themselves.

Phase 10, path one. The person registers an OAuth app in the provider's own console, pastes
the client id and secret into the node's panel, and presses `Connect`; the system browser
opens, they authorise, and the token lands in `.env`.

## Why the credentials are theirs and not ours

**There is no Framestack OAuth app and there will not be one.** Every user's traffic under one
registration means shared rate limits, one terms-of-service exposure and a single point of
revocation — one provider's decision, and every project on every machine stops working. That
is path three in the plan and it is named there so it does not creep in.

Dynamic client registration — where the client registers itself at connect time and nobody
pastes anything — is path two, and it is *later*: support across servers is uneven, and the
fallback when it is missing is exactly what is built here. This ships first because it works
everywhere.

## Where the token goes, and what never holds it

`.env`, gitignored, under a name derived from the server's. `mcp.json` holds the server and
the **name** of that variable; it never holds the secret, and nothing in this codebase writes
a secret into it. No value crosses the wire to the UI — a payload says a key is set, never
what it is.

## The loopback listener

The redirect goes to `http://127.0.0.1:<port>/callback`, on a socket opened for this one
exchange and closed after it. It is bound to the loopback interface, it answers exactly one
path, and it is torn down when the flow ends or times out — a listener that outlived its
flow would be a port on somebody's machine kept open by a builder.

PKCE is used unconditionally. The secret is sent to the token endpoint where the provider
requires one, and the challenge is what makes the code useless to anybody who intercepts it.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from framestack_core.envfile import write_value

__all__ = [
    "Auth",
    "client_id_key",
    "client_secret_key",
    "key_for",
    "read_auth",
    "start_auth",
    "stop_auth",
    "token_key",
]

#: How long a person has to finish authorising before the listener is taken down. Generous:
#: a provider's consent screen may ask them to sign in first, and on a phone at that.
SECONDS = 300

#: What the browser is sent back to. One path, on loopback, for one exchange.
CALLBACK = "/callback"

#: Anything that cannot be part of a variable name. A server called `gmail-work` becomes
#: `GMAIL_WORK`, which is a name `.env` can hold and a person can recognise.
UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def key_for(name: str, suffix: str) -> str:
    """The variable a server's secret goes under. Derived, so nothing has to be configured."""
    slug = UNSAFE.sub("_", name).strip("_").upper()
    return f"MCP_{slug}_{suffix}"


def client_id_key(name: str) -> str:
    return key_for(name, "CLIENT_ID")


def client_secret_key(name: str) -> str:
    return key_for(name, "CLIENT_SECRET")


def token_key(name: str) -> str:
    return key_for(name, "TOKEN")


@dataclass(frozen=True)
class Auth:
    """Where one authorisation got to. A refusal is a result, never a protocol fault."""

    ok: bool
    detail: str
    node: str = ""
    #: Whether the browser is still out there with somebody in front of it.
    running: bool = False
    #: The URL the browser was sent to, so a person who lost the window can open it again.
    #: It carries a client id and a challenge, never a secret.
    url: str = ""
    #: Where the provider was told to come back to. Shown because the person has to register
    #: exactly this in the provider's console before any of it can work.
    redirect: str = ""
    #: The variable the token was written to. The **name**; never the value.
    stored: str = ""
    at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "running": self.running,
            "url": self.url,
            "redirect": self.redirect,
            "stored": self.stored,
            "at": self.at,
        }


@dataclass
class _Flow:
    """One exchange in progress. Held in memory only: it is about a browser, not a project."""

    node: str
    server: _Listener
    url: str
    redirect: str
    result: Auth


#: Every flow this sidecar started, keyed by `<project>::<node>`. One per node: a second
#: press while a browser is already open is the same exchange, not a new one.
_FLOWS: dict[str, _Flow] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _key(project: Path, node: str) -> str:
    return f"{project}::{node}"


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _get_json(url: str) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
        with urllib.request.urlopen(request, timeout=15) as answer:  # noqa: S310
            loaded = json.loads(answer.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def endpoints(url: str) -> tuple[str, str]:
    """`(authorize, token)` for the server at `url`, discovered the way the spec says.

    The protected resource points at its authorization server, and that server describes
    itself. Where a provider publishes neither document — plenty do not — the conventional
    paths on its own origin are used and the failure, if it is one, is the provider's own
    error page in the person's browser rather than a guess dressed up as a diagnosis.
    """
    origin = _origin(url)
    issuer = origin
    resource = _get_json(f"{origin}/.well-known/oauth-protected-resource")
    if resource:
        servers = resource.get("authorization_servers")
        if isinstance(servers, list) and servers and isinstance(servers[0], str):
            issuer = servers[0].rstrip("/")

    for well_known in (
        f"{issuer}/.well-known/oauth-authorization-server",
        f"{issuer}/.well-known/openid-configuration",
    ):
        described = _get_json(well_known)
        if described:
            authorize = described.get("authorization_endpoint")
            token = described.get("token_endpoint")
            if isinstance(authorize, str) and isinstance(token, str):
                return authorize, token

    return f"{issuer}/authorize", f"{issuer}/token"


class _Listener(HTTPServer):
    """The loopback socket for one exchange, and the one thing the callback leaves behind.

    A subclass rather than an attribute bolted onto an `HTTPServer`, so what the handler
    hands over has a declared shape: `(code, state, error)`, or `None` while nobody has come
    back yet.
    """

    answer: tuple[str, str, str] | None = None


class _Callback(BaseHTTPRequestHandler):
    """The one page the provider sends the browser back to."""

    # Silenced: this is a person's browser, and a builder writing their query string to a log
    # would be writing an authorization code to a log.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's own name
        parts = urllib.parse.urlsplit(self.path)
        if parts.path != CALLBACK:
            self.send_response(404)
            self.end_headers()
            return
        query = urllib.parse.parse_qs(parts.query)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        refused = (query.get("error") or [""])[0]
        # Handed to the waiting thread rather than acted on here: the exchange talks to the
        # provider, and doing that inside a request handler would tie a token to a socket.
        listener = self.server
        assert isinstance(listener, _Listener)
        listener.answer = (code, state, refused)

        said = (
            "You can close this tab." if code else f"Authorisation failed: {refused or 'no code'}"
        )
        body = f"<!doctype html><meta charset=utf-8><p>{said}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _exchange(
    token_url: str,
    code: str,
    verifier: str,
    client: str,
    secret: str,
    redirect: str,
    resource: str,
) -> tuple[str, str]:
    """`(the access token, "")`, or `("", why not)`. The one request that carries a secret."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "client_id": client,
        "code_verifier": verifier,
        "resource": resource,
    }
    if secret:
        form["client_secret"] = secret
    request = urllib.request.Request(  # noqa: S310 -- the provider's own token endpoint
        token_url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            loaded = json.loads(answer.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        # The provider's own words, not ours. A token endpoint refusing a code says why, and
        # rewriting that into "authorisation failed" would throw away the useful half.
        said = exc.read().decode("utf-8", "replace")[:200]
        return "", f"the token endpoint answered {exc.code}: {said}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return "", f"the token could not be fetched: {exc}"

    token = loaded.get("access_token") if isinstance(loaded, dict) else None
    if not isinstance(token, str) or not token:
        return "", "the token endpoint answered without an access token"
    return token, ""


def start_auth(
    project: Path | str,
    node: str,
    name: str,
    url: str,
    client: str,
    secret: str,
) -> Auth:
    """Open the browser on the provider's consent screen. Never implicit (P11).

    Returns as soon as the browser has been opened; whether the person authorised is polled
    with `read_auth`, because a verb that blocked would hold the window for five minutes
    while somebody signed in on their phone.
    """
    root = Path(project).expanduser()
    if not client:
        return Auth(
            False,
            f"paste a client id first — register one in the provider's console, with "
            f"{CALLBACK} on 127.0.0.1 as the redirect",
            node,
        )

    where = _key(root, node)
    with _LOCK:
        running = _FLOWS.get(where)
        if running is not None:
            # The same exchange, not a second one: a person pressing twice has one browser
            # open, and starting another listener would leave the first one holding a port.
            return Auth(
                True,
                "a browser is already open for this server",
                node,
                running=True,
                url=running.url,
                redirect=running.redirect,
                at=_now(),
            )

    try:
        server = _Listener(("127.0.0.1", 0), _Callback)
    except OSError as exc:
        return Auth(False, f"nothing could listen for the callback: {exc}", node)
    # A second at a time, so the loop below can notice its own deadline rather than sitting
    # in `accept` until somebody's browser turns up.
    server.timeout = 1

    redirect = f"http://127.0.0.1:{server.server_port}{CALLBACK}"
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    state = secrets.token_urlsafe(16)
    authorize, token_url = endpoints(url)
    opened = (
        authorize
        + ("&" if "?" in authorize else "?")
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client,
                "redirect_uri": redirect,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                # Which server this token is for. The MCP spec asks for it, and a token bound to
                # one resource is one that cannot be replayed against another.
                "resource": url,
            }
        )
    )

    flow = _Flow(
        node=node,
        server=server,
        url=opened,
        redirect=redirect,
        result=Auth(
            True,
            "waiting for the browser",
            node,
            running=True,
            url=opened,
            redirect=redirect,
            at=_now(),
        ),
    )
    with _LOCK:
        _FLOWS[where] = flow

    def wait() -> None:
        import time

        deadline = time.monotonic() + SECONDS
        answer: tuple[str, str, str] | None = None
        while time.monotonic() < deadline:
            try:
                server.handle_request()
            except (OSError, ValueError):
                # The socket went out from under us, which is what `stop_auth` does when
                # somebody gives up. Ending quietly is the whole of the right behaviour: the
                # flow has already been forgotten, and there is nothing left to answer to.
                return
            answer = server.answer
            if answer is not None:
                break
        _close(server)

        if answer is None:
            _finish(where, Auth(False, "nobody authorised it in time", node, at=_now()))
            return
        code, back, refused = answer
        if refused or not code:
            said = refused or "no code"
            _finish(where, Auth(False, f"the provider refused: {said}", node, at=_now()))
            return
        if back != state:
            # The state is the only thing tying this callback to the request we made. A
            # mismatch is somebody else's callback and is never exchanged.
            _finish(where, Auth(False, "the callback did not match this request", node, at=_now()))
            return

        token, why = _exchange(token_url, code, verifier, client, secret, redirect, url)
        if not token:
            _finish(where, Auth(False, why, node, at=_now()))
            return
        stored = token_key(name)
        if not write_value(root, stored, token):
            _finish(where, Auth(False, "the token could not be written to .env", node, at=_now()))
            return
        _finish(
            where,
            Auth(
                True,
                # Said as what happened. Whether the server accepts it is a question only the
                # server can answer, and `mcp.probe` is where that is asked.
                f"authorised — the token is in .env as {stored}",
                node,
                stored=stored,
                at=_now(),
            ),
        )

    threading.Thread(target=wait, daemon=True).start()
    # The browser, opened by the person's own default. Nothing is embedded and nothing is
    # intercepted: what happens next happens between them and the provider.
    webbrowser.open(opened)
    return flow.result


def _close(server: HTTPServer) -> None:
    with contextlib.suppress(OSError):
        server.server_close()


def _finish(where: str, result: Auth) -> None:
    with _LOCK:
        flow = _FLOWS.get(where)
        if flow is not None:
            flow.result = result
            # The flow stays in the table until it is read, so the answer is not lost between
            # the browser closing and the panel's next poll.


def read_auth(project: Path | str, node: str) -> Auth:
    """How the exchange went. A read: it opens no browser and asks no provider.

    A finished flow is handed over once and then forgotten — it is a fact about a browser
    session, and keeping it would mean a panel opened tomorrow still saying "authorised".
    """
    where = _key(Path(project).expanduser(), node)
    with _LOCK:
        flow = _FLOWS.get(where)
        if flow is None:
            return Auth(True, "nothing is being authorised here", node)
        if flow.result.running:
            return flow.result
        del _FLOWS[where]
        return flow.result


def stop_auth(project: Path | str, node: str) -> Auth:
    """Give up on an exchange. The listener goes; nothing was written."""
    where = _key(Path(project).expanduser(), node)
    with _LOCK:
        flow = _FLOWS.pop(where, None)
    if flow is None:
        return Auth(True, "nothing was being authorised here", node)
    _close(flow.server)
    return Auth(True, "stopped waiting for the browser", node, at=_now())
