"""The observable checks: acceptance condition 2, and the second half of I-5.

The tests that carry the phase are the ones about what the runner refuses to do. A check
that cannot run must report `skipped`, never `passed`; a project that will not import must
come back as failure with the reason; and a node that satisfies the parser perfectly while
returning a 500 must be red, for the observable reason and not for a parse reason.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from framestack_core.gate import check_graph
from framestack_core.observe import build_plan, run_observations
from framestack_core.parser import parse_project
from framestack_core.verdict import Verdict

FIXTURES = Path(__file__).parent / "fixtures"
BROKEN_RUNTIME = FIXTURES / "broken-runtime"
EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def observe(project: Path) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    graph = parse_project(project)
    run = run_observations(graph, project)
    verdicts = check_graph(graph, observations=run.observations).verdicts
    return dict(run.observations), dict(run.skipped), verdicts


def write_project(root: Path, files: dict[str, str]) -> Path:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return root


# -- the phase's acceptance criterion ---------------------------------------------


def test_a_project_that_parses_perfectly_can_still_be_red() -> None:
    """P4's whole point: parseability is not the criterion (I-5)."""
    graph = parse_project(BROKEN_RUNTIME)
    assert check_graph(graph).diagnostics == ()  # the static gate has nothing to say

    observations, _, verdicts = observe(BROKEN_RUNTIME)

    assert verdicts["boom"] == Verdict.BROKEN.value
    assert verdicts["healthy"] == Verdict.GREEN.value


def test_the_reason_names_the_observable_check_not_the_parse() -> None:
    observations, _, _ = observe(BROKEN_RUNTIME)
    failure = observations["boom"]

    assert failure.check == "http.route_answers"  # type: ignore[union-attr]
    assert "500" in failure.detail  # type: ignore[union-attr]


# -- the good example -------------------------------------------------------------


def test_the_example_service_proves_itself() -> None:
    """Every node green, and the unreached band empty -- the P9 measurement (Q7).

    `users.create` is the one that matters: no direct call can prove a POST without
    inventing a request body, and the project's own test creates a user with a name a
    person chose. That is the difference between evidence and a manufactured pass.
    """
    observations, skipped, verdicts = observe(EXAMPLE)

    assert all(observation.passed for observation in observations.values())  # type: ignore[union-attr]
    assert set(verdicts.values()) == {Verdict.GREEN.value}
    assert skipped == {}
    assert observations["users.create"].check == "tests.exercised"  # type: ignore[union-attr]


def test_a_router_check_proves_its_routes_are_mounted() -> None:
    observations, _, _ = observe(EXAMPLE)
    router = observations["users"]

    assert router.passed is True  # type: ignore[union-attr]
    assert router.check == "http.router_mounts"  # type: ignore[union-attr]


def copy_example(tmp_path: Path) -> Path:
    """The example service, somewhere it can be broken on purpose."""
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def without_tests(tmp_path: Path) -> Path:
    """The same service as a project that never wrote a test."""
    root = copy_example(tmp_path)
    shutil.rmtree(root / "tests")
    return root


# -- the observed run (Q7): the project's own tests ------------------------------


def test_a_node_no_test_reaches_falls_back_to_its_direct_check() -> None:
    """Two sources of evidence, and the fallback is not second-class -- just narrower.

    `users_router` runs at import time, when the application is assembled, and never
    inside a test. Import-time execution is deliberately not counted as exercised: the
    claim "a test ran this" has to stay true.
    """
    observations, _, verdicts = observe(EXAMPLE)
    router = observations["users"]

    assert router.check == "http.router_mounts"  # type: ignore[union-attr]
    assert verdicts["users"] == Verdict.GREEN.value


def test_a_failing_test_reddens_the_node_it_exercised(tmp_path: Path) -> None:
    """Test evidence outranks a direct call, including when it is the worse news.

    The route still answers 200 here, so the direct check would pass it. The project's own
    test says the answer is wrong, and the project is the authority on that.
    """
    root = copy_example(tmp_path)
    health = root / "app" / "api" / "health.py"
    health.write_text(health.read_text().replace('{"status": "ok"}', '{"status": "nope"}'))

    observations, _, verdicts = observe(root)

    assert observations["health"].check == "tests.exercised"  # type: ignore[union-attr]
    assert observations["health"].passed is False  # type: ignore[union-attr]
    assert "test_health_reports_ok" in observations["health"].detail  # type: ignore[union-attr]
    assert verdicts["health"] == Verdict.BROKEN.value


def test_a_node_the_failing_test_never_touched_stays_green(tmp_path: Path) -> None:
    """A failing suite is not a blanket verdict. Only what it ran is what it judged."""
    root = copy_example(tmp_path)
    health = root / "app" / "api" / "health.py"
    health.write_text(health.read_text().replace('{"status": "ok"}', '{"status": "nope"}'))

    _, _, verdicts = observe(root)

    assert verdicts["health"] == Verdict.BROKEN.value
    assert verdicts["users.create"] == Verdict.GREEN.value


def test_a_suite_that_cannot_run_falls_back_instead_of_reddening_nodes(tmp_path: Path) -> None:
    """A broken test suite is not a broken application, and must not be reported as one."""
    root = copy_example(tmp_path)
    (root / "tests" / "test_api.py").write_text("this is not python(\n")

    observations, skipped, verdicts = observe(root)

    assert observations["health"].check == "http.route_answers"  # type: ignore[union-attr]
    assert verdicts["health"] == Verdict.GREEN.value
    # And the node the suite would have proven is unproven with the suite as the reason.
    assert "pytest exit" in skipped["users.create"]


def test_a_project_with_no_tests_says_so_rather_than_going_quiet(tmp_path: Path) -> None:
    _, skipped, _ = observe(without_tests(tmp_path))

    assert "no test suite" in skipped["users.create"]


# -- what the runner must never do ------------------------------------------------


def test_a_check_that_cannot_run_is_skipped_not_passed(tmp_path: Path) -> None:
    """The erosion I-5 exists against would enter here, as a convenience.

    Without the suite, the POST route is exactly what it was before P9: a node nothing can
    prove without inventing input, and therefore unproven.
    """
    _, skipped, verdicts = observe(without_tests(tmp_path))

    assert skipped["users.create"]
    assert "no test" in skipped["users.create"] or "no test suite" in skipped["users.create"]
    assert verdicts["users.create"] == Verdict.UNPROVEN.value


def test_a_route_that_is_declared_but_not_mounted_fails(tmp_path: Path) -> None:
    """Markup can claim a route the application never registered. That is not green."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/routes.py": """
                from bp import editable, node

                @node(id="ghost", kind="fastapi.route")
                @editable()
                def ghost() -> dict[str, str]:
                    return {}
            """,
            "app/main.py": """
                from bp import generated
                from fastapi import FastAPI

                @generated()
                def create_app() -> FastAPI:
                    return FastAPI()

                app = create_app()
            """,
            "app/__node__.py": """
                from bp import group_node

                from app.routes import ghost

                service = group_node(id="api", kind="fastapi.service", members=[ghost])
            """,
        },
    )

    observations, _, verdicts = observe(root)

    assert observations["ghost"].passed is False  # type: ignore[union-attr]
    assert "not mounted" in observations["ghost"].detail  # type: ignore[union-attr]
    assert verdicts["ghost"] == Verdict.BROKEN.value


def test_a_project_that_will_not_import_fails_with_the_reason(tmp_path: Path) -> None:
    """Import failure is a finding about the project, not a crash of the runner."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/routes.py": """
                from bp import editable, node

                import a_module_that_does_not_exist

                @node(id="route", kind="fastapi.route")
                @editable()
                def route() -> None:
                    pass
            """,
            "app/__node__.py": """
                from bp import group_node

                from app.routes import route

                service = group_node(id="api", kind="fastapi.service", members=[route])
            """,
        },
    )

    observations, _, verdicts = observe(root)

    assert observations["route"].passed is False  # type: ignore[union-attr]
    assert "a_module_that_does_not_exist" in observations["route"].detail  # type: ignore[union-attr]
    assert verdicts["route"] == Verdict.BROKEN.value


def test_a_check_that_raises_becomes_a_finding_not_an_exception(tmp_path: Path) -> None:
    """A settings object that cannot be constructed is red, and the runner survives."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/settings.py": """
                from bp import node

                @node(id="settings", kind="fastapi.settings")
                class Settings:
                    def __init__(self) -> None:
                        raise ValueError("no configuration available")
            """,
            "app/__node__.py": """
                from bp import group_node

                from app.settings import Settings

                service = group_node(id="api", kind="fastapi.service", members=[Settings])
            """,
        },
    )

    observations, _, verdicts = observe(root)

    assert observations["settings"].passed is False  # type: ignore[union-attr]
    assert "ValueError" in observations["settings"].detail  # type: ignore[union-attr]


def test_a_hanging_project_is_a_failing_project(tmp_path: Path) -> None:
    """A timeout has to come back as a verdict; a runner that waits forever has no answer."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/routes.py": """
                import time

                from bp import editable, node

                time.sleep(30)

                @node(id="route", kind="fastapi.route")
                @editable()
                def route() -> None:
                    pass
            """,
            "app/__node__.py": """
                from bp import group_node

                from app.routes import route

                service = group_node(id="api", kind="fastapi.service", members=[route])
            """,
        },
    )

    run = run_observations(parse_project(root), root, timeout_s=2)

    assert run.observations["route"].passed is False
    assert "within 2s" in run.observations["route"].detail or ""


# -- the plan ---------------------------------------------------------------------


def test_only_modules_the_graph_knows_about_are_imported(tmp_path: Path) -> None:
    """Running a stranger's code is limited to the part they annotated for us."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/routes.py": """
                from bp import editable, node

                @node(id="route", kind="fastapi.route")
                @editable()
                def route() -> None:
                    pass
            """,
            "scripts/dangerous.py": "raise SystemExit('this must never be imported')\n",
        },
    )

    plan = build_plan(parse_project(root), root)

    assert "app.routes" in plan["modules"]  # type: ignore[operator]
    assert "scripts.dangerous" not in plan["modules"]  # type: ignore[operator]


def test_a_node_whose_kind_is_unregistered_gets_no_check(tmp_path: Path) -> None:
    """It has no observable check to run, and the gate already reported the kind."""
    root = write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/routes.py": """
                from bp import node

                @node(id="route", kind="fastapi.teleport")
                def route() -> None:
                    pass
            """,
        },
    )

    plan = build_plan(parse_project(root), root)

    assert plan["nodes"] == []


def test_a_degraded_check_says_what_it_was_written_against(tmp_path: Path) -> None:
    """The note travels with the result that is missing, not with the graph as a whole.

    A node that could not be proven and a library that is not the one the check was written
    against are two facts the reader has to put together; printing them apart makes that
    the reader's job.
    """
    from framestack_core.observe import build_plan
    from framestack_core.probe import run_plan

    root = without_tests(tmp_path)
    plan = build_plan(parse_project(root), root)
    plan["technologies"] = {
        "fastapi": {"distribution": "fastapi", "verified": "0.0.1-never-released"}
    }

    results = {result["node"]: result for result in run_plan(plan)}

    assert results["users.create"]["status"] == "skipped"
    assert "written against fastapi 0.0.1-never-released" in results["users.create"]["detail"]
    assert "written against" not in results["health"]["detail"]
