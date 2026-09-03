"""`Deploy`: the compose stack, up and down again (Phase 5).

`docker` is stubbed in most of these, and that is deliberate rather than a shortcut. What is
under test is not whether Compose works -- it does, and it is not ours -- but the four things
this module is responsible for: that the compose file is never read here, that output is
polled with an offset the caller keeps, that a missing `docker` is an answer rather than a
crash, and that **stopping means `down`**. The last one is the one that would quietly become
false: killing the client detaches from containers the daemon still owns, and a local-first
tool that leaves a Postgres running after its window closes has broken the only promise it
makes about the machine it runs on.

The one test that uses the real `docker` asks it what the reference's stack is made of, and
skips itself when there is none. It brings nothing up: a test that pulled an image would be a
test that fails on an aeroplane.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from contract import validate, wire_form

from framestack_core.api import DEPLOY_SCHEMA, deploy_poll, deploy_status, deploy_up
from framestack_core.deploy import (
    COMPOSE_FILE,
    LOG_PATH,
    close_everything_deployed_here,
    read_deploy,
    start_deploy,
    stop_deploy,
)
from framestack_core.deploy import deploy_status as status

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `docker` that answers the three things this module asks it, and records `down`.

    `up` prints and then waits, which is what the real one does: the stack is running for as
    long as the client is attached to it.
    """
    binaries = tmp_path / "bin"
    binaries.mkdir(exist_ok=True)
    docker = binaries / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'case "$2" in\n'
        '  version) echo "9.9.9"; exit 0 ;;\n'
        "esac\n"
        'for word in "$@"; do\n'
        '  case "$word" in\n'
        '    --services) printf "api\\nworker\\n"; exit 0 ;;\n'
        '    up) echo "attaching to api, worker"; sleep 30; exit 0 ;;\n'
        '    down) echo "$@" >> "$FAKE_DOCKER_LOG"; exit 0 ;;\n'
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaries}:{tmp_path}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(tmp_path / "down.log"))
    return tmp_path / "down.log"


def wait_for_output(root: Path, deadline: float = 20.0) -> str:
    end = time.monotonic() + deadline
    text = ""
    while time.monotonic() < end:
        answer = read_deploy(root, len(text.encode()))
        text += answer.output
        if text.strip():
            return text
        time.sleep(0.05)
    return text


# -- refusals, each of them a result ---------------------------------------------------------


def test_a_project_with_no_compose_file_has_nothing_to_bring_up(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / COMPOSE_FILE).unlink()

    answer = start_deploy(root)

    assert not answer.ok
    assert COMPOSE_FILE in answer.detail


def test_a_machine_with_no_docker_says_so_before_anything_is_pressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The panel can explain the button rather than letting somebody discover it."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    answer = status(project(tmp_path))

    assert not answer.ok
    assert not answer.available
    assert "PATH" in answer.detail


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert not start_deploy(tmp_path / "nothing").ok
    assert not status(tmp_path / "nothing").ok


# -- what it asks, and what it refuses to read -------------------------------------------------


def test_the_services_are_asked_of_compose_rather_than_read_out_of_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole rule, as a test. `compose.yaml` here declares services that are not in the
    file at all, and the answer follows the program rather than the text -- which is what
    proves no YAML reader is involved."""
    root = project(tmp_path)
    fake_docker(tmp_path, monkeypatch)

    answer = status(root)

    assert answer.available
    assert answer.services == ("api", "worker")
    assert "postgres" in (root / COMPOSE_FILE).read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("docker") is None, reason="no docker on this machine")
def test_the_real_compose_reads_the_reference_s_own_services(tmp_path: Path) -> None:
    """Nothing is brought up. Asking a file what it says starts no container."""
    answer = status(project(tmp_path))

    if not answer.available:
        pytest.skip(answer.detail)
    assert set(answer.services) == {"api", "worker", "postgres"}


# -- the P13 shape ------------------------------------------------------------------------------


def test_the_log_is_polled_with_an_offset_the_caller_keeps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    fake_docker(tmp_path, monkeypatch)

    started = start_deploy(root)
    assert started.ok and started.running

    try:
        assert "attaching to api, worker" in wait_for_output(root)
        whole = read_deploy(root, 0)
        assert read_deploy(root, whole.offset).output == ""
        assert (root / LOG_PATH).is_file()
    finally:
        stop_deploy(root)


def test_a_second_press_does_not_start_a_second_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    fake_docker(tmp_path, monkeypatch)

    start_deploy(root)
    try:
        again = start_deploy(root)
        assert again.ok
        assert "already up" in again.detail
    finally:
        stop_deploy(root)


# -- stopping means stopped -----------------------------------------------------------------


def test_stopping_takes_the_containers_down_and_not_only_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The promise a local-first tool cannot afford to break.

    Killing `up` leaves the daemon holding everything, so `down` is what makes the word
    "stop" true. If this ever fails, closing the window leaves somebody's database running.
    """
    root = project(tmp_path)
    down = fake_docker(tmp_path, monkeypatch)

    start_deploy(root)
    answer = stop_deploy(root)

    assert answer.ok and not answer.running
    assert down.is_file()
    assert "down" in down.read_text(encoding="utf-8")
    assert not read_deploy(root, 0).running


def test_the_sidecar_takes_down_what_it_brought_up_on_the_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Closing the app stops what it started", as the thing that actually runs on exit."""
    root = project(tmp_path)
    down = fake_docker(tmp_path, monkeypatch)

    start_deploy(root)
    close_everything_deployed_here()

    assert "down" in down.read_text(encoding="utf-8")
    assert not read_deploy(root, 0).running


# -- the contract ------------------------------------------------------------------------------


def test_every_verb_matches_the_declared_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    fake_docker(tmp_path, monkeypatch)

    validate(wire_form(deploy_status(root)), DEPLOY_SCHEMA)
    validate(wire_form(deploy_up(root)), DEPLOY_SCHEMA)
    try:
        validate(wire_form(deploy_poll(root, 0)), DEPLOY_SCHEMA)
    finally:
        stop_deploy(root)

    # And a refusal, which is a result and has to be the same shape as one.
    validate(wire_form(deploy_status(tmp_path / "nothing")), DEPLOY_SCHEMA)
