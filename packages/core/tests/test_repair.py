"""The repair system, and the choice it refuses to make.

§9's two cases differ in who is entitled to decide. Case 1 has one right answer — the
signature was locked, so putting it back is what "locked" meant — and the toolchain does
it, keeping the user's body. Case 2 has two non-equivalent answers, and the tool takes
neither: the test that `apply_repair` cannot be called without a resolution is the phase's
named acceptance criterion, and it is the one that must never be softened for convenience.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from framestack_core.parser import parse_project
from framestack_core.reconcile import reconcile
from framestack_core.repair import apply_repair, list_repairs
from framestack_core.snapshot import load_snapshot, save_snapshot, take_snapshot

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)
    save_snapshot(take_snapshot(parse_project(root)), root)
    return root


def edit(root: Path, relative: str, before: str, after: str) -> None:
    path = root / relative
    source = path.read_text()
    assert before in source, f"{relative} does not contain the text to replace"
    path.write_text(source.replace(before, after))


def break_the_contract(root: Path) -> None:
    """A user edits an editable body and changes the locked signature while they are in it."""
    edit(
        root,
        "app/api/users.py",
        "def list_users(limit: int | None = None) -> list[User]:",
        "def list_users(limit: int | None = None, verbose: bool = False) -> list[User]:",
    )
    edit(
        root,
        "app/api/users.py",
        "return _USERS[: limit or settings.page_size]",
        "page = _USERS[: limit or settings.page_size]\n    return page",
    )


def touch_the_generated_zone(root: Path) -> None:
    edit(root, "app/main.py", 'title="Example Service"', 'title="Edited By Hand"')


def divergences(root: Path) -> tuple[object, ...]:
    snapshot = load_snapshot(root)
    assert snapshot is not None
    return reconcile(snapshot, parse_project(root))


# -- case 1: the editable zone broke its contract ---------------------------------


def test_the_contract_is_restored_without_discarding_the_body(tmp_path: Path) -> None:
    """§9 case 1. The signature is the graph's; the body is the user's."""
    root = project(tmp_path)
    break_the_contract(root)

    apply_repair(
        root,
        code="function.signature_broken",
        target="list_users",
        resolution="repair",
        observe=False,
    )

    source = (root / "app/api/users.py").read_text()
    assert "def list_users(limit: int | None = None) -> list[User]:" in source
    assert "page = _USERS[: limit or settings.page_size]" in source
    assert "return page" in source


def test_the_restored_contract_ends_the_divergence(tmp_path: Path) -> None:
    root = project(tmp_path)
    break_the_contract(root)

    apply_repair(
        root,
        code="function.signature_broken",
        target="list_users",
        resolution="repair",
        observe=False,
    )

    assert divergences(root) == ()


def test_a_repair_that_leaves_the_node_broken_does_not_move_the_reference(
    tmp_path: Path,
) -> None:
    """I-5, at the point it is most tempting to skip: the repair "worked", so surely...

    Restoring a signature can leave a body referring to a parameter that no longer exists.
    The contract is right and the node still does not work, so the reference stays where it
    was and the caller is told which node is failing.
    """
    root = project(tmp_path)
    edit(
        root,
        "app/api/users.py",
        "def list_users(limit: int | None = None) -> list[User]:",
        "def list_users(limit: int | None = None, offset: int = 0) -> list[User]:",
    )
    edit(
        root,
        "app/api/users.py",
        "return _USERS[: limit or settings.page_size]",
        "return _USERS[offset:][: limit or settings.page_size]",
    )
    before = load_snapshot(root)

    result = apply_repair(
        root, code="function.signature_broken", target="list_users", resolution="repair"
    )

    assert result.applied is True
    assert result.snapshot_updated is False
    assert result.unproven == ("users.list",)
    assert load_snapshot(root) == before


# -- case 2: the generated zone was touched ---------------------------------------


def test_a_generated_divergence_cannot_be_resolved_without_a_choice(tmp_path: Path) -> None:
    """The phase's named acceptance test: the toolchain does not decide this one.

    Not a convention and not a code review rule -- the argument is required, so there is
    no call that resolves a generated-zone divergence while leaving the decision implicit.
    """
    root = project(tmp_path)
    touch_the_generated_zone(root)

    with pytest.raises(TypeError):
        apply_repair(root, code="function.generated_touched", target="create_app")  # type: ignore[call-arg]


def test_an_invented_resolution_is_refused_and_the_real_ones_named(tmp_path: Path) -> None:
    root = project(tmp_path)
    touch_the_generated_zone(root)

    result = apply_repair(
        root, code="function.generated_touched", target="create_app", resolution="auto"
    )

    assert result.applied is False
    assert "revert" in (result.refused or "") and "accept" in (result.refused or "")


def test_both_ways_out_are_always_offered(tmp_path: Path) -> None:
    """Offering one would be the silent choice §9 forbids, dressed as a recommendation."""
    root = project(tmp_path)
    touch_the_generated_zone(root)

    generated = [r for r in list_repairs(root) if r["fault"] == "generated"]

    assert generated
    for repair in generated:
        assert set(repair["resolutions"]) == {"revert", "accept"}


def test_reverting_restores_the_generated_body(tmp_path: Path) -> None:
    root = project(tmp_path)
    original = (root / "app/main.py").read_text()
    touch_the_generated_zone(root)

    result = apply_repair(
        root, code="function.generated_touched", target="create_app", resolution="revert"
    )

    assert result.applied and result.snapshot_updated
    assert (root / "app/main.py").read_text() == original
    assert divergences(root) == ()


def test_accepting_keeps_the_edit_and_moves_the_reference(tmp_path: Path) -> None:
    root = project(tmp_path)
    touch_the_generated_zone(root)
    edited = (root / "app/main.py").read_text()

    result = apply_repair(
        root, code="function.generated_touched", target="create_app", resolution="accept"
    )

    assert result.applied and result.snapshot_updated
    assert (root / "app/main.py").read_text() == edited  # the user's edit survives
    assert divergences(root) == ()


# -- what goes to the agent instead -----------------------------------------------


def test_a_divergence_with_no_mechanical_repair_says_so(tmp_path: Path) -> None:
    """A mechanical edit the tool cannot make correctly is worse than an instruction."""
    root = project(tmp_path)
    edit(
        root,
        "app/settings.py",
        '@node(id="api.settings", kind="fastapi.settings", title="Settings")\n',
        "",
    )

    result = apply_repair(
        root, code="node.carrier_gone", target="api.settings", resolution="revert"
    )

    assert result.applied is False
    assert "no mechanical repair" in (result.refused or "")


def test_the_request_carries_everything_a_repair_needs(tmp_path: Path) -> None:
    """§9: what, where, which rule -- and what must survive the fix."""
    root = project(tmp_path)
    break_the_contract(root)

    request = next(
        r["request"] for r in list_repairs(root) if r["code"] == "function.signature_broken"
    )

    assert "app/api/users.py" in request
    assert "list_users" in request
    assert "§5.2" in request
    assert "(limit: int | None = None) -> list[User]" in request
    assert "do not discard the body" in request


def test_a_generated_request_tells_the_agent_not_to_choose(tmp_path: Path) -> None:
    root = project(tmp_path)
    touch_the_generated_zone(root)

    request = next(
        r["request"] for r in list_repairs(root) if r["code"] == "function.generated_touched"
    )

    assert "the user does" in request


# -- refusals ---------------------------------------------------------------------


def test_repairing_without_a_reference_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    shutil.copytree(EXAMPLE, root)

    result = apply_repair(
        root, code="function.generated_touched", target="create_app", resolution="revert"
    )

    assert result.applied is False
    assert "no reference" in (result.refused or "")


def test_repairing_something_that_did_not_diverge_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)

    result = apply_repair(
        root, code="function.generated_touched", target="create_app", resolution="revert"
    )

    assert result.applied is False
    assert "no function.generated_touched divergence" in (result.refused or "")


def test_nothing_diverged_means_nothing_to_repair(tmp_path: Path) -> None:
    assert list_repairs(project(tmp_path)) == []
