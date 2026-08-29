"""Planning and inserting a blueprint that carries code (P20, Q28, Q30).

The claims worth holding here are not about the copy -- copying files is not hard -- but
about the rules the copy is wrapped in: that an insert cannot happen without a plan, that a
collision refuses instead of merging, that nothing is executed, that nothing is recorded
about where the files came from, and that the result is not green until something runs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from framestack_core.blueprint import insert_blueprint, plan_blueprint
from framestack_core.catalog import all_blueprints, bundled_catalog, list_blueprints
from framestack_core.gate import check_graph
from framestack_core.parser import parse_project

BUNDLED = [entry.id for entry in all_blueprints() if entry.carries_code]


@pytest.fixture(autouse=True)
def _no_ambient_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """A named catalog is never picked up from the environment a test happens to run in."""
    monkeypatch.delenv("FRAMESTACK_BLUEPRINTS", raising=False)


# -- the bundled catalog ---------------------------------------------------------------


def test_the_application_ships_a_catalog() -> None:
    """Q28's first source. Without it the only catalog is one most people have not got."""
    assert bundled_catalog() is not None
    assert BUNDLED


def test_a_bundled_entry_says_it_is_bundled() -> None:
    """`origin` is what decides whether a client asks first, so it is not inferred."""
    assert {entry.origin for entry in all_blueprints()} == {"bundled"}


def test_listing_the_named_catalog_still_means_the_named_one(tmp_path: Path) -> None:
    """`list_blueprints` is what "input B is unavailable here" is asked with (§3).

    P20 added a second source; it must not have quietly changed what the first question
    means, or a project with no catalog configured would stop being able to say so.
    """
    assert list_blueprints() == []
    assert list_blueprints(tmp_path) == []


# -- planning --------------------------------------------------------------------------


@pytest.mark.parametrize("blueprint", BUNDLED)
def test_every_bundled_entry_plans_into_an_empty_project(blueprint: str, tmp_path: Path) -> None:
    plan = plan_blueprint(tmp_path, blueprint)

    assert plan.refused is None
    assert plan.files
    assert plan.collisions == ()
    assert plan.identity


def test_planning_writes_nothing(tmp_path: Path) -> None:
    """A plan is a read. It is the whole basis for showing somebody a diff first."""
    plan_blueprint(tmp_path, "rag-pipeline")

    assert list(tmp_path.iterdir()) == []


def test_a_plan_names_the_third_party_modules_the_entry_imports() -> None:
    """The summary Q28.4 owes a reader: facts, never a verdict, and never the stdlib."""
    plan = plan_blueprint("/nonexistent-project", "rag-pipeline")

    assert "langchain_core" in plan.imports
    assert "typing" not in plan.imports


def test_an_unknown_entry_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    assert plan_blueprint(tmp_path, "not-a-blueprint").refused is not None


# -- inserting -------------------------------------------------------------------------


def _insert(project: Path, blueprint: str = "rag-pipeline") -> tuple[object, list[str]]:
    plan = plan_blueprint(project, blueprint)
    result = insert_blueprint(project, blueprint, plan=plan.identity)
    return result, list(result.files)


def test_an_insert_produces_code_and_the_parser_draws_it(tmp_path: Path) -> None:
    """I-1 through a gesture: the graph is whatever the parser now says about the files."""
    result, files = _insert(tmp_path)

    assert result.inserted  # type: ignore[attr-defined]
    assert "rag/pipeline.py" in files
    assert {node.id for node in parse_project(tmp_path).nodes} >= {"rag", "rag.chunking"}


def test_the_gate_accepts_what_was_inserted(tmp_path: Path) -> None:
    _insert(tmp_path)

    assert list(check_graph(parse_project(tmp_path)).errors) == []


def test_the_inserted_node_is_not_green(tmp_path: Path) -> None:
    """**I-5 has no back door.** A template that shipped its own verdict is the lie every
    flow-document builder tells; this one proves itself by a run like everything else."""
    _insert(tmp_path)

    verdicts = check_graph(parse_project(tmp_path)).verdicts

    assert set(verdicts.values()) == {"unproven"}


def test_an_insert_without_the_plan_s_identity_is_refused(tmp_path: Path) -> None:
    """The required keyword is checked, not ceremonial: it is the content itself."""
    result = insert_blueprint(tmp_path, "rag-pipeline", plan="not-the-plan")

    assert not result.inserted
    assert result.refused is not None
    assert list(tmp_path.iterdir()) == []


def test_an_entry_edited_after_the_plan_no_longer_matches_it(tmp_path: Path) -> None:
    """What the identity buys: nothing can be written that was not what was described."""
    stale = plan_blueprint(tmp_path, "rag-pipeline").identity

    assert insert_blueprint(tmp_path, "langgraph-agent", plan=stale).inserted is False


def test_a_collision_refuses_the_whole_insert_and_names_it(tmp_path: Path) -> None:
    """Never a merge. Merging somebody's project with a template is the operation this
    codebase has consistently refused to do silently."""
    (tmp_path / "rag").mkdir()
    (tmp_path / "rag" / "chunking.py").write_text("# mine\n", encoding="utf-8")

    plan = plan_blueprint(tmp_path, "rag-pipeline")
    result = insert_blueprint(tmp_path, "rag-pipeline", plan=plan.identity)

    assert plan.collisions == ("rag/chunking.py",)
    assert not result.inserted
    assert "rag/chunking.py" in (result.refused or "")
    # And the file that was in the way is untouched.
    assert (tmp_path / "rag" / "chunking.py").read_text(encoding="utf-8") == "# mine\n"


def test_inserting_twice_collides_with_itself(tmp_path: Path) -> None:
    """The second insert is a collision like any other -- there is no "already installed"
    state to consult, because nothing was recorded (Q28.6)."""
    _insert(tmp_path)
    plan = plan_blueprint(tmp_path, "rag-pipeline")

    assert plan.collisions
    assert not insert_blueprint(tmp_path, "rag-pipeline", plan=plan.identity).inserted


def test_nothing_records_where_the_files_came_from(tmp_path: Path) -> None:
    """No manifest, so upstream drift cannot exist -- there is no link along which it could
    happen. What records the change is the git diff (Q28.6, I-1)."""
    _insert(tmp_path)

    written = {path.name for path in tmp_path.rglob("*") if path.is_file()}

    assert not {name for name in written if "blueprint" in name.lower()}
    assert not (tmp_path / ".framestack" / "blueprints.json").exists()


def test_an_entry_may_not_write_outside_the_project(tmp_path: Path) -> None:
    """Containment, checked at plan time so nothing is half-written when it is discovered."""
    from framestack_core.blueprint import _containment_problem

    assert _containment_problem(tmp_path, "../escape.py") is not None
    assert _containment_problem(tmp_path, "/etc/passwd") is not None
    assert _containment_problem(tmp_path, ".framestack/run.json") is not None
    assert _containment_problem(tmp_path, "rag/pipeline.py") is None
