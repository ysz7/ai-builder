"""Proof of inertness (invariant I-2).

The bar is identity, not equivalence: a decorated object must be *the same object*
that went in. A wrapper that merely behaves the same would still be runtime
behavior, and would put the markup package on the application's critical path.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, get_args, get_type_hints

import pytest

from bp import GroupNode, Param, editable, generated, group_node, node


def test_node_returns_the_same_function_object() -> None:
    def handler(x: int) -> int:
        return x * 2

    decorated = node(id="h", kind="fastapi.route", title="H")(handler)

    assert decorated is handler
    assert decorated(21) == 42


def test_node_returns_the_same_class_object() -> None:
    class Chunker:
        size = 512

    decorated = node(id="chunking", kind="rag.chunking")(Chunker)

    assert decorated is Chunker
    assert decorated().size == 512


def test_editable_returns_the_same_function_object() -> None:
    def rank(items: list[int]) -> list[int]:
        return sorted(items, reverse=True)

    decorated = editable(signature_locked=True)(rank)

    assert decorated is rank
    assert decorated([1, 3, 2]) == [3, 2, 1]


def test_generated_returns_the_same_function_object() -> None:
    def include_routers(app: object) -> None: ...

    decorated = generated()(include_routers)

    assert decorated is include_routers


def test_editable_and_generated_are_indistinguishable_at_runtime() -> None:
    """The zones differ only to the parser -- the runtime sees two identical no-ops."""

    def scaffold() -> str:
        return "value"

    def body() -> str:
        return "value"

    assert generated()(scaffold)() == editable()(body)()


def test_decorators_preserve_identity_metadata() -> None:
    """No wrapper means no lost __name__/__doc__/__module__ -- nothing to functools.wraps."""

    def handler() -> None:
        """Docstring that must survive."""

    decorated = editable()(node(id="h", kind="k")(handler))

    assert decorated.__name__ == "handler"
    assert decorated.__doc__ == "Docstring that must survive."
    assert decorated.__module__ == handler.__module__


def test_decorated_object_gains_no_attributes() -> None:
    """The markup must leave no trace on the object at runtime."""

    def handler() -> None: ...

    before = set(vars(handler))
    node(id="h", kind="k")(handler)
    editable()(handler)
    generated()(handler)

    assert set(vars(handler)) == before


def test_group_node_holds_members_by_reference() -> None:
    class Chunker: ...

    def retrieve() -> None: ...

    subsystem = group_node(id="rag", kind="rag", title="RAG", members=[Chunker, retrieve])

    assert isinstance(subsystem, GroupNode)
    assert subsystem.members[0] is Chunker
    assert subsystem.members[1] is retrieve


def test_group_node_registers_nothing_globally() -> None:
    """Two declarations with the same id do not collide -- there is no registry."""
    a = group_node(id="api", kind="fastapi.service")
    b = group_node(id="api", kind="fastapi.service")

    assert a is not b
    assert a == b


def test_param_is_metadata_only_and_does_not_affect_the_value() -> None:
    class Settings:
        request_timeout_s: Annotated[int, Param(min=1, max=120, widget="slider")] = 30

    assert Settings.request_timeout_s == 30
    assert Settings().request_timeout_s + 1 == 31

    hints = get_type_hints(Settings, include_extras=True)
    annotation, meta = get_args(hints["request_timeout_s"])
    assert annotation is int
    assert isinstance(meta, Param)
    assert (meta.min, meta.max, meta.widget) == (1, 120, "slider")


def test_param_is_frozen() -> None:
    """A knob's metadata is read by the writer; it must not be mutable behind its back."""
    p = Param(widget="slider")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.widget = "tags"  # type: ignore[misc]


def test_package_has_no_third_party_imports() -> None:
    """bp must stay dependency-free: it ships inside every generated application."""
    import ast
    import pathlib
    import sys

    pkg = pathlib.Path(__import__("bp").__file__).parent
    stdlib = set(sys.stdlib_module_names)

    for source in pkg.rglob("*.py"):
        tree = ast.parse(source.read_text())
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.Import):
                roots = [alias.name.split(".")[0] for alias in stmt.names]
            elif isinstance(stmt, ast.ImportFrom):
                roots = [(stmt.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                assert root in stdlib or root == "bp", (
                    f"{source.name} imports {root!r}; bp must depend on nothing"
                )


def test_declared_members_do_not_touch_the_carrier() -> None:
    """Containment is a statement about the graph, never about the runtime object."""

    def list_users() -> list[int]:
        return [1]

    def users_router() -> str:
        return "router"

    decorated = node(id="users", kind="fastapi.router", members=[list_users])(users_router)

    assert decorated is users_router
    assert decorated() == "router"
    assert not hasattr(users_router, "members")
