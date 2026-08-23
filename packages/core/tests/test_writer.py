"""Two-way writes: the graph edits code through the syntax tree.

The load-bearing test is the round trip with a byte-identical remainder. An edit that
reformatted the file around the value it changed would still "work" — the graph would show
the right number — while making every diff unreadable and every merge a conflict. Writing
through the tree rather than through text is what buys the difference, and this is where
it is proven rather than assumed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import libcst as cst

from aibuilder_core.parser import parse_project
from aibuilder_core.reconcile import reconcile
from aibuilder_core.snapshot import load_snapshot, save_snapshot, take_snapshot
from aibuilder_core.writer import WriteResult, set_knob, set_node_title

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root)
    save_snapshot(take_snapshot(parse_project(root)), root)
    return root


def knob(root: Path, node_id: str, name: str) -> object:
    node = parse_project(root).node(node_id)
    assert node is not None
    return next(k for k in node.knobs if k.name == name)


def files(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): path.read_text() for path in sorted(root.rglob("*.py"))}


# -- the round trip ---------------------------------------------------------------


def test_a_knob_written_comes_back_out_of_the_parser(tmp_path: Path) -> None:
    root = project(tmp_path)

    result = set_knob(root, "api.settings", "page_size", 50)

    assert result.written is True
    assert knob(root, "api.settings", "page_size").default == "50"  # type: ignore[attr-defined]


def test_everything_but_the_edited_line_is_byte_identical(tmp_path: Path) -> None:
    """The acceptance test for P6."""
    root = project(tmp_path)
    before = files(root)

    set_knob(root, "api.settings", "page_size", 50)

    after = files(root)
    assert set(before) == set(after)

    for name in before:
        if name == "app/settings.py":
            continue
        assert before[name] == after[name], f"{name} was touched and should not have been"

    changed = [
        (old, new)
        for old, new in zip(
            before["app/settings.py"].splitlines(),
            after["app/settings.py"].splitlines(),
            strict=True,
        )
        if old != new
    ]
    assert len(changed) == 1
    assert changed[0][0].endswith("= 25")
    assert changed[0][1].endswith("= 50")


def test_a_string_knob_keeps_the_quote_style_already_in_the_file(tmp_path: Path) -> None:
    """A diff about one value must not also be a diff about quoting."""
    root = project(tmp_path)

    set_knob(root, "api.settings", "log_level", "debug")

    assert '= "debug"' in (root / "app/settings.py").read_text()


def test_a_list_knob_can_be_written(tmp_path: Path) -> None:
    root = project(tmp_path)

    set_knob(root, "api.settings", "cors_origins", ["https://a.test", "https://b.test"])

    assert knob(root, "api.settings", "cors_origins").default == (  # type: ignore[attr-defined]
        '["https://a.test", "https://b.test"]'
    )


def test_comments_and_docstrings_around_the_edit_survive(tmp_path: Path) -> None:
    root = project(tmp_path)

    set_knob(root, "api.settings", "request_timeout_s", 45)

    source = (root / "app/settings.py").read_text()
    assert "Every field here is a knob" in source
    assert 'Param(min=1, max=120, label="Request timeout (s)")' in source


# -- the node's own declaration ---------------------------------------------------


def test_a_node_can_be_renamed_through_its_decorator(tmp_path: Path) -> None:
    root = project(tmp_path)

    result = set_node_title(root, "health", "Liveness")

    assert result.written is True
    assert parse_project(root).node("health").title == "Liveness"  # type: ignore[union-attr]


def test_a_group_node_can_be_renamed_through_its_declaration(tmp_path: Path) -> None:
    root = project(tmp_path)

    set_node_title(root, "api", "Public API")

    assert parse_project(root).node("api").title == "Public API"  # type: ignore[union-attr]


def test_a_node_with_no_title_gets_one(tmp_path: Path) -> None:
    """A keyword that is absent has to be added, or an unnamed node is unrenamable."""
    root = project(tmp_path)
    path = root / "app/api/health.py"
    path.write_text(path.read_text().replace(', title="Health"', ""))
    assert parse_project(root).node("health").title is None  # type: ignore[union-attr]

    set_node_title(root, "health", "Health check")

    assert parse_project(root).node("health").title == "Health check"  # type: ignore[union-attr]


# -- what the writer refuses ------------------------------------------------------


def test_a_value_above_the_declared_maximum_is_refused(tmp_path: Path) -> None:
    """The declaration is the graph's promise about that value (§5.5)."""
    root = project(tmp_path)
    before = files(root)

    result = set_knob(root, "api.settings", "page_size", 500)

    assert result.written is False
    assert "maximum" in (result.refused or "")
    assert files(root) == before


def test_a_value_outside_the_declared_choices_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)

    result = set_knob(root, "api.settings", "log_level", "trace")

    assert result.written is False
    assert "choices" in (result.refused or "")


def test_a_value_of_the_wrong_type_is_refused(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert set_knob(root, "api.settings", "page_size", "many").written is False
    # bool is an int in Python; writing True into a slider is never what was meant.
    assert set_knob(root, "api.settings", "page_size", True).written is False


def test_an_unknown_node_or_knob_is_refused_by_name(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert "no node" in (set_knob(root, "nope", "page_size", 1).refused or "")
    assert "no knob" in (set_knob(root, "api.settings", "nope", 1).refused or "")


# -- the write and the reference --------------------------------------------------


def test_a_successful_write_moves_the_reference_with_it(tmp_path: Path) -> None:
    """Otherwise the graph's own edit shows up as a divergence next time §8 asks."""
    root = project(tmp_path)

    set_knob(root, "api.settings", "page_size", 50)

    snapshot = load_snapshot(root)
    assert snapshot is not None
    assert reconcile(snapshot, parse_project(root)) == ()


def test_a_refused_write_leaves_the_reference_alone(tmp_path: Path) -> None:
    root = project(tmp_path)
    before = load_snapshot(root)

    set_knob(root, "api.settings", "page_size", 500)

    assert load_snapshot(root) == before


def test_a_write_that_would_break_the_gate_is_undone(tmp_path: Path) -> None:
    """A defensive path: the graph made this edit, so it does not get to leave wreckage.

    No public write can trigger it today -- every one of them validates first -- so it is
    exercised through a transformer that deliberately breaks the project. The repairs in
    P7 edit far more than a literal, and this is the net under them.
    """
    from aibuilder_core.writer import _apply

    root = project(tmp_path)
    before = (root / "app/api/health.py").read_text()

    class _RemoveTheCarrier(cst.CSTTransformer):
        changed = True

        def leave_Decorator(
            self, original: cst.Decorator, updated: cst.Decorator
        ) -> cst.Decorator | cst.RemovalSentinel:
            call = updated.decorator
            func = call.func if isinstance(call, cst.Call) else call
            if isinstance(func, cst.Name) and func.value == "node":
                return cst.RemoveFromParent()
            return updated

    result: WriteResult = _apply(
        root, parse_project(root), "app/api/health.py", _RemoveTheCarrier(), "not found"
    )

    assert result.written is False
    assert result.diagnostics
    assert (root / "app/api/health.py").read_text() == before
