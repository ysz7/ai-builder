"""Proof of I-2 in its mechanical form.

The unit tests fix what the strip removes and, just as importantly, what it leaves alone.
The last test is the one the invariant actually rests on: the example service and its
stripped copy answer identically, proven by running both, not by reading them.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aibuilder_core.strip import GROUP_MANIFEST, strip_project, strip_source

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"


def strip(source: str) -> str:
    return strip_source(textwrap.dedent(source).lstrip())


def test_node_and_editable_decorators_come_off() -> None:
    result = strip(
        """
        from bp import editable, node

        @node(id="health", kind="fastapi.route")
        @editable(signature_locked=True)
        def health() -> dict[str, str]:
            return {"status": "ok"}
        """
    )

    assert "bp" not in result
    assert "@node" not in result and "@editable" not in result
    assert "def health() -> dict[str, str]:" in result


def test_generated_decorator_comes_off_too() -> None:
    result = strip(
        """
        from bp import generated

        @generated()
        def include_routers(app: object) -> None:
            pass
        """
    )

    assert "@generated" not in result
    assert "def include_routers(app: object) -> None:" in result


def test_unrelated_decorators_survive() -> None:
    """Only the markup goes. A strip that ate a real decorator would change behavior."""
    result = strip(
        """
        import functools

        from bp import node

        @functools.cache
        @node(id="x", kind="k")
        def compute() -> int:
            return 1
        """
    )

    assert "@functools.cache" in result
    assert "@node" not in result


def test_param_metadata_is_unwrapped_to_the_bare_type() -> None:
    result = strip(
        """
        from typing import Annotated

        from bp import Param

        class Settings:
            chunk_size: Annotated[int, Param(min=128, max=1024)] = 512
        """
    )

    assert "chunk_size: int = 512" in result
    assert "Param" not in result


def test_annotated_keeps_metadata_that_is_not_ours() -> None:
    """A user's own `Annotated` metadata is not the markup layer's to remove."""
    result = strip(
        """
        from typing import Annotated

        from bp import Param
        from fastapi import Query

        def search(q: Annotated[str, Query(min_length=2), Param(widget="text")]) -> str:
            return q
        """
    )

    assert "Query(min_length=2)" in result
    assert "Annotated[str, Query(min_length=2)]" in result
    assert "Param" not in result


def test_orphaned_annotated_import_is_removed() -> None:
    result = strip(
        """
        from typing import Annotated

        from bp import Param

        class Settings:
            timeout: Annotated[int, Param(min=1)] = 30
        """
    )

    assert "Annotated" not in result


def test_an_annotated_still_in_use_keeps_its_import() -> None:
    result = strip(
        """
        from typing import Annotated

        from bp import Param
        from fastapi import Query

        def search(q: Annotated[str, Query()]) -> str:
            return q

        class Settings:
            timeout: Annotated[int, Param(min=1)] = 30
        """
    )

    assert "from typing import Annotated" in result
    assert "timeout: int = 30" in result


def test_aliased_imports_are_followed() -> None:
    """The markup is recognized by what it is, not by how it happens to be spelled."""
    result = strip(
        """
        from bp import editable as ed, node as bp_node

        @bp_node(id="x", kind="k")
        @ed()
        def handler() -> None:
            pass
        """
    )

    assert "bp" not in result
    assert "def handler() -> None:" in result


def test_module_style_imports_are_followed() -> None:
    result = strip(
        """
        import bp

        @bp.node(id="x", kind="k")
        def handler() -> None:
            pass
        """
    )

    assert "bp" not in result
    assert "def handler() -> None:" in result


def test_group_node_declaration_is_removed() -> None:
    result = strip(
        """
        from bp import group_node

        from app.api.health import health

        service = group_node(id="api", kind="fastapi.service", members=[health])
        """
    )

    assert "group_node" not in result
    assert "service" not in result
    assert "from app.api.health import health" in result


def test_a_file_without_markup_is_returned_untouched() -> None:
    source = textwrap.dedent(
        """
        def add(a: int, b: int) -> int:
            return a  +  b   # deliberately odd spacing
        """
    ).lstrip()

    assert strip_source(source) == source


def test_stripping_is_idempotent() -> None:
    once = strip(
        """
        from bp import node

        @node(id="x", kind="k")
        def handler() -> None:
            pass
        """
    )

    assert strip_source(once) == once


def test_strip_refuses_to_write_inside_the_source_tree(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        strip_project(tmp_path, tmp_path / "inner")


def test_group_manifests_are_removed_from_the_copy(tmp_path: Path) -> None:
    report = strip_project(EXAMPLE, tmp_path / "stripped")

    assert report.manifests_removed == [f"app/api/{GROUP_MANIFEST}"]
    assert not list((tmp_path / "stripped").rglob(GROUP_MANIFEST))


def test_the_stripped_copy_has_no_trace_of_the_markup(tmp_path: Path) -> None:
    strip_project(EXAMPLE, tmp_path / "stripped")

    for source in (tmp_path / "stripped").rglob("*.py"):
        text = source.read_text()
        assert "bp" not in text, f"{source.name} still references the markup package"
        assert "Param(" not in text


OBSERVABLE_CHECKS = """
import json, sys
sys.path.insert(0, sys.argv[1])

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
created = client.post("/users", json={"name": "linus"})
print(json.dumps({
    "health": [client.get("/health").status_code, client.get("/health").json()],
    "users": [client.get("/users").status_code, client.get("/users").json()],
    "create": [created.status_code, created.json()],
}))
"""


def observable_results(project_root: Path) -> dict[str, object]:
    """Run the service's observable checks in a fresh process and return what it answered.

    A subprocess, not an import: both copies declare the package `app`, so importing one
    would poison the other. Running them apart is also the more honest test -- the claim
    is that the stripped project *runs* identically, not that it looks similar.
    """
    proc = subprocess.run(
        [sys.executable, "-c", OBSERVABLE_CHECKS, str(project_root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return dict(json.loads(proc.stdout.strip()))


def test_the_stripped_service_answers_exactly_as_the_annotated_one(tmp_path: Path) -> None:
    """Invariant I-2, end to end.

    If this ever fails, the markup stopped being inert -- and with it goes the only thing
    separating this product from a graph-first builder.
    """
    stripped = tmp_path / "stripped"
    strip_project(EXAMPLE, stripped)

    assert observable_results(stripped) == observable_results(EXAMPLE)
