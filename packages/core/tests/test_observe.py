"""The observable checks: acceptance condition 2, and the second half of I-5.

The tests that carry the phase are the ones about what the runner refuses to do. A check
that cannot run must report `skipped`, never `passed`; a project that will not import must
come back as failure with the reason; and a node that satisfies the parser perfectly while
returning a 500 must be red, for the observable reason and not for a parse reason.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from aibuilder_core.gate import check_graph
from aibuilder_core.observe import build_plan, run_observations
from aibuilder_core.parser import parse_project
from aibuilder_core.verdict import Verdict

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
    observations, skipped, verdicts = observe(EXAMPLE)

    assert all(observation.passed for observation in observations.values())  # type: ignore[union-attr]
    assert verdicts["api"] == Verdict.GREEN.value
    assert verdicts["health"] == Verdict.GREEN.value
    # The POST route cannot be called without inventing a body, so it stays unproven --
    # which is the honest answer, not a passing one.
    assert verdicts["users.create"] == Verdict.UNPROVEN.value
    assert "users.create" in skipped


def test_a_router_check_proves_its_routes_are_mounted() -> None:
    observations, _, _ = observe(EXAMPLE)
    router = observations["users"]

    assert router.passed is True  # type: ignore[union-attr]
    assert router.check == "http.router_mounts"  # type: ignore[union-attr]


# -- what the runner must never do ------------------------------------------------


def test_a_check_that_cannot_run_is_skipped_not_passed(tmp_path: Path) -> None:
    """The erosion I-5 exists against would enter here, as a convenience."""
    _, skipped, verdicts = observe(EXAMPLE)

    assert skipped["users.create"]
    assert verdicts["users.create"] != Verdict.GREEN.value


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
