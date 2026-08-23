"""Snapshot and reconciliation: "is it still valid", not "did it change".

The first test is the one the design turns on. A user editing inside an editable body must
raise **nothing** — not a quiet warning, not an informational note. Their internals were
handed to them (§4), and a tool that comments on them has started supervising instead of
reconciling. Everything else here is the other half: an outline change must produce a
distinct, addressed divergence with whose fault it is.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from aibuilder_core.parser import parse_project
from aibuilder_core.reconcile import Fault, Resolution, reconcile
from aibuilder_core.snapshot import (
    SNAPSHOT_VERSION,
    load_snapshot,
    save_snapshot,
    snapshot_path,
    take_snapshot,
)

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def project(tmp_path: Path) -> Path:
    """A private copy of the example, already snapshotted."""
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)
    save_snapshot(take_snapshot(parse_project(root)), root)
    return root


def edit(root: Path, relative: str, before: str, after: str) -> None:
    path = root / relative
    source = path.read_text()
    assert before in source, f"{relative} does not contain the text to replace"
    path.write_text(source.replace(before, after))


def divergences(root: Path) -> list[object]:
    snapshot = load_snapshot(root)
    assert snapshot is not None
    return list(reconcile(snapshot, parse_project(root)))


def codes(root: Path) -> set[str]:
    return {divergence.code for divergence in divergences(root)}  # type: ignore[attr-defined]


# -- the silence that is promised -------------------------------------------------


def test_editing_inside_an_editable_body_raises_nothing(tmp_path: Path) -> None:
    """§8: the internals of an editable body belong to the user."""
    root = project(tmp_path)
    edit(
        root,
        "app/api/health.py",
        'return {"status": "ok"}',
        'state = "ok"\n    return {"status": state}',
    )

    assert divergences(root) == []


def test_an_unchanged_project_diverges_in_no_way(tmp_path: Path) -> None:
    assert divergences(project(tmp_path)) == []


def test_reformatting_a_generated_body_is_not_a_change(tmp_path: Path) -> None:
    """A watcher would fire here. Reconciliation must not: nothing about the code moved."""
    root = project(tmp_path)
    edit(
        root,
        "app/api/users.py",
        'router = APIRouter(prefix="/users", tags=["users"])',
        'router = APIRouter(\n        prefix="/users",\n        tags=["users"],\n    )',
    )

    assert divergences(root) == []


def test_adding_a_comment_to_a_generated_body_is_not_a_change(tmp_path: Path) -> None:
    root = project(tmp_path)
    edit(
        root,
        "app/main.py",
        '    app = FastAPI(title="Example Service")',
        '    # a note for whoever reads this next\n    app = FastAPI(title="Example Service")',
    )

    assert divergences(root) == []


# -- the three divergences the phase must tell apart ------------------------------


def test_breaking_a_locked_signature_is_a_contract_fault(tmp_path: Path) -> None:
    root = project(tmp_path)
    edit(
        root,
        "app/api/users.py",
        "def list_users(limit: int | None = None) -> list[User]:",
        "def list_users(limit: int | None = None, offset: int = 0) -> list[User]:",
    )

    broken = next(d for d in divergences(root) if d.code == "function.signature_broken")  # type: ignore[attr-defined]

    assert broken.fault == Fault.CONTRACT.value
    assert broken.resolutions == (Resolution.REPAIR.value,)
    # The reference carries the original contract, so the repair can restore it without
    # having to guess -- and without touching the body (§9 case 1).
    assert broken.reference == "(limit: int | None = None) -> list[User]"
    assert broken.location.file == "app/api/users.py"


def test_removing_a_carrier_decorator_is_a_generated_fault(tmp_path: Path) -> None:
    root = project(tmp_path)
    edit(
        root,
        "app/settings.py",
        '@node(id="api.settings", kind="fastapi.settings", title="Settings")\n',
        "",
    )

    gone = next(d for d in divergences(root) if d.code == "node.carrier_gone")  # type: ignore[attr-defined]

    assert gone.node == "api.settings"
    assert gone.fault == Fault.GENERATED.value
    assert set(gone.resolutions) == {Resolution.REVERT.value, Resolution.ACCEPT.value}


def test_touching_the_generated_zone_is_a_generated_fault(tmp_path: Path) -> None:
    root = project(tmp_path)
    edit(root, "app/main.py", 'title="Example Service"', 'title="Edited By Hand"')

    touched = next(d for d in divergences(root) if d.code == "function.generated_touched")  # type: ignore[attr-defined]

    assert touched.fault == Fault.GENERATED.value
    assert "app.main.create_app" in touched.message
    assert touched.location.file == "app/main.py"


def test_the_toolchain_never_offers_only_one_way_out_of_a_generated_edit(
    tmp_path: Path,
) -> None:
    """§9 case 2: a silent automaton kills trust in the graph, whichever way it leans."""
    root = project(tmp_path)
    edit(root, "app/main.py", 'title="Example Service"', 'title="Edited By Hand"')

    for divergence in divergences(root):
        if divergence.fault == Fault.GENERATED.value:  # type: ignore[attr-defined]
            assert set(divergence.resolutions) == {  # type: ignore[attr-defined]
                Resolution.REVERT.value,
                Resolution.ACCEPT.value,
            }


# -- the rest of the outline ------------------------------------------------------


def test_a_changed_knob_default_is_reported(tmp_path: Path) -> None:
    """The graph writes these itself, so the reference has to move with them (P6)."""
    root = project(tmp_path)
    edit(root, "app/settings.py", "] = 25", "] = 50")

    changed = next(d for d in divergences(root) if d.code == "knob.changed")  # type: ignore[attr-defined]

    assert "25" in changed.message and "50" in changed.message
    assert changed.reference == "25"


def test_a_new_node_is_reported_as_added(tmp_path: Path) -> None:
    root = project(tmp_path)
    path = root / "app/api/health.py"
    path.write_text(
        path.read_text()
        + textwrap.dedent(
            """

            @node(id="ready", kind="fastapi.route", title="Ready")
            @editable(signature_locked=True)
            def ready() -> dict[str, str]:
                return {"ready": "yes"}
            """
        )
    )

    assert "node.added" in codes(root)


def test_a_changed_contract_edge_is_reported(tmp_path: Path) -> None:
    root = project(tmp_path)
    edit(
        root,
        "app/api/users.py",
        "def list_users(limit: int | None = None) -> list[User]:",
        "def list_users(limit: int | None = None, offset: int = 0) -> list[User]:",
    )

    assert "edge.changed" in codes(root)


def test_changing_a_classification_is_reported(tmp_path: Path) -> None:
    """What the user is allowed to edit changed, which is never incidental."""
    root = project(tmp_path)
    edit(root, "app/main.py", "@generated()", "@editable()")
    edit(root, "app/main.py", "from bp import generated", "from bp import editable")

    assert "function.zone_changed" in codes(root)


# -- the reference itself ---------------------------------------------------------


def test_every_divergence_carries_an_address_and_a_way_out(tmp_path: Path) -> None:
    root = project(tmp_path)
    edit(root, "app/main.py", 'title="Example Service"', 'title="Edited By Hand"')
    edit(
        root,
        "app/api/users.py",
        "def list_users(limit: int | None = None) -> list[User]:",
        "def list_users(limit: int | None = None, offset: int = 0) -> list[User]:",
    )

    for divergence in divergences(root):
        assert divergence.location.file  # type: ignore[attr-defined]
        assert divergence.location.object  # type: ignore[attr-defined]
        assert divergence.rule  # type: ignore[attr-defined]
        assert divergence.repair  # type: ignore[attr-defined]
        assert divergence.resolutions  # type: ignore[attr-defined]


def test_the_snapshot_holds_no_editable_bodies(tmp_path: Path) -> None:
    """The material for the comparison §8 forbids must not exist at all."""
    root = project(tmp_path)
    stored = snapshot_path(root).read_text()

    # A line lifted from an editable body. If it ever appears in the reference, the
    # snapshot has started storing code and §8's promise is gone.
    assert "_USERS[: limit or settings.page_size]" not in stored
    snapshot = load_snapshot(root)
    assert snapshot is not None
    editable = [f for f in snapshot.functions if f.zone == "editable"]
    assert editable and all(function.body_digest is None for function in editable)


def test_the_snapshot_survives_a_round_trip(tmp_path: Path) -> None:
    root = project(tmp_path)
    original = take_snapshot(parse_project(root))

    assert load_snapshot(root) == original


def test_a_snapshot_from_another_version_is_treated_as_absent(tmp_path: Path) -> None:
    """A reference whose meaning has shifted produces confident, wrong divergences."""
    root = project(tmp_path)
    path = snapshot_path(root)
    path.write_text(path.read_text().replace(f'"version": {SNAPSHOT_VERSION}', '"version": 99'))

    assert load_snapshot(root) is None


def test_a_project_with_no_reference_is_not_an_error(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()

    assert load_snapshot(root) is None


# -- taking one ------------------------------------------------------------------


def test_a_snapshot_is_refused_while_the_gate_has_errors(tmp_path: Path) -> None:
    """A reference taken from broken code makes the breakage the baseline."""
    from aibuilder_core.api import take_project_snapshot

    root = tmp_path / "broken"
    shutil.copytree(Path(__file__).parent / "fixtures" / "mis-annotated", root)

    result = take_project_snapshot(root)

    assert result["taken"] is False
    assert result["refused"]
    assert not snapshot_path(root).exists()


def test_a_clean_project_gets_its_reference(tmp_path: Path) -> None:
    from aibuilder_core.api import take_project_snapshot

    root = tmp_path / "clean"
    shutil.copytree(EXAMPLE, root)

    result = take_project_snapshot(root)

    assert result["taken"] is True
    assert snapshot_path(root).exists()
