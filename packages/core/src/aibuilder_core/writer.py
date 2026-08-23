"""Writing back into code, through the syntax tree.

Every edit addresses a **syntax node** — an `Annotated` field's default, an argument of a
carrier's decorator — never a line and never a span of text (§8, I-4). That is the reason
the markup is real Python rather than anchor comments: the tree can see a decorator and a
type, and it cannot see the meaning of a comment. `libcst` preserves everything it was not
asked to change, so the rest of the file comes out byte for byte as it went in.

Three rules hold every write:

**A write that breaks the gate is undone.** The user did not make this edit — the graph
did — so a write of ours that leaves the project worse than it found it is a bug, and the
file goes back to what it was. The caller is told why rather than left with the wreckage.

**A knob's own declaration is enforced.** A field that says `Param(min=1, max=120)` will
not be written 500. The declaration is the graph's promise about that value; writing past
it would make the promise decorative.

**A passing write becomes the new reference.** Otherwise the graph's own edit would show
up as a divergence the next time reconciliation ran (§8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import libcst as cst

from aibuilder_core.diagnostics import Diagnostic
from aibuilder_core.gate import check_graph
from aibuilder_core.ir import Graph, Knob, Node
from aibuilder_core.markup import Bindings, collect_bindings
from aibuilder_core.parser import parse_project
from aibuilder_core.paths import package_name
from aibuilder_core.snapshot import save_snapshot, take_snapshot

__all__ = ["WriteResult", "set_knob", "set_node_title"]


@dataclass(frozen=True)
class WriteResult:
    written: bool
    file: str | None = None
    refused: str | None = None
    #: Populated when a write was undone: what the gate said about the result.
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return {
            "written": self.written,
            "file": self.file,
            "refused": self.refused,
            "diagnostics": [asdict(diagnostic) for diagnostic in self.diagnostics],
        }


def _refused(reason: str) -> WriteResult:
    return WriteResult(written=False, refused=reason)


# -- value rendering and validation ----------------------------------------------


def _render(value: Any, previous: str | None) -> str | None:
    """The source text for a new value, or None when it is not something we may write.

    A string reuses the quote character already in the file. The graph should leave no
    trace beyond the value it was asked to change, and swapping every `"x"` for `'x'`
    would put a formatting argument into a diff that is supposed to be about one number.
    """
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        quote = "'" if previous and previous.startswith("'") else '"'
        if quote in value or "\\" in value or "\n" in value:
            return None  # escaping is a formatting decision; refuse rather than guess
        return f"{quote}{value}{quote}"
    if isinstance(value, list | tuple):
        parts = [_render(item, None) for item in value]
        if any(part is None for part in parts):
            return None
        return "[" + ", ".join(part for part in parts if part) + "]"
    return None


def _validate(knob: Knob, value: Any) -> str | None:
    """The reason this value may not be written, or None if it may."""
    declared = knob.type.strip()

    if knob.choices is not None and str(value) not in knob.choices:
        return f"{value!r} is not one of the declared choices: {', '.join(knob.choices)}"

    if declared.startswith("bool"):
        if not isinstance(value, bool):
            return f"{knob.name} is declared bool; {type(value).__name__} was given"
    elif declared.startswith("int"):
        # bool is an int in Python, and writing True into a slider is never what was meant.
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{knob.name} is declared int; {type(value).__name__} was given"
    elif declared.startswith("float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{knob.name} is declared float; {type(value).__name__} was given"
    elif declared.startswith("str"):
        if not isinstance(value, str):
            return f"{knob.name} is declared str; {type(value).__name__} was given"
    elif declared.startswith(("list", "tuple", "set")) and not isinstance(value, list | tuple):
        return f"{knob.name} is declared {declared}; {type(value).__name__} was given"

    if isinstance(value, int | float) and not isinstance(value, bool):
        if knob.min is not None and value < knob.min:
            return f"{value} is below the declared minimum of {knob.min}"
        if knob.max is not None and value > knob.max:
            return f"{value} is above the declared maximum of {knob.max}"

    return None


# -- transformers -----------------------------------------------------------------


class _SetKnobDefault(cst.CSTTransformer):
    """Replace one annotated field's default, and nothing else in the file."""

    def __init__(self, owner: str, name: str, value: cst.BaseExpression) -> None:
        self.owner = owner
        self.name = name
        self.value = value
        self.changed = False
        self._stack: list[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._stack.append(node.name.value)
        return True

    def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
        self._stack.pop()
        return updated

    def leave_AnnAssign(self, original: cst.AnnAssign, updated: cst.AnnAssign) -> cst.AnnAssign:
        if self._stack and self._stack[-1] != self.owner:
            return updated
        target = updated.target
        if not isinstance(target, cst.Name) or target.value != self.name:
            return updated

        self.changed = True
        return updated.with_changes(value=self.value)


class _SetCallKeyword(cst.CSTTransformer):
    """Set a keyword argument on the markup call that declares one node.

    Finds the node by its carrier's name -- a decorated function or class, or the
    assignment a `group_node` is bound to -- and edits the call in place. Adding the
    keyword when it is missing matters: a node with no `title=` still has to be renamable.
    """

    def __init__(self, bindings: Bindings, target: str, keyword: str, value: cst.BaseExpression):
        self.bindings = bindings
        self.target = target
        self.keyword = keyword
        self.value = value
        self.changed = False

    def leave_FunctionDef(
        self, original: cst.FunctionDef, updated: cst.FunctionDef
    ) -> cst.FunctionDef:
        if updated.name.value != self.target.rsplit(".", 1)[-1]:
            return updated
        return updated.with_changes(decorators=self._decorators(updated.decorators))

    def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
        if updated.name.value != self.target.rsplit(".", 1)[-1]:
            return updated
        return updated.with_changes(decorators=self._decorators(updated.decorators))

    def leave_Assign(self, original: cst.Assign, updated: cst.Assign) -> cst.Assign:
        target = updated.targets[0].target
        if not isinstance(target, cst.Name) or target.value != self.target:
            return updated
        if not isinstance(updated.value, cst.Call):
            return updated
        if self.bindings.resolve(updated.value) != "group_node":
            return updated

        return updated.with_changes(value=self._with_keyword(updated.value))

    def _decorators(self, decorators: Sequence[cst.Decorator]) -> list[cst.Decorator]:
        result = []
        for decorator in decorators:
            call = decorator.decorator
            if self.bindings.resolve(call) == "node" and isinstance(call, cst.Call):
                decorator = decorator.with_changes(decorator=self._with_keyword(call))
            result.append(decorator)
        return result

    def _with_keyword(self, call: cst.Call) -> cst.Call:
        args = list(call.args)
        for index, argument in enumerate(args):
            if argument.keyword is not None and argument.keyword.value == self.keyword:
                self.changed = True
                args[index] = argument.with_changes(value=self.value)
                return call.with_changes(args=args)

        # Not present: append it, keeping whatever comma style the call already uses.
        self.changed = True
        if args:
            args[-1] = args[-1].with_changes(
                comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
            )
        args.append(
            cst.Arg(
                keyword=cst.Name(self.keyword),
                value=self.value,
                equal=cst.AssignEqual(
                    whitespace_before=cst.SimpleWhitespace(""),
                    whitespace_after=cst.SimpleWhitespace(""),
                ),
            )
        )
        return call.with_changes(args=args)


# -- the write path ----------------------------------------------------------------


def _find(graph: Graph, node_id: str) -> tuple[Node | None, str | None]:
    node = graph.node(node_id)
    if node is None:
        return None, f"no node with id {node_id!r}"
    return node, None


def _apply(
    project: Path,
    graph: Graph,
    relative_file: str,
    transformer: cst.CSTTransformer,
    missing: str,
) -> WriteResult:
    """Transform one file, then let the gate decide whether the edit may stand."""
    path = project / relative_file
    before = path.read_text(encoding="utf-8")
    module = cst.parse_module(before)
    after = module.visit(transformer).code

    if not getattr(transformer, "changed", False):
        return _refused(missing)
    if after == before:
        return WriteResult(written=True, file=relative_file)

    errors_before = {(d.code, d.address) for d in check_graph(graph).errors}
    path.write_text(after, encoding="utf-8")

    rechecked = check_graph(parse_project(project))
    introduced = [d for d in rechecked.errors if (d.code, d.address) not in errors_before]
    if introduced:
        # Ours to undo. The user did not make this edit, so they should not be left
        # holding it.
        path.write_text(before, encoding="utf-8")
        return WriteResult(
            written=False,
            file=relative_file,
            refused="the edit was undone: it would have broken the gate",
            diagnostics=tuple(introduced),
        )

    # The graph's own edit must not read as a divergence next time §8 asks.
    save_snapshot(take_snapshot(parse_project(project)), project)
    return WriteResult(written=True, file=relative_file)


def set_knob(project: Path | str, node_id: str, knob_name: str, value: Any) -> WriteResult:
    """Write a new value into a knob's literal default."""
    project = Path(project)
    graph = parse_project(project)

    node, problem = _find(graph, node_id)
    if node is None:
        return _refused(problem or "")

    knob = next((k for k in node.knobs if k.name == knob_name), None)
    if knob is None:
        return _refused(f"node {node_id!r} has no knob {knob_name!r}")
    if knob.location is None:
        return _refused(f"knob {knob_name!r} has no address to write to")

    invalid = _validate(knob, value)
    if invalid is not None:
        return _refused(invalid)

    source = _render(value, knob.default)
    if source is None:
        return _refused(f"{value!r} is not a value the writer can express as a literal")

    owner, _, name = knob.location.object.rpartition(".")
    transformer = _SetKnobDefault(owner, name, cst.parse_expression(source))
    return _apply(
        project,
        graph,
        knob.location.file,
        transformer,
        f"knob {knob_name!r} was not found where the graph said it was",
    )


def set_node_title(project: Path | str, node_id: str, title: str) -> WriteResult:
    """Rename a node, by editing the `title=` on its own declaration."""
    project = Path(project)
    graph = parse_project(project)

    node, problem = _find(graph, node_id)
    if node is None:
        return _refused(problem or "")

    source = _render(title, node.title)
    if source is None:
        return _refused(f"{title!r} is not a value the writer can express as a literal")

    path = project / node.location.file
    bindings = collect_bindings(
        cst.parse_module(path.read_text(encoding="utf-8")),
        package_name(path, project),
    )
    transformer = _SetCallKeyword(
        bindings, node.location.object, "title", cst.parse_expression(source)
    )
    return _apply(
        project,
        graph,
        node.location.file,
        transformer,
        f"the declaration of {node_id!r} was not found where the graph said it was",
    )
