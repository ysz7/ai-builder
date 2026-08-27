"""A terminal the person types into (the sixth process of the P13 shape).

These start a real shell, because there is nothing to test otherwise: the whole claim is that
a pty behaves like a terminal -- a prompt appears, a command runs, the process group goes when
the tab does -- and none of that can be asserted against a fake. They are cheap: `$SHELL`
starting and being asked to echo something costs a fraction of a second.
"""

from __future__ import annotations

import os
import re
import signal
import time
from pathlib import Path

import pytest

from aibuilder_core.shell import (
    close_everything_opened_here,
    close_shell,
    list_shells,
    open_shell,
    read_shell,
    write_shell,
)


@pytest.fixture(autouse=True)
def _no_survivors() -> object:
    """No test may leave a shell running: they outlive the process that opened them."""
    yield
    close_everything_opened_here()


def until(project: Path, shell: str, wanted: str, seconds: float = 6.0) -> str:
    """Read until the shell has said something, or give up.

    Polled rather than slept on, for the reason everything else here is polled: how long a
    shell takes to print its prompt is a fact about somebody's machine, and a fixed sleep is
    either too short on theirs or wasted on ours.
    """
    seen = ""
    offset = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        answer = read_shell(project, shell, offset)
        offset = answer.offset
        seen += answer.output
        if wanted in seen:
            return seen
        time.sleep(0.05)
    return seen


def test_nothing_is_open_until_somebody_opens_one(tmp_path: Path) -> None:
    """P11, in the one place a panel would most like to be helpful."""
    assert list_shells(tmp_path).shells == ()


def test_a_shell_runs_what_is_typed_into_it(tmp_path: Path) -> None:
    """The whole claim, at its smallest: it is a terminal, and it answers.

    A pty and not a pipe is what makes this true of `python` and `git log` as well -- a shell
    handed a pipe decides it is not interactive and behaves like something being scripted.
    """
    opened = open_shell(tmp_path, "one")
    assert opened.ok is True

    write_shell(tmp_path, opened.shell, "echo from-the-shell\n")

    assert "from-the-shell" in until(tmp_path, opened.shell, "from-the-shell")


def test_it_starts_in_the_project(tmp_path: Path) -> None:
    """Where else would it be? Asserted because the alternative -- the sidecar's own cwd --
    is the builder's directory, and a terminal that opens there is one that edits us."""
    opened = open_shell(tmp_path)
    write_shell(tmp_path, opened.shell, "pwd\n")

    # `resolve` on both sides: macOS hands out /var, which is a link to /private/var.
    assert str(tmp_path.resolve()) in until(tmp_path, opened.shell, str(tmp_path.resolve()))


def test_what_is_typed_is_sent_verbatim(tmp_path: Path) -> None:
    """Not even a newline is added, and that is what makes ctrl-c expressible.

    A verb that appended one would make the interrupt byte impossible to send -- and the
    interrupt is the only way to stop what is running in there.
    """
    opened = open_shell(tmp_path)
    # Typed but not entered: nothing runs until the newline the caller sends. The command is
    # written so that what is typed and what it prints are **different strings** -- the pty
    # echoes the typing, so a command whose output repeats it proves nothing.
    write_shell(tmp_path, opened.shell, "printf 'ran-%s\\n' yes")
    time.sleep(0.5)
    early = read_shell(tmp_path, opened.shell, 0).output

    write_shell(tmp_path, opened.shell, "\n")
    later = until(tmp_path, opened.shell, "ran-yes")

    assert "ran-yes" not in early
    assert "ran-yes" in later


def test_output_is_polled_with_an_offset_the_caller_keeps(tmp_path: Path) -> None:
    """P13. The second read returns what happened since the first, not the whole log again."""
    opened = open_shell(tmp_path)
    until(tmp_path, opened.shell, "$")  # let the prompt land, whatever it looks like
    first = read_shell(tmp_path, opened.shell, 0)

    write_shell(tmp_path, opened.shell, "echo second\n")
    until(tmp_path, opened.shell, "second")
    second = read_shell(tmp_path, opened.shell, first.offset)

    assert second.offset >= first.offset
    assert "second" in second.output


def test_closing_a_terminal_takes_what_was_running_in_it(tmp_path: Path) -> None:
    """The **process group**, not the shell alone.

    A shell with a server in it is a shell whose child would outlive it, holding the port and
    printing into a log nobody is reading. Closing a tab has to mean closing what was in it.
    """
    opened = open_shell(tmp_path)
    # `child-$!` typed, `child-1234` printed: the pty echoes what is typed, so the marker has
    # to be one the typing cannot contain.
    write_shell(tmp_path, opened.shell, "sleep 60 & echo child-$!\n")
    printed = until(tmp_path, opened.shell, "child-1")

    found = re.search(r"child-(\d+)", printed)
    assert found, f"the shell did not report a pid: {printed!r}"
    child = int(found.group(1))

    close_shell(tmp_path, opened.shell)
    time.sleep(0.5)

    with pytest.raises(OSError):
        os.kill(child, 0)


def test_a_closed_terminal_is_gone_from_the_list(tmp_path: Path) -> None:
    opened = open_shell(tmp_path)
    assert len(list_shells(tmp_path).shells) == 1

    close_shell(tmp_path, opened.shell)

    assert list_shells(tmp_path).shells == ()


def test_typing_into_a_terminal_that_is_not_here_is_refused(tmp_path: Path) -> None:
    """A refusal is a result. And the project is checked, not only the id: a shell belongs to
    the project it was opened in, or one window could type into another's."""
    refused = write_shell(tmp_path, "nobody", "echo\n")

    assert refused.ok is False
    assert "no terminal here" in refused.detail


def test_a_terminal_that_exited_says_so_rather_than_pretending(tmp_path: Path) -> None:
    """A shell the person quit is not a shell that can be typed into, and the log says how it
    ended -- a transcript that simply stopped would leave them wondering."""
    opened = open_shell(tmp_path)
    write_shell(tmp_path, opened.shell, "exit\n")
    printed = until(tmp_path, opened.shell, "[the shell exited]")

    assert "[the shell exited]" in printed
    assert write_shell(tmp_path, opened.shell, "echo\n").ok is False
    assert read_shell(tmp_path, opened.shell, 0).running is False


def test_the_sidecar_takes_its_terminals_with_it(tmp_path: Path) -> None:
    """A shell is the sidecar's lifetime: its master pty cannot be reopened from a pid, so one
    left running is a process nothing on this machine could ever type into again."""
    opened = open_shell(tmp_path)
    pid = opened.shells[0]["pid"]

    close_everything_opened_here()
    time.sleep(0.4)

    assert list_shells(tmp_path).shells == ()
    with pytest.raises(OSError):
        os.kill(pid, signal.SIGCONT)
