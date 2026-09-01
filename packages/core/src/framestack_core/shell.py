"""A terminal the person types into, as a process this toolchain starts and talks to.

**This is not a verb on a node, and that distinction is the whole of why it is allowed.**
`run.*` calls one export the convention already requires, because a verb that ran an
arbitrary string would be a shell with a button on it -- a thing the graph makes claims about
without knowing what it did. Nothing here makes a claim about anything. A shell is somebody's
own shell, opened deliberately, typed into by hand; it colours no node, proves no check and
is not read by the parser. What it costs is a process, which is exactly what `agent.*`,
`observe.*`, `run.*` and `deploy.*` each cost already. It is also the way out of a corner the
buttons cannot reach, which is why it may run what `run.start` refuses.

So this is one instance of the P13 shape and it follows the same four rules:

* **Nothing is pushed.** Output is polled with an offset the caller keeps.
* **Nothing starts implicitly.** A shell exists because somebody opened one.
* **What we start, we can find again** -- within a limit stated below.
* A refusal is a result, never a protocol fault.

The one place it differs from the others, and it is stated rather than worked around: a
terminal has to be **written to**, and it is written to through a pty whose master end cannot
be reopened from a pid. So a shell is the **sidecar's** lifetime, exactly as a session is
(`session.py`) -- a sidecar that dies takes its shells with it. The process itself is put in
its own process group and killed on the way out rather than left behind.

**A pty and not a pipe.** A shell handed a pipe decides it is not interactive: no prompt, no
job control, and `python` or `git log` on the other end behaves like something being scripted.
The person asked for a terminal, and a terminal is what a pty means to every program that
looks.
"""

from __future__ import annotations

import contextlib
import errno
import os
import pty
import re
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "SHELLS_PATH",
    "ShellResult",
    "close_everything_opened_here",
    "close_shell",
    "list_shells",
    "open_shell",
    "read_shell",
    "resize_shell",
    "write_shell",
]

#: Where a shell's output is kept, one file per shell. Tooling state beside the run record.
SHELLS_PATH = Path(".framestack") / "shells"

#: How many shells one project may have open at once.
#:
#: A limit rather than none, because every one of these is a process holding a pty and the
#: only thing that closes them is a person or the sidecar exiting. Ten tabs is more than
#: anybody works with; a thousand opened by a loop in the interface is a machine on its knees.
LIMIT = 10

#: What the shell is told it is talking to.
#:
#: `dumb` on purpose: the panel draws text, not a screen. A shell that believes it has a
#: cursor to move sends escape sequences to move it, and what arrives is a transcript full of
#: instructions nobody is carrying out. What is left after this is still stripped on the way
#: out -- a program may ignore `TERM` and colour its output anyway -- but asking first means
#: there is far less to strip.
TERM = "dumb"

#: Escape sequences, removed on the way out rather than on the way in.
#:
#: On the way out because the log is what the shell actually wrote: turning it into something
#: else before storing it would make the record a rendering. This strips the two families
#: that survive `TERM=dumb` -- CSI (colour, cursor) and OSC (window titles, which some shells
#: set on every prompt) -- and leaves everything else, including the bell, alone.
_ESCAPES = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


@dataclass
class _Shell:
    """One open terminal. Held by the sidecar, because a pty master is not a pid."""

    identifier: str
    name: str
    project: str
    process: subprocess.Popen[bytes]
    #: The master end. Written to when somebody types; read by the pump below.
    master: int
    log: Path
    #: The thread copying the pty into the log. It ends when the shell does.
    pump: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def alive(self) -> bool:
        return self.process.poll() is None


#: Every shell this sidecar holds, keyed by its id. Ids are unique across projects, so one
#: map serves them all and `list_shells` filters by the project that asked.
_SHELLS: dict[str, _Shell] = {}


@dataclass(frozen=True)
class ShellResult:
    """The answer to every verb here. Refusals are results, never protocol faults."""

    ok: bool
    detail: str
    #: The shell acted on, where the verb had one.
    shell: str = ""
    running: bool = False
    #: What it printed since the offset that was asked for.
    output: str = ""
    #: Where the reader got to. Kept by the caller and handed back (P13).
    offset: int = 0
    #: Every shell open for this project, so a panel can draw its tabs from one answer.
    shells: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "shell": self.shell,
            "running": self.running,
            "output": self.output,
            "offset": self.offset,
            "shells": [dict(item) for item in self.shells],
        }


def _listing(project: Path) -> tuple[dict[str, Any], ...]:
    """The shells this project has open, oldest first -- which is the order they were made.

    Order matters here in a way it does not elsewhere: these are drawn as tabs, and tabs that
    reshuffle themselves when one of them exits are tabs nobody can aim at.
    """
    here = str(project)
    return tuple(
        {
            "id": shell.identifier,
            "name": shell.name,
            "running": shell.alive(),
            "pid": shell.process.pid,
        }
        for shell in _SHELLS.values()
        if shell.project == here
    )


def _log_for(project: Path, identifier: str) -> Path:
    return project / SHELLS_PATH / f"{identifier}.log"


def _pump(shell: _Shell) -> None:
    """Copy the pty into the log until the shell ends.

    A thread and not a poll: a pty has no "how much is there" to ask, only a read that waits.
    It appends bytes and interprets none of them -- what the shell wrote is what the log
    holds, and the only editing happens on the way back out to a caller.
    """
    while True:
        try:
            chunk = os.read(shell.master, 4096)
        except OSError as exc:
            # EIO is how a pty says the far end has gone. It is the normal end of a shell,
            # not a fault, and it must not reach anybody as one.
            if exc.errno not in (errno.EIO, errno.EBADF):
                chunk = b""
            break
        if not chunk:
            break
        with contextlib.suppress(OSError), shell.log.open("ab") as sink:
            sink.write(chunk)
    # The shell has ended. Said in the log rather than only in a status field, because a
    # person looking at the transcript is owed the last line of it.
    with contextlib.suppress(OSError), shell.log.open("ab") as sink:
        sink.write(b"\n[the shell exited]\n")


def open_shell(project: Path | str, name: str = "") -> ShellResult:
    """Open one terminal in the project's own directory. Never implicit (P11).

    The shell is **the person's own** -- `$SHELL`, as their terminal would start it -- rather
    than one chosen here. Their aliases, their prompt, their environment: a builder that
    quietly substituted `/bin/sh` would be a different machine from the one they know.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return ShellResult(False, "there is no project at that path")

    open_here = _listing(root)
    if len([item for item in open_here if item["running"]]) >= LIMIT:
        return ShellResult(
            False,
            f"{LIMIT} terminals are already open here -- close one before opening another",
            shells=open_here,
        )

    identifier = str(uuid.uuid4())
    log = _log_for(root, identifier)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"")

    program = os.environ.get("SHELL") or "/bin/sh"
    # A login shell, because that is what a terminal window starts: without it none of the
    # person's own setup is read, and the first command they try is the one that needs it.
    line = [program, "-l"] if os.path.basename(program) != "sh" else [program]

    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(  # noqa: S603 -- the program is the person's own $SHELL
            line,
            cwd=root,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            env={**os.environ, "TERM": TERM},
            close_fds=True,
        )
    except OSError as exc:
        os.close(master)
        os.close(slave)
        return ShellResult(False, f"a terminal could not be opened: {exc}")
    finally:
        # The child holds its own copy; keeping ours would mean the pty never reports the
        # far end closing, and the pump would wait for a shell that had already gone.
        with contextlib.suppress(OSError):
            os.close(slave)

    shell = _Shell(
        identifier=identifier,
        name=name.strip() or f"shell {len(open_here) + 1}",
        project=str(root),
        process=process,
        master=master,
        log=log,
    )
    shell.pump = threading.Thread(target=_pump, args=(shell,), daemon=True)
    shell.pump.start()
    _SHELLS[identifier] = shell

    return ShellResult(
        True,
        "terminal open",
        shell=identifier,
        running=True,
        shells=_listing(root),
    )


def write_shell(project: Path | str, shell: str, text: str) -> ShellResult:
    """Type into one terminal. **Nothing is added to what was typed.**

    Not even a newline: a person pressing enter is a `\\n` the caller sends, and a person
    pressing ctrl-c is a `\\x03` it sends instead. A verb that appended a newline would make
    the second of those impossible to express.
    """
    root = Path(project).resolve()
    held = _SHELLS.get(shell)
    if held is None or held.project != str(root):
        return ShellResult(False, "there is no terminal here by that name", shell=shell)
    if not held.alive():
        return ShellResult(
            False,
            "that terminal has exited -- open another",
            shell=shell,
            shells=_listing(root),
        )

    try:
        with held.lock:
            os.write(held.master, text.encode("utf-8"))
    except OSError as exc:
        return ShellResult(False, f"the terminal stopped listening: {exc}", shell=shell)
    return ShellResult(True, "", shell=shell, running=True)


def read_shell(project: Path | str, shell: str, offset: int = 0) -> ShellResult:
    """What the terminal has printed since `offset`. Polled, never pushed (P13).

    The offset counts **bytes of the log**, which is what the shell wrote, so it stays valid
    across a caller that reconnects. Escape sequences are removed here rather than stored
    stripped, because the log is a record and a record that had been edited on the way in
    would be a rendering instead.
    """
    root = Path(project).resolve()
    held = _SHELLS.get(shell)
    if held is None or held.project != str(root):
        return ShellResult(False, "there is no terminal here by that name", shell=shell)

    try:
        with held.log.open("rb") as handle:
            handle.seek(max(offset, 0))
            chunk = handle.read()
            here = handle.tell()
    except OSError as exc:
        return ShellResult(False, f"the terminal's output could not be read: {exc}", shell=shell)

    return ShellResult(
        True,
        "",
        shell=shell,
        running=held.alive(),
        output=_flatten(_ESCAPES.sub(b"", chunk).decode("utf-8", errors="replace")),
        offset=here,
    )


def _flatten(text: str) -> str:
    """A carriage return means "write over this line again", and here there is no screen.

    So the line is resolved the way a terminal would resolve it -- what was written last is
    what is left -- rather than passed on with the returns in it, which draws every zsh prompt
    twice and turns a progress bar into a hundred lines. It is done **on the way out**: the
    log keeps what the shell wrote, and this is the panel's version of it.
    """
    if "\r" not in text:
        return text
    return "\n".join(line.rsplit("\r", 1)[-1] for line in text.replace("\r\n", "\n").split("\n"))


def resize_shell(project: Path | str, shell: str, columns: int, rows: int) -> ShellResult:
    """Tell the shell how wide its window is.

    Asked rather than assumed, in the other direction: programs that wrap their own output --
    `git log`, `ps`, anything drawing a table -- read this and nothing else. A pty opened and
    never resized reports 80x24 to every one of them, and the person's wide panel gets
    somebody else's line breaks.
    """
    root = Path(project).resolve()
    held = _SHELLS.get(shell)
    if held is None or held.project != str(root):
        return ShellResult(False, "there is no terminal here by that name", shell=shell)
    if not held.alive():
        return ShellResult(False, "that terminal has exited", shell=shell)

    # Imported here rather than at the top: these are the only two lines in this module that
    # are Unix-shaped in a way `pty` itself is not, and they are cheap to keep contained.
    import fcntl
    import struct
    import termios

    with contextlib.suppress(OSError), held.lock:
        fcntl.ioctl(
            held.master,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", max(rows, 1), max(columns, 1), 0, 0),
        )
    return ShellResult(True, "", shell=shell, running=True)


def close_shell(project: Path | str, shell: str) -> ShellResult:
    """Close one terminal, and everything it started.

    The **process group** is signalled rather than the shell alone: a shell with a server
    running in it is a shell whose child would outlive it, holding the port and printing into
    a log nobody is reading any more. Closing a tab has to mean closing what was in it.
    """
    root = Path(project).resolve()
    held = _SHELLS.get(shell)
    if held is None or held.project != str(root):
        return ShellResult(False, "there is no terminal here by that name", shell=shell)

    _end(held)
    _SHELLS.pop(shell, None)
    with contextlib.suppress(OSError):
        held.log.unlink()
    return ShellResult(True, "terminal closed", shell=shell, shells=_listing(root))


def list_shells(project: Path | str) -> ShellResult:
    """The terminals open for this project. A read: it opens nothing (P11)."""
    root = Path(project).resolve()
    return ShellResult(True, "", shells=_listing(root))


def _end(shell: _Shell) -> None:
    """Stop one shell's process group, then let go of the pty."""
    if shell.alive():
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(os.getpgid(shell.process.pid), signal.SIGHUP)
        try:
            shell.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError, ProcessLookupError):
                os.killpg(os.getpgid(shell.process.pid), signal.SIGKILL)
    with contextlib.suppress(OSError):
        os.close(shell.master)


def close_everything_opened_here() -> None:
    """Close every shell this sidecar opened. Called when it exits, for the reason `_end` is.

    A terminal is the sidecar's lifetime, so a sidecar going away with shells still running
    would leave somebody's processes on their machine with nothing left that knows about them.
    """
    for shell in list(_SHELLS.values()):
        _end(shell)
        with contextlib.suppress(OSError):
            shell.log.unlink()
    _SHELLS.clear()
