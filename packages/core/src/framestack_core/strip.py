"""Remove the markup layer from a project.

This is the mechanical form of invariant I-2. The spec's test -- "remove the annotation
package from the dependencies and the application still starts" -- cannot be run
literally: deleting a package whose symbols are imported breaks the import. So instead we
remove the markup itself and require the result to pass the same observable checks as the
annotated original. If stripping ever changes behavior, the markup was not inert, and the
only thing separating this product from a graph-first builder is gone.

What comes off:

* `@node`, `@editable` and `@generated` decorators -- inert, so their absence is invisible;
* `Param(...)` metadata inside `Annotated[...]`, leaving the bare type;
* `__node__.py` group manifests, whole -- they declare nodes and run nothing;
* the now-unused `bp` imports.

Everything else is copied byte for byte. The stripped tree is written beside nothing and
owns nothing: it is an output artifact, never a second source of truth (I-1).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst

from framestack_core.markup import (
    GROUP_MANIFEST,
    MARKUP_DECLARATIONS,
    MARKUP_DECORATORS,
    MARKUP_METADATA,
    Bindings,
    alias_local_name,
    collect_bindings,
    dotted_name,
)

__all__ = ["StripReport", "strip_project", "strip_source"]

#: Never copied into the stripped tree.
SKIP_DIRECTORIES = frozenset({"__pycache__", ".git", ".venv", ".mypy_cache", ".pytest_cache"})


@dataclass
class StripReport:
    """What a strip run did. Reported so CI can assert on it, not just on exit status."""

    files_copied: int = 0
    files_rewritten: int = 0
    manifests_removed: list[str] = field(default_factory=list)


class _MarkupRemover(cst.CSTTransformer):
    def __init__(self, bindings: Bindings) -> None:
        self.bindings = bindings
        self.changed = False

    # -- decorators -------------------------------------------------------------

    def leave_Decorator(
        self, original: cst.Decorator, updated: cst.Decorator
    ) -> cst.Decorator | cst.RemovalSentinel:
        if self.bindings.resolve(original.decorator) in MARKUP_DECORATORS:
            self.changed = True
            return cst.RemoveFromParent()
        return updated

    # -- imports and node declarations ------------------------------------------

    def leave_SimpleStatementLine(
        self, original: cst.SimpleStatementLine, updated: cst.SimpleStatementLine
    ) -> cst.SimpleStatementLine | cst.RemovalSentinel:
        kept = [stmt for stmt in updated.body if not self._is_markup_statement(stmt)]
        if len(kept) == len(updated.body):
            return updated

        self.changed = True
        if not kept:
            return cst.RemoveFromParent()
        return updated.with_changes(body=kept)

    def _is_markup_statement(self, statement: cst.BaseSmallStatement) -> bool:
        if isinstance(statement, cst.ImportFrom):
            return dotted_name(statement.module) == "bp"
        if isinstance(statement, cst.Import):
            return any(dotted_name(alias.name) == "bp" for alias in statement.names)
        if isinstance(statement, cst.Assign):
            return self.bindings.resolve(statement.value) in MARKUP_DECLARATIONS
        return False

    # -- Annotated metadata -----------------------------------------------------

    def leave_Subscript(
        self, original: cst.Subscript, updated: cst.Subscript
    ) -> cst.BaseExpression:
        if not self.bindings.is_annotated(updated.value):
            return updated

        kept = [element for element in updated.slice if not self._is_markup_metadata(element)]
        if len(kept) == len(updated.slice):
            return updated

        self.changed = True
        # `Annotated` with nothing but the type left is just the type. Keeping a
        # one-element `Annotated` would be valid Python but is not what an engineer
        # writing this by hand would produce, and the stripped copy has to read like
        # ordinary code.
        if len(kept) == 1 and isinstance(kept[0].slice, cst.Index):
            return kept[0].slice.value
        return updated.with_changes(slice=[*_recomma(kept)])

    def _is_markup_metadata(self, element: cst.SubscriptElement) -> bool:
        index = element.slice
        if not isinstance(index, cst.Index):
            return False
        return self.bindings.resolve(index.value) in MARKUP_METADATA


class _NameUsageCounter(cst.CSTVisitor):
    """Names referenced outside import statements."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def visit_Import(self, node: cst.Import) -> bool:
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        return False

    def visit_Name(self, node: cst.Name) -> None:
        self.used.add(node.value)


class _UnusedImportRemover(cst.CSTTransformer):
    """Drop imports the strip itself orphaned.

    Removing `Param` from an `Annotated` can leave `from typing import Annotated` with no
    remaining user. The stripped copy has to read like code an engineer wrote, so the
    orphan goes -- but only ever an orphan the strip created, never an import that was
    already unused in the source. Tidying the user's project is not this tool's business.
    """

    def __init__(self, orphans: set[str]) -> None:
        self.orphans = orphans

    def leave_ImportFrom(
        self, original: cst.ImportFrom, updated: cst.ImportFrom
    ) -> cst.ImportFrom | cst.RemovalSentinel:
        if isinstance(updated.names, cst.ImportStar):
            return updated

        kept = [alias for alias in updated.names if alias_local_name(alias) not in self.orphans]
        if len(kept) == len(updated.names):
            return updated
        if not kept:
            return cst.RemoveFromParent()
        return updated.with_changes(
            names=[*kept[:-1], kept[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)]
        )

    def leave_SimpleStatementLine(
        self, original: cst.SimpleStatementLine, updated: cst.SimpleStatementLine
    ) -> cst.SimpleStatementLine | cst.RemovalSentinel:
        if not updated.body:
            return cst.RemoveFromParent()
        return updated


def _recomma(elements: list[cst.SubscriptElement]) -> list[cst.SubscriptElement]:
    """Drop the trailing comma the removed element may have left behind."""
    if not elements:
        return elements
    return [*elements[:-1], elements[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)]


def strip_source(source: str) -> str:
    """Return `source` with the markup layer removed. Formatting elsewhere is preserved."""
    module = cst.parse_module(source)

    bindings = collect_bindings(module)
    if not bindings.uses_markup:
        return source

    remover = _MarkupRemover(bindings)
    stripped = module.visit(remover)
    if not remover.changed:
        return source

    candidates = bindings.annotated
    if candidates:
        usage = _NameUsageCounter()
        stripped.visit(usage)
        orphans = candidates - usage.used
        if orphans:
            stripped = stripped.visit(_UnusedImportRemover(orphans))

    return stripped.code


def strip_project(source_root: Path, destination: Path) -> StripReport:
    """Write a markup-free copy of `source_root` to `destination`.

    The destination is replaced if it exists: it is a build artifact, and a stale file
    surviving from a previous run would make the strip test pass on the wrong tree.
    """
    source_root = source_root.resolve()
    destination = destination.resolve()
    if destination == source_root or source_root in destination.parents:
        raise ValueError("the stripped copy must be written outside the source tree")

    if destination.exists():
        shutil.rmtree(destination)

    report = StripReport()
    for path in sorted(source_root.rglob("*")):
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(source_root).parts):
            continue

        relative = path.relative_to(source_root)
        target = destination / relative

        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        if path.name == GROUP_MANIFEST:
            report.manifests_removed.append(str(relative))
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix != ".py":
            shutil.copy2(path, target)
            report.files_copied += 1
            continue

        source = path.read_text(encoding="utf-8")
        stripped = strip_source(source)
        target.write_text(stripped, encoding="utf-8")
        report.files_copied += 1
        if stripped != source:
            report.files_rewritten += 1

    return report
