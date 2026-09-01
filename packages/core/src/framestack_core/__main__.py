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


def log(message: str) -> None:
    """stderr only. stdout is the wire; a stray print there corrupts the stream."""
    print(f"[core] {message}", file=sys.stderr, flush=True)


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

    try:
        return encode_result(request.id, dispatch(request.method, request.params, request.id))
    except ProtocolError as exc:
        return encode_error(request.id, exc.code, exc.message)
    except Exception as exc:  # a handler bug must not take the core down
        log(f"handler {request.method!r} raised: {exc!r}")
        return encode_error(request.id, "handler_error", f"{type(exc).__name__}: {exc}")


def serve(stdin: TextIO, stdout: TextIO) -> None:
    for line in stdin:
        response = handle_line(line)
        if response is None:
            continue
        stdout.write(response + "\n")
        stdout.flush()


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
    log("stdin closed, exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
