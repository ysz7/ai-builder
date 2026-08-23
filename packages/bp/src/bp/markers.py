"""Boundary markers: @node, @editable, @generated, group_node.

Every construct here is inert. A decorator returns its target object unchanged --
the same object, not a copy and not a wrapper. `group_node` builds a plain data
record and touches nothing.

The parser reads these from the syntax tree; the runtime never consults them.
Putting behavior in this module would breach invariant I-2 and, with it, the only
thing separating this product from a graph-first builder.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

__all__ = ["node", "editable", "generated", "group_node", "GroupNode"]

T = TypeVar("T")


def node(
    *,
    id: str,
    kind: str,
    title: str | None = None,
    members: Iterable[Any] = (),
    **extra: Any,
) -> Callable[[T], T]:
    """Mark a single-carrier node. Returns the carrier untouched.

    `id` is unique and stable, `kind` is the dotted type the graph dispatches on,
    `title` is the human label.

    `members` declares the nodes this one contains -- a router and the routes it
    registers, for instance. Containment is not carriership: a node with one carrier can
    still hold others, and saying so explicitly is the only way the graph knows. Deriving
    it instead from who-calls-whom would break the moment two carriers referenced the same
    node, because a reference may be shared and a parent may not.

    Members are given by object reference, never by string, so a rename or a moved file
    still resolves.
    """

    def apply(carrier: T) -> T:
        return carrier

    return apply


def editable(*, signature_locked: bool = True, **extra: Any) -> Callable[[T], T]:
    """Mark a function body as user-editable. Returns the function untouched.

    The signature is the contract other nodes bind to -- it becomes a graph edge --
    so it stays locked while the body is handed to the user.
    """

    def apply(fn: T) -> T:
        return fn

    return apply


def generated(**extra: Any) -> Callable[[T], T]:
    """Mark a function as generated-zone scaffolding. Returns it untouched.

    The counterpart of `editable`, and mandatory: every function inside a carrier
    carries exactly one of the two. The classification is explicit rather than
    inferred from the absence of `@editable`, because in the syntax tree
    "scaffolding, correctly left alone" and "the agent forgot to classify this"
    look identical -- and a gate that cannot tell them apart cannot enforce
    acceptance condition 1.

    This is the Unreal rule: a member is visible to the editor only when it says so
    itself (`UPROPERTY`, `UFUNCTION`). Nothing is deduced from silence.
    """

    def apply(fn: T) -> T:
        return fn

    return apply


@dataclass(frozen=True)
class GroupNode:
    """Declarative record for a node spanning several carriers.

    Members are held by object reference, never by string: a moved file still
    resolves, a renamed string would not.
    """

    id: str
    kind: str
    title: str | None = None
    members: tuple[Any, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


def group_node(
    *,
    id: str,
    kind: str,
    title: str | None = None,
    members: Iterable[Any] = (),
    **extra: Any,
) -> GroupNode:
    """Declare a node spanning several carriers. Registers nothing, imports nothing."""
    return GroupNode(
        id=id,
        kind=kind,
        title=title,
        members=tuple(members),
        extra=extra,
    )
