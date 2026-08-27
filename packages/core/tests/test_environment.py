"""The project's environment: whose interpreter, whose services, and who started them.

Three claims carry this phase, and the third is the one that would be easiest to lose:

1. **The checks run in the project's interpreter** when it has one, and say so when they do
   not. The evidence a node carries is only as good as the environment it was gathered in.
2. **A failing test in an environment the project asked for and did not get is
   unattributable.** It becomes `unproven` with the reason, never a red node — and the
   asymmetry is deliberate: a test that *passed* still proves what it proved.
3. **Nothing is ever started implicitly.** Observing a graph does not bring a container up.
   Because of that there is nothing to leak, and the test that guards it watches the actual
   docker commands rather than trusting the code to have meant well.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from aibuilder_core.api import environment_status, read_graph, services_start, services_stop
from aibuilder_core.environment import (
    Environment,
    compose_file,
    describe_environment,
    project_interpreter,
)
from aibuilder_core.observe import probe_script, run_observations
from aibuilder_core.parser import parse_project
from aibuilder_core.verdict import Verdict

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
CACHED = EXAMPLES / "service-with-cache"
PLAIN = EXAMPLES / "fastapi-service"


def docker_daemon_is_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


needs_docker = pytest.mark.skipif(
    not docker_daemon_is_up(), reason="no docker daemon on this machine"
)


def copy(tmp_path: Path, source: Path) -> Path:
    root = tmp_path / source.name
    shutil.copytree(source, root, ignore=shutil.ignore_patterns("__pycache__", ".aibuilder"))
    return root


# -- the interpreter --------------------------------------------------------------


def test_a_project_with_its_own_virtual_environment_gets_it(tmp_path: Path) -> None:
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()

    resolved, origin = project_interpreter(tmp_path)

    assert resolved == str(interpreter)
    assert origin == "project"


def test_a_project_without_one_gets_ours_and_is_told_so(tmp_path: Path) -> None:
    """Falling back is allowed. Falling back silently was the actual problem."""
    resolved, origin = project_interpreter(tmp_path)

    assert resolved == sys.executable
    assert origin == "toolchain"


def test_an_explicit_interpreter_wins(tmp_path: Path) -> None:
    resolved, origin = project_interpreter(tmp_path, python="/usr/bin/python3")

    assert (resolved, origin) == ("/usr/bin/python3", "explicit")


def test_the_checks_really_run_in_that_interpreter(tmp_path: Path) -> None:
    """The proof is a project whose own environment cannot import what ours can.

    A bare virtual environment has no FastAPI in it, so a run that lands there fails on the
    import -- which is exactly what proves the run did not happen in our environment, where
    FastAPI is installed and everything would have passed.
    """
    root = copy(tmp_path, PLAIN)
    subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True, timeout=120)

    assert project_interpreter(root)[1] == "project"
    run = run_observations(parse_project(root), root)

    assert run.environment is not None and run.environment.interpreter_origin == "project"
    assert all("did not import" in observation.detail for observation in run.observations.values())


def test_the_probe_is_a_file_another_interpreter_can_be_handed() -> None:
    """It is spawned by path, never imported -- which is what makes P11 possible at all."""
    assert probe_script().is_file()
    assert probe_script().name == "probe.py"


# -- the services -----------------------------------------------------------------


def test_the_compose_file_is_found_by_dockers_own_precedence(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").touch()
    assert compose_file(tmp_path) is not None
    assert Path(str(compose_file(tmp_path))).name == "docker-compose.yml"

    (tmp_path / "compose.yaml").touch()
    assert Path(str(compose_file(tmp_path))).name == "compose.yaml"


def test_a_project_with_no_services_is_a_complete_environment() -> None:
    environment = describe_environment(PLAIN)

    assert environment.compose_file is None
    assert environment.services == ()
    assert environment.incomplete is None


def test_declared_services_that_are_not_running_make_it_incomplete() -> None:
    environment = describe_environment(CACHED)

    assert environment.compose_file is not None
    assert environment.incomplete is not None


def test_docker_being_absent_is_reported_rather_than_guessed_around(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not knowing is a third answer. It is not "no services" and it is not "all fine"."""
    monkeypatch.setattr("aibuilder_core.environment.shutil.which", lambda _: None)

    environment = describe_environment(CACHED)

    assert environment.docker_unavailable == "docker is not installed"
    assert environment.incomplete is not None
    assert "could not be checked" in environment.incomplete


# -- what the evidence does about it ----------------------------------------------


def test_a_failure_in_a_missing_environment_is_unattributable() -> None:
    """The phase's central asymmetry, on a project built to show it.

    `/health` answers without the cache and its test passes; `/counter` cannot, and its test
    fails. One node keeps its evidence, the other loses its claim -- and neither is red,
    because nothing here says the code is wrong.
    """
    graph = parse_project(CACHED)
    run = run_observations(graph, CACHED)

    from aibuilder_core.gate import check_graph

    verdicts = check_graph(graph, observations=run.observations).verdicts

    assert verdicts["health"] == Verdict.GREEN.value
    assert verdicts["counter"] == Verdict.UNPROVEN.value
    assert (
        "nothing answers" in run.skipped["counter"]
        or "could not be checked" in (run.skipped["counter"])
    )
    assert "cannot be attributed" in run.skipped["counter"]


def test_observing_never_starts_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    """The promise the whole phase is shaped around, watched at the docker command itself.

    Not "the code does not call up" -- what docker was actually asked to do. A convenience
    added three layers away would still show up here.
    """
    asked: list[tuple[str, ...]] = []
    original = describe_environment

    def record(project: Path, *arguments: str, timeout: int = 20) -> tuple[int, str, str]:
        asked.append(arguments)
        return 1, "", "not run in this test"

    monkeypatch.setattr("aibuilder_core.environment._docker", record)
    run_observations(parse_project(CACHED), CACHED)

    assert asked, "docker was not consulted at all, so this test proves nothing"
    assert all("up" not in arguments and "down" not in arguments for arguments in asked)
    assert original is describe_environment


def test_the_environment_travels_with_the_evidence() -> None:
    observed = read_graph(CACHED, observe=True)
    plain = read_graph(CACHED)

    assert observed["environment"]["compose_file"] is not None
    # A read that did not observe describes no environment: asking docker is not something
    # a plain question should do.
    assert plain["environment"] is None


def test_the_status_method_reads_and_changes_nothing() -> None:
    before = environment_status(CACHED)["environment"]
    after = environment_status(CACHED)["environment"]

    assert before == after
    assert before["interpreter_origin"] in {"project", "toolchain", "explicit"}


# -- the two methods that do change something -------------------------------------


def test_starting_services_a_project_does_not_declare_is_refused(tmp_path: Path) -> None:
    result = services_start(tmp_path)

    assert result["ok"] is False
    assert "no compose file" in result["detail"]


@needs_docker
def test_the_loop_closes_once_the_services_are_up(tmp_path: Path) -> None:
    """The other half of the phase, and it only runs where there is a daemon to run it.

    On a machine without docker this is skipped rather than failed -- the same rule the
    toolchain itself follows about the environments it finds.
    """
    root = copy(tmp_path, CACHED)

    started = services_start(root)
    assert started["ok"] is True, started["detail"]

    try:
        graph = parse_project(root)
        run = run_observations(graph, root)

        from aibuilder_core.gate import check_graph

        verdicts = check_graph(graph, observations=run.observations).verdicts
        assert run.environment is not None and run.environment.incomplete is None
        assert verdicts["counter"] == Verdict.GREEN.value
        assert set(verdicts.values()) == {Verdict.GREEN.value}
    finally:
        stopped = services_stop(root)
        assert stopped["ok"] is True, stopped["detail"]


def test_an_environment_describes_itself_as_data() -> None:
    payload: dict[str, Any] = Environment(
        interpreter="/x", interpreter_origin="toolchain"
    ).as_dict()

    assert payload["services"] == []
    assert payload["incomplete"] is None


# -- readiness, without a daemon to produce it ------------------------------------


def compose_declares(
    monkeypatch: pytest.MonkeyPatch,
    services: dict[str, Any],
    running: tuple[str, ...] = (),
) -> None:
    """Feed the reader exactly what docker would have said -- about the file, and about itself.

    The daemon-dependent path is one skipped test on a laptop, so what it depends on is
    pinned here instead: an unproven code path is not made proven by being hard to reach.

    `running` is the second answer: `docker compose ps` naming the containers that are up,
    which is a different question from what the file declares and from what answers on a port.
    """

    def answer(project: Path, *arguments: str, timeout: int = 20) -> tuple[int, str, str]:
        if "config" in arguments:
            return 0, json.dumps({"services": services}), ""
        if "ps" in arguments:
            lines = [json.dumps({"Service": name, "State": "running"}) for name in running]
            return 0, "\n".join(lines), ""
        return 0, "", ""

    monkeypatch.setattr("aibuilder_core.environment._docker", answer)


# -- running is docker's answer, and it is not reachability (Q24) -----------------


def test_up_is_what_docker_says_not_what_a_port_says(monkeypatch: pytest.MonkeyPatch) -> None:
    """The complaint that produced this: "I started docker and the button still says Up".

    Their container was running and nothing on this side could connect to it, so by
    reachability nothing had happened. What a button reflects has to be the question the
    button asked -- `env.up` starts containers, so containers being up is what says it worked.
    """
    # A port nothing is listening on, asked of the OS rather than picked: a number written
    # here is a number somebody's own redis is eventually running on, and the test would
    # then pass for a reason that has nothing to do with what it is testing.
    silent = free_port()
    compose_declares(
        monkeypatch,
        {"cache": {"ports": [{"published": str(silent)}]}},
        running=("cache",),
    )

    environment = describe_environment(CACHED)

    assert environment.up is True
    assert environment.services[0].running is True
    # And the other claim is untouched: nothing answered, so it is still not reachable.
    assert environment.services[0].reachable is False
    assert environment.incomplete is not None


def test_a_container_that_is_not_up_is_not_up(monkeypatch: pytest.MonkeyPatch) -> None:
    compose_declares(monkeypatch, {"cache": {"ports": [{"published": str(free_port())}]}})

    environment = describe_environment(CACHED)

    assert environment.up is False
    assert environment.services[0].running is False


def test_docker_answering_in_a_list_is_read_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One object per line in current versions, a list in older ones. Both are docker's own
    answer about its own state -- neither is somebody's file that we are parsing."""

    def answer(project: Path, *arguments: str, timeout: int = 20) -> tuple[int, str, str]:
        if "config" in arguments:
            return 0, json.dumps({"services": {"cache": {}}}), ""
        if "ps" in arguments:
            return 0, json.dumps([{"Service": "cache", "State": "running"}]), ""
        return 0, "", ""

    monkeypatch.setattr("aibuilder_core.environment._docker", answer)

    assert describe_environment(CACHED).up is True


def free_port() -> int:
    """A port nothing is on, asked of the OS. Bound and released, so it is free by the time
    anything looks -- which is what "nothing answers here" needs to mean."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def listening_port() -> Any:
    """A real socket to connect to. Readiness is a connection, so the test makes one."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    return server


def test_a_service_whose_port_answers_is_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    server = listening_port()
    try:
        port = server.getsockname()[1]
        compose_declares(monkeypatch, {"cache": {"ports": [{"published": str(port)}]}})

        environment = describe_environment(CACHED)

        assert environment.services[0].reachable is True
        assert environment.incomplete is None
    finally:
        server.close()


def test_a_service_whose_port_does_not_answer_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deliberately the whole check: no status field, no version of docker to keep up with.

    This is also what "running but still starting" now costs -- nothing. A database that has
    not finished booting does not answer, and an environment that says it is ready would be
    handing a node a red badge for a boot.
    """
    server = listening_port()
    port = server.getsockname()[1]
    server.close()  # nothing listens there any more
    compose_declares(monkeypatch, {"cache": {"ports": [{"published": str(port)}]}})

    environment = describe_environment(CACHED)

    assert environment.services_missing == ("cache",)
    assert environment.incomplete is not None


def test_a_service_that_publishes_nothing_is_not_claimed_either_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing on this side of the compose network can reach it, so there is no claim."""
    compose_declares(monkeypatch, {"worker": {}})

    environment = describe_environment(CACHED)

    assert environment.services[0].ports == ()
    assert environment.services_missing == ()
    assert environment.incomplete is None


def test_a_port_is_read_whichever_way_compose_spelled_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = listening_port()
    try:
        port = server.getsockname()[1]
        compose_declares(
            monkeypatch, {"cache": {"ports": [{"published": f"127.0.0.1:{port}:6379"}]}}
        )

        assert describe_environment(CACHED).services[0].ports == (port,)
    finally:
        server.close()


def test_a_configuration_that_cannot_be_read_is_said_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(project: Path, *arguments: str, timeout: int = 20) -> tuple[int, str, str]:
        return 0, "not json", ""

    monkeypatch.setattr("aibuilder_core.environment._docker", answer)

    environment = describe_environment(CACHED)

    assert environment.docker_unavailable is not None
    assert environment.incomplete is not None


# -- P12's acceptance: the loop on a project with a database ----------------------


@needs_docker
def test_the_loop_closes_on_a_project_with_a_database(tmp_path: Path) -> None:
    """A database, a vector store, and the compose file that declares them (P12).

    Every kind of node this project has is proven differently: the database by opening its
    connection, the vector store by the project's own tests, the routes by those same tests,
    and the compose file by its services answering where they publish. The stripped copy is
    then put through exactly the same checks, because none of that may depend on `bp`.
    """
    from aibuilder_core.project import read_project
    from aibuilder_core.strip import strip_project

    root = copy(tmp_path, EXAMPLES / "service-with-db")

    started = services_start(root)
    assert started["ok"] is True, started["detail"]

    try:
        from aibuilder_core.gate import check_graph

        graph = read_project(root)
        run = run_observations(graph, root)
        verdicts = check_graph(graph, observations=run.observations).verdicts

        assert run.environment is not None and run.environment.incomplete is None
        assert verdicts["db"] == Verdict.GREEN.value
        assert verdicts["vectors"] == Verdict.GREEN.value
        assert verdicts["compose.yaml"] == Verdict.GREEN.value
        assert Verdict.BROKEN.value not in verdicts.values()

        stripped = tmp_path / "stripped"
        strip_project(root, stripped)
        without_markup = run_observations(graph, stripped)

        assert {node: run.passed for node, run in without_markup.observations.items()} == {
            node: run.passed for node, run in run.observations.items()
        }
    finally:
        stopped = services_stop(root)
        assert stopped["ok"] is True, stopped["detail"]


# -- calling a service on the port it publishes (Q24) -----------------------------


def test_calling_a_service_the_project_never_declared_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal is a result, and it names what there is instead of failing silently."""
    from aibuilder_core.runner import call_service

    compose_declares(monkeypatch, {"cache": {}})

    refused = call_service(CACHED, "api")

    assert refused.ok is False
    assert "declares no service 'api'" in refused.detail
    assert "cache" in refused.detail


def test_a_service_that_publishes_nothing_cannot_be_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a failure of the call: nothing on this side of the compose network can reach it,
    so there is no address to fail to reach."""
    from aibuilder_core.runner import call_service

    compose_declares(monkeypatch, {"worker": {}})

    refused = call_service(CACHED, "worker")

    assert refused.ok is False
    assert "publishes no port" in refused.detail


def test_a_port_the_service_does_not_publish_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The port is docker's answer, not a number this side may pick. Guessing 8000 because
    it is usually 8000 would be inventing the address of somebody else's program."""
    from aibuilder_core.runner import call_service

    compose_declares(monkeypatch, {"api": {"ports": [{"published": "8080"}]}})

    refused = call_service(CACHED, "api", port=9999)

    assert refused.ok is False
    assert "does not publish 9999" in refused.detail


def test_a_service_that_is_not_up_says_so_in_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two facts in one sentence, because the second explains the first: nothing answered,
    and its container is not running."""
    from aibuilder_core.runner import call_service

    compose_declares(monkeypatch, {"api": {"ports": [{"published": str(free_port())}]}})

    refused = call_service(CACHED, "api")

    assert refused.ok is False
    assert "its container is not running" in refused.detail


def test_calling_something_that_does_not_speak_http_is_an_answer_about_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """redis, postgres and a queue all accept the connection and then say something that is
    not a response. That is an answer about the service -- it is up, and this is not how you
    talk to it -- and saying so is more use than a stack trace about a disconnected remote."""
    import threading

    from aibuilder_core.runner import call_service

    server = listening_port()

    def accept_and_hang_up() -> None:
        # What redis does to an HTTP request, near enough: the connection is accepted and
        # then it is not an HTTP conversation. A socket that merely listens would time out
        # instead, which is the other branch and a different sentence.
        with contextlib.suppress(OSError):
            connection, _ = server.accept()
            connection.close()

    listener = threading.Thread(target=accept_and_hang_up, daemon=True)
    listener.start()
    try:
        port = server.getsockname()[1]
        compose_declares(
            monkeypatch,
            {"cache": {"ports": [{"published": str(port)}]}},
            running=("cache",),
        )

        answer = call_service(CACHED, "cache")
    finally:
        server.close()

    assert answer.ok is False
    assert "did not answer in HTTP" in answer.detail
