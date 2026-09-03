"""The knobs, and the first write path (Phase 3).

Half of this file is about the *diff*. That is not fussiness: the claim of the product is
that the code is the source of truth, and a panel that reformatted a file every time somebody
moved a control would make the person review a change they did not ask for. The second time
that happened they would stop using the panel and edit the file, and the panel would have
proven the opposite of what it exists to prove.

So the tests below check the whole file byte for byte after an edit, not just the field that
was edited — the comments, the ordering, the blank lines, the quote style of the string on
the next line.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from contract import validate, wire_form

from framestack_core.api import (
    EDITOR_SCHEMA,
    SETTINGS_SCHEMA,
    editor_open,
    settings_get,
    settings_put,
)
from framestack_core.editor import open_in_editor
from framestack_core.observe import read_observation, start_observation
from framestack_core.settings import Settings, read_settings, write_setting

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"


def project(tmp_path: Path) -> Path:
    """A writable copy. These tests edit settings; the reference is not theirs to edit."""
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


def field(settings: Settings, name: str) -> object:
    found = [one for one in settings.fields if one.name == name]
    assert found, f"no field {name!r} in {[one.name for one in settings.fields]}"
    return found[0]


def rewrite(root: Path, node: str, source: str) -> None:
    (root / node / "settings.py").write_text(source, encoding="utf-8")


# -- reading ------------------------------------------------------------------------------


def test_the_reference_declares_the_knobs_its_classes_declare(tmp_path: Path) -> None:
    settings = read_settings(project(tmp_path), "rag")

    assert settings.ok is True
    assert settings.class_name == "RagSettings"
    assert settings.path == "rag/settings.py"
    assert [one.name for one in settings.fields] == [
        "index_path",
        "chunk_size",
        "overlap",
        "top_k",
        "hybrid",
        "reranker",
    ]


def test_a_control_is_chosen_from_the_annotation_and_the_value_keeps_its_type(
    tmp_path: Path,
) -> None:
    """The value crosses the wire as the field's own type, not as text.

    A contract that flattened everything to a string would make the panel parse it back, and
    a panel parsing Python literals is a second implementation of the thing this module is.
    """
    root = project(tmp_path)
    settings = read_settings(root, "rag")

    assert (field(settings, "top_k").control, field(settings, "top_k").value) == ("integer", 4)  # type: ignore[attr-defined]
    assert (field(settings, "overlap").control, field(settings, "overlap").value) == (  # type: ignore[attr-defined]
        "number",
        0.15,
    )
    assert (field(settings, "hybrid").control, field(settings, "hybrid").value) == ("toggle", True)  # type: ignore[attr-defined]

    api = read_settings(root, "api")
    assert (field(api, "greeting").control, field(api, "greeting").value) == (  # type: ignore[attr-defined]
        "text",
        "framestack reference",
    )


def test_every_knob_says_where_it_is_written(tmp_path: Path) -> None:
    """What "open in editor" points at. A panel that could not do this would ask for faith."""
    root = project(tmp_path)
    settings = read_settings(root, "rag")
    lines = (root / "rag" / "settings.py").read_text(encoding="utf-8").splitlines()

    assert "top_k: int = 4" in lines[field(settings, "top_k").line - 1]  # type: ignore[attr-defined]


def test_a_literal_becomes_a_select_with_its_own_choices(tmp_path: Path) -> None:
    """The one control the reference does not exercise, so it is exercised on a real file."""
    root = project(tmp_path)
    rewrite(
        root,
        "rag",
        "from typing import Literal\n\n"
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n"
        '    scoring: Literal["overlap", "exact"] = "overlap"\n',
    )

    scoring = field(read_settings(root, "rag"), "scoring")

    assert scoring.control == "select"  # type: ignore[attr-defined]
    assert scoring.choices == ("overlap", "exact")  # type: ignore[attr-defined]
    assert scoring.value == "overlap"  # type: ignore[attr-defined]


def test_a_system_with_no_settings_is_an_ordinary_answer(tmp_path: Path) -> None:
    """Allowed and normal. A refusal here would make the commonest state look like a fault."""
    root = project(tmp_path)
    (root / "rag" / "settings.py").unlink()

    settings = read_settings(root, "rag")

    assert settings.ok is True
    assert settings.path == ""
    assert settings.fields == ()
    assert "no settings.py" in settings.detail


def test_two_settings_classes_are_refused_rather_than_chosen_between(tmp_path: Path) -> None:
    """Never guessed at. Picking the first would edit a different class than the one shown."""
    root = project(tmp_path)
    rewrite(
        root,
        "rag",
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n    top_k: int = 4\n\n\n"
        "class OtherSettings(BaseSettings):\n    top_k: int = 9\n",
    )

    settings = read_settings(root, "rag")

    assert settings.ok is False
    assert "more than one" in settings.detail


def test_a_default_built_by_a_call_is_shown_and_refused(tmp_path: Path) -> None:
    """Writing a literal over `Field(4, ge=1)` would delete a constraint the author put there."""
    root = project(tmp_path)
    rewrite(
        root,
        "rag",
        "from pydantic import Field\n"
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n"
        "    top_k: int = Field(4, ge=1)\n",
    )

    top_k = field(read_settings(root, "rag"), "top_k")

    assert top_k.control == "none"  # type: ignore[attr-defined]
    assert "not a plain value" in top_k.reason  # type: ignore[attr-defined]
    assert write_setting(root, "rag", "top_k", 8).ok is False


def test_a_type_with_no_control_is_shown_with_the_reason(tmp_path: Path) -> None:
    """Shown rather than hidden: a knob nobody can see is one nobody knows they have."""
    root = project(tmp_path)
    rewrite(
        root,
        "rag",
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n"
        "    top_k: int = 4\n"
        "    weights: list = []\n",
    )

    weights = field(read_settings(root, "rag"), "weights")

    assert weights.control == "none"  # type: ignore[attr-defined]
    assert weights.reason != ""  # type: ignore[attr-defined]


# -- writing ---------------------------------------------------------------------------------


def test_changing_top_k_changes_exactly_one_line(tmp_path: Path) -> None:
    """The acceptance criterion, checked as bytes rather than as a feeling.

    Everything the edit was not about — the docstring, the `from __future__` line, the four
    fields around it, the blank lines — comes back identical, because libcst rebuilds the
    file from the tree it parsed rather than rewriting it.
    """
    root = project(tmp_path)
    path = root / "rag" / "settings.py"
    before = path.read_text(encoding="utf-8").splitlines(keepends=True)

    answer = write_setting(root, "rag", "top_k", 8)

    assert answer.ok is True
    after = path.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(before) == len(after)
    differing = [
        index for index, pair in enumerate(zip(before, after, strict=True)) if pair[0] != pair[1]
    ]
    assert len(differing) == 1
    assert after[differing[0]].strip() == "top_k: int = 8"


def test_git_diff_after_the_edit_is_one_line(tmp_path: Path) -> None:
    """The same claim, asked of `git` rather than of us.

    Asked rather than computed, for the reason nothing here reads somebody else's format: the
    tool a person will actually check this with is the one that should answer it.
    """
    root = project(tmp_path)
    for line in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "before"],
    ):
        subprocess.run(["git", *line], cwd=root, check=True, capture_output=True)  # noqa: S603, S607

    write_setting(root, "rag", "top_k", 8)

    diff = subprocess.run(  # noqa: S603, S607
        ["git", "diff", "--unified=0"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    added = [one for one in diff.splitlines() if one.startswith("+") and not one.startswith("+++")]
    removed = [
        one for one in diff.splitlines() if one.startswith("-") and not one.startswith("---")
    ]

    assert added == ["+    top_k: int = 8"]
    assert removed == ["-    top_k: int = 4"]


def test_comments_and_ordering_around_the_edit_are_preserved(tmp_path: Path) -> None:
    """The thing a regular expression over the line would get right most of the time."""
    root = project(tmp_path)
    written = (
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n"
        "    # How much of a document goes in one chunk.\n"
        "    chunk_size: int = 500  # tuned by hand, do not lower\n\n"
        "    top_k: int = 4\n"
        "    greeting: str = 'single quoted on purpose'\n"
    )
    rewrite(root, "rag", written)

    write_setting(root, "rag", "top_k", 8)

    assert (root / "rag" / "settings.py").read_text(encoding="utf-8") == written.replace(
        "top_k: int = 4", "top_k: int = 8"
    )


def test_a_string_keeps_the_quote_style_it_was_written_in(tmp_path: Path) -> None:
    """A change the person did not ask for is a change that makes the diff untrustworthy."""
    root = project(tmp_path)
    rewrite(
        root,
        "rag",
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n    label: str = 'one'\n",
    )

    write_setting(root, "rag", "label", "two")

    assert "label: str = 'two'" in (root / "rag" / "settings.py").read_text(encoding="utf-8")


def test_every_control_writes_the_type_its_annotation_declares(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert write_setting(root, "rag", "overlap", 0.25).ok is True
    assert write_setting(root, "rag", "hybrid", False).ok is True
    assert write_setting(root, "api", "greeting", "hello").ok is True

    body = (root / "rag" / "settings.py").read_text(encoding="utf-8")
    assert "overlap: float = 0.25" in body
    assert "hybrid: bool = False" in body
    assert 'greeting: str = "hello"' in (root / "api" / "settings.py").read_text(encoding="utf-8")


def test_a_float_field_set_to_a_whole_number_stays_a_float(tmp_path: Path) -> None:
    """`overlap: float = 1` would be a type the author did not declare."""
    root = project(tmp_path)

    write_setting(root, "rag", "overlap", 1)

    assert "overlap: float = 1.0" in (root / "rag" / "settings.py").read_text(encoding="utf-8")


def test_a_value_of_the_wrong_type_is_refused_and_the_file_is_untouched(
    tmp_path: Path,
) -> None:
    """A refusal is a result. What must not happen is a file changed on the way to one."""
    root = project(tmp_path)
    path = root / "rag" / "settings.py"
    before = path.read_text(encoding="utf-8")

    answer = write_setting(root, "rag", "top_k", "eight")

    assert answer.ok is False
    assert "whole number" in answer.detail
    assert path.read_text(encoding="utf-8") == before


def test_a_select_refuses_a_value_that_is_not_one_of_its_choices(tmp_path: Path) -> None:
    root = project(tmp_path)
    rewrite(
        root,
        "rag",
        "from typing import Literal\n\n"
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n"
        '    scoring: Literal["overlap", "exact"] = "overlap"\n',
    )

    assert write_setting(root, "rag", "scoring", "fuzzy").ok is False
    assert write_setting(root, "rag", "scoring", "exact").ok is True


def test_setting_a_field_to_what_it_already_is_writes_nothing(tmp_path: Path) -> None:
    """A write that changes nothing still moves a timestamp, and something is always watching."""
    root = project(tmp_path)
    path = root / "rag" / "settings.py"
    stamp = path.stat().st_mtime_ns

    answer = write_setting(root, "rag", "top_k", 4)

    assert answer.ok is True
    assert path.stat().st_mtime_ns == stamp


def test_a_field_that_is_not_there_is_refused_by_name(tmp_path: Path) -> None:
    assert write_setting(project(tmp_path), "rag", "nonesuch", 1).ok is False


def test_a_system_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    root = project(tmp_path)

    assert read_settings(root, "nonesuch").ok is False
    assert write_setting(root, "nonesuch", "top_k", 1).ok is False


def test_the_panel_reads_the_file_back_rather_than_what_it_believes_it_wrote(
    tmp_path: Path,
) -> None:
    """What is drawn next has to be what is in the file."""
    root = project(tmp_path)

    after = write_setting(root, "rag", "top_k", 8)

    assert field(after, "top_k").value == 8  # type: ignore[attr-defined]
    assert field(read_settings(root, "rag"), "top_k").value == 8  # type: ignore[attr-defined]


# -- the payload -------------------------------------------------------------------------------


def test_both_verbs_match_the_declared_contract(tmp_path: Path) -> None:
    root = project(tmp_path)

    validate(wire_form(settings_get(root, "rag")), SETTINGS_SCHEMA)
    validate(wire_form(settings_get(root, "nonesuch")), SETTINGS_SCHEMA)
    validate(wire_form(settings_put(root, "rag", "top_k", 8)), SETTINGS_SCHEMA)
    validate(wire_form(settings_put(root, "rag", "top_k", "no")), SETTINGS_SCHEMA)


# -- the phase it has to keep working ------------------------------------------------------------


def test_editing_a_field_then_observing_keeps_the_node_green(tmp_path: Path) -> None:
    """The acceptance criterion that joins this phase to the last one.

    It is the real check on "byte-identical elsewhere": a write that broke the file would
    show up here as a suite that cannot run, and the node would go `skipped` rather than
    green. Nothing about the edit is allowed to cost evidence.
    """
    root = project(tmp_path)

    assert write_setting(root, "rag", "top_k", 8).ok is True

    started = start_observation(root)
    assert started.ok is True
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        answer = read_observation(root, 0)
        if not answer.running:
            break
        time.sleep(0.1)

    assert answer.observation is not None
    assert {one.node: one.verdict for one in answer.observation.verdicts}["rag"] == "green"


# -- open in editor ---------------------------------------------------------------------------


def test_a_path_outside_the_project_is_refused(tmp_path: Path) -> None:
    """This takes a path from a webview and hands it to another program."""
    root = project(tmp_path)

    assert open_in_editor(root, "../../etc/passwd").ok is False
    assert open_in_editor(root, "/etc/passwd").ok is False


def test_a_file_that_is_not_there_is_refused_by_name(tmp_path: Path) -> None:
    assert open_in_editor(project(tmp_path), "rag/nonesuch.py").ok is False


def test_opening_uses_the_editor_the_person_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`$EDITOR` wins over anything on the PATH: they already answered this question."""
    root = project(tmp_path)
    monkeypatch.setenv("FRAMESTACK_EDITOR", "true")

    answer = open_in_editor(root, "rag/settings.py", 12)

    assert answer.ok is True
    assert answer.editor == "true"


def test_the_editor_payload_matches_the_declared_contract(tmp_path: Path) -> None:
    validate(wire_form(editor_open(project(tmp_path), "rag/settings.py", 1)), EDITOR_SCHEMA)
