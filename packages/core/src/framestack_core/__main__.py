"""Entry point.

This is the **sidecar**: NDJSON requests on stdin, NDJSON responses on stdout. That is how
Tauri spawns it, so the argument-free path must never change meaning.

    echo '{"id":1,"method":"ping"}' | uv run python -m framestack_core

There are no subcommands. The old CLI was a face on the parser, the gate, the observer and
the writer, and the rebuild deleted all four; the ones the new design needs are added back
beside the capability they drive, never ahead of it.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import TextIO

from framestack_core.deploy import close_everything_deployed_here
from framestack_core.handlers import dispatch
from framestack_core.observe import close_everything_observed_here
from framestack_core.protocol import (
    ProtocolError,
    decode_request,
    encode_error,
    encode_result,
)
from framestack_core.run import close_everything_run_here
from framestack_core.session import close_everything_started_here
from framestack_core.shell import close_everything_opened_here
from framestack_core.watch import stop_watching_everything


def log(message: str) -> None:
    """stderr only. stdout is the wire; a stray print there corrupts the stream."""
    print(f"[core] {message}", file=sys.stderr, flush=True)


#: How long the reader waits for answers still being written when stdin closes. Short: the
#: window has gone, so a handler still working has nobody to tell, and the shutdown below is
#: what actually has to happen. The threads are daemons, so one that ignores this dies with
#: the process rather than holding it open.
GOODBYE = 2.0

#: One request at a time **per method**, and that is the whole of the concurrency rule.
#:
#: Requests used to be answered one after another, which meant a handler that spawned a
#: subprocess -- classifying a chat message, probing a server, asking `docker compose` --
#: stopped the core answering anything at all, and the window froze around it. They now run
#: on a thread each. What that must not do is let two calls of the *same* method interleave:
#: the state a handler keeps is a dict keyed by project, and "start it if it is not already
#: running" read twice at once starts it twice. Serialising by method keeps every one of
#: those check-then-act pairs exactly as sequential as it was, while a poll of a different
#: method goes through beside it.
_METHOD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS = threading.Lock()

#: stdout carries the wire, so a line is written whole or the stream is corrupted.
_WRITING = threading.Lock()


def _lock_for(method: str) -> threading.Lock:
    with _LOCKS:
        return _METHOD_LOCKS.setdefault(method, threading.Lock())


def handle_line(line: str) -> str | None:
    """Turn one request line into one response line. Never raises."""
    line = line.strip()
    if not line:
        return None

    try:
        request = decode_request(line)
    except ProtocolError as exc:
        return encode_error(exc.request_id, exc.code, exc.message)

    log(f"-> {request.method} (id={request.id!r})")

    with _lock_for(request.method):
        try:
            return encode_result(request.id, dispatch(request.method, request.params, request.id))
        except ProtocolError as exc:
            return encode_error(request.id, exc.code, exc.message)
        except Exception as exc:  # a handler bug must not take the core down
            log(f"handler {request.method!r} raised: {exc!r}")
            return encode_error(request.id, "handler_error", f"{type(exc).__name__}: {exc}")


def _answer(line: str, stdout: TextIO) -> None:
    """One request, answered off the reader so the next one can be read while it works."""
    response = handle_line(line)
    if response is None:
        return
    with _WRITING:
        stdout.write(response + "\n")
        stdout.flush()


def serve(stdin: TextIO, stdout: TextIO) -> None:
    """Read requests forever; answer each on its own thread.

    **Responses are no longer in request order, and never were required to be**: `id` is
    echoed verbatim and the shell matches on it, which is the only reason this change is a
    change to the core alone. What the reader keeps is the one thing a wire needs -- a line
    is written whole -- and the ordering it gives up is the thing that was costing the
    window every subprocess a handler spawned.
    """
    live: list[threading.Thread] = []
    for line in stdin:
        if not line.strip():
            continue
        thread = threading.Thread(target=_answer, args=(line, stdout), daemon=True)
        live.append(thread)
        thread.start()
        live = [one for one in live if one.is_alive()]

    # stdin closed: answer what can still be answered before the shutdown below starts
    # taking things down underneath it.
    for thread in live:
        thread.join(GOODBYE)


def main() -> int:
    """The sidecar. Ends whatever it started before it goes (P13).

    `atexit` covers the ordinary paths, and this covers the one that matters most: the shell
    closing our stdin because the window went away. A session that ends leaves nothing
    running -- and a session that is killed outright leaves the state file, which is how the
    next one finds the orphan.
    """
    log("ready")
    try:
        with contextlib.suppress(KeyboardInterrupt):
            serve(sys.stdin, sys.stdout)
    finally:
        # A session is the sidecar's lifetime (Q16): ending here ends the agent too, or a
        # closed window leaves somebody's agent running with nothing to talk to.
        close_everything_started_here()
        # And the terminals, for the same reason and one more: a shell's master pty cannot
        # be reopened from a pid, so one left running is a process nothing on this machine
        # can ever type into again -- along with whatever server was running inside it.
        close_everything_opened_here()
        # And any suite still running. Unlike a shell, nobody opened one on purpose to keep:
        # a test run with nothing left to report to is a process writing into a project for
        # no reader, and it holds whatever the tests themselves started.
        close_everything_observed_here()
        # And any export somebody pressed `Run` on: the same reasoning again, and one more --
        # a run is somebody's own code, which may have opened a port or a connection of its
        # own, and it is holding them for a panel that is no longer there to be shown them.
        close_everything_run_here()
        # And the compose stack, which is the only one of these that would otherwise survive
        # us: `up` is a client attached to containers the daemon owns, so ending the client
        # is not ending the stack. This runs `down`, because "closing the app stops what it
        # started" has to be true of the thing a person is most likely to leave running.
        close_everything_deployed_here()
        # And the watchers. They start nothing and hold nothing, but a thread per project
        # scanning a directory forever is still a thread per project, and this process is
        # about to stop having anybody to answer.
        stop_watching_everything()
    log("stdin closed, exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
