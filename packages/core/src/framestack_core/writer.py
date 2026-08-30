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

`set_body` (Q15) is the third verb and it obeys all three. It exists because the editor
lives **inside the application**: a node shows the slice of the file it owns, and the
editable part of that slice has to be writable from there or the panel is a viewer. What it
will not do is loosen anything -- a generated zone is refused, a locked signature is
refused, and the decorators are not its business at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import libcst as cst

from framestack_core.compose import composition_for
from framestack_core.diagnostics import Diagnostic
from framestack_core.gate import check_graph
from framestack_core.ir import Function, Graph, Knob, Node
from framestack_core.kinds import CarrierType
from framestack_core.markup import Bindings, collect_bindings
from framestack_core.parser import parse_project, signature_of
from framestack_core.paths import package_name
from framestack_core.snapshot import save_snapshot, take_snapshot

__all__ = [
    "WriteResult",
    "claim_member",
    "connect",
    "set_body",
    "set_knob",
    "set_node_title",
]

#: For rendering a statement back to text when a transformer has to compare against one.
#: A module of its own so the comparison is `libcst`'s own idea of the code rather than a
#: string this file assembled and hoped matched.
_RENDERER = cst.parse_module("")


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


class _AddMember(_SetCallKeyword):
    """Append one name to the `members=[...]` of the markup call that declares a group.

    Appends rather than rebuilding, which is why it subclasses the keyword setter instead of
    using it: `members` is the one keyword whose value a person has written *around* --
    the reference project has a comment inside that list explaining why the routes are not
    in it -- and setting the whole expression would silently delete it. `libcst` was chosen
    so that a write touches the syntax node it is about and nothing else, and rebuilding a
    list to add one element is exactly the "nothing else" it exists to prevent.

    A group with no `members=` at all still gets one, through the inherited path.
    """

    def __init__(self, bindings: Bindings, target: str, name: str) -> None:
        super().__init__(bindings, target, "members", cst.parse_expression(f"[{name}]"))
        self.name = name
        self.already = False

    def _with_keyword(self, call: cst.Call) -> cst.Call:
        args = list(call.args)
        for index, argument in enumerate(args):
            if argument.keyword is None or argument.keyword.value != "members":
                continue
            listed = argument.value
            if not isinstance(listed, cst.List):
                # A `members` that is not a literal list -- a name, a comprehension -- is
                # not ours to append to: whatever produced it is the thing that decides.
                return call
            if any(
                isinstance(element.value, cst.Name) and element.value.value == self.name
                for element in listed.elements
            ):
                self.already = True
                return call

            elements = list(listed.elements)
            if elements:
                # The comma the previous last element did not need, with the spacing the
                # rest of the list already uses -- a formatter run is not this write's to
                # trigger, so the line has to come out already correct.
                elements[-1] = elements[-1].with_changes(
                    comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
                )
            elements.append(cst.Element(value=cst.Name(self.name)))
            self.changed = True
            args[index] = argument.with_changes(value=listed.with_changes(elements=elements))
            return call.with_changes(args=args)

        return super()._with_keyword(call)


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


# -- editing a body ----------------------------------------------------------------


class _SetFunctionBody(cst.CSTTransformer):
    """Replace one function's body, keeping its decorators and everything around it.

    Scoped by the owner chain, so a `run` inside one class is never confused with the `run`
    inside another -- the same reason `_SetKnobDefault` carries a stack.

    The decorators are deliberately untouched: they are the markup layer, and the panel
    that calls this shows them read-only. A write that could move a decorator would be a
    write that can reclassify a zone, which is not an edit -- it is a change of who owns
    the code.
    """

    def __init__(self, qualname: str, replacement: cst.FunctionDef, keep_signature: bool) -> None:
        self.qualname = qualname
        self.replacement = replacement
        self.keep_signature = keep_signature
        self.changed = False
        self._stack: list[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._stack.append(node.name.value)
        return True

    def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
        self._stack.pop()
        return updated

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self._stack.append(node.name.value)
        return True

    def leave_FunctionDef(
        self, original: cst.FunctionDef, updated: cst.FunctionDef
    ) -> cst.FunctionDef:
        here = ".".join(self._stack)
        self._stack.pop()
        if here != self.qualname:
            return updated

        self.changed = True
        changes: dict[str, Any] = {"body": self.replacement.body}
        if not self.keep_signature:
            # Only reachable for a function whose signature was never locked. A locked one
            # is refused before the transformer is built, never quietly rewritten.
            changes["params"] = self.replacement.params
            changes["returns"] = self.replacement.returns
        return updated.with_changes(**changes)


def _submitted(source: str) -> tuple[cst.FunctionDef | None, str | None]:
    """The one function definition in what the caller sent, or the reason it is not one."""
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return None, f"the replacement does not parse: {exc}"

    statements = [item for item in module.body if not isinstance(item, cst.EmptyLine)]
    if len(statements) != 1 or not isinstance(statements[0], cst.FunctionDef):
        return None, "the replacement must be exactly one function definition"

    function = statements[0]
    if function.decorators:
        # The markup is not edited here. Letting a decorator through this path would let a
        # body edit reclassify its own zone, which is the one thing §4 exists to prevent.
        return None, "the replacement must carry no decorators; the markup is not edited here"
    return function, None


def set_body(project: Path | str, node_id: str, function_path: str, source: str) -> WriteResult:
    """Write a new body for one editable function of a node's carrier (Q15).

    Addressed by node **and** function, not by function alone: I-6 says code is edited
    through a node, and a verb that took a bare path would be a second way in that happens
    to bypass it. The function must belong to the carrier the node names, or this refuses.
    """
    project = Path(project)
    graph = parse_project(project)

    node, problem = _find(graph, node_id)
    if node is None:
        return _refused(problem or "")

    function = next((item for item in graph.functions if item.path == function_path), None)
    if function is None:
        return _refused(f"no function at {function_path!r}")
    if not _belongs_to(function, node):
        return _refused(f"{function_path!r} is not part of the carrier of {node_id!r}")

    if function.zone == "generated":
        return _refused(
            f"{function_path!r} is a generated zone: it is edited through the graph, not by hand"
        )
    if function.zone != "editable":
        return _refused(
            f"{function_path!r} is not classified @editable, so it has no editable body"
        )

    replacement, invalid = _submitted(source)
    if replacement is None:
        return _refused(invalid or "")

    submitted = signature_of(replacement)
    if function.signature_locked and submitted != function.signature:
        # The signature is the contract an edge binds to (§6). Refusing here is the whole
        # point of `signature_locked`, and it is refused rather than repaired because only
        # the author knows which of the two they meant.
        return _refused(
            f"the signature is locked: {function.signature.render()} was declared, "
            f"{submitted.render()} was submitted"
        )

    transformer = _SetFunctionBody(
        function.location.object, replacement, keep_signature=function.signature_locked
    )
    return _apply(
        project,
        graph,
        function.location.file,
        transformer,
        f"{function_path!r} was not found where the graph said it was",
    )


def _belongs_to(function: Function, node: Node) -> bool:
    """Is this function part of what the node carries?

    A function carrier is the function itself; a class or a module carrier owns everything
    defined inside it. Anything else belongs to some other node, and editing it from here
    would be editing one node's code through another's panel.
    """
    return function.path == node.carrier or function.path.startswith(f"{node.carrier}.")


# -- connecting two nodes (P21) --------------------------------------------------------


class _AddToGenerated(cst.CSTTransformer):
    """Insert one statement into a generated function, before whatever it returns.

    Before the `return` rather than at the end, because a generated zone is assembly that
    builds something and hands it back: appending after the return would write a line that
    can never run, and prepending would put the call before the thing it acts on exists.
    """

    def __init__(self, function: str, statement: str) -> None:
        self.function = function
        self.statement = statement
        self.changed = False
        self.already = False

    def leave_FunctionDef(
        self, original: cst.FunctionDef, updated: cst.FunctionDef
    ) -> cst.FunctionDef:
        if original.name.value != self.function:
            return updated

        body = updated.body
        if not isinstance(body, cst.IndentedBlock):
            return updated

        rendered = [_RENDERER.code_for_node(line).strip() for line in body.body]
        if self.statement in rendered:
            # Already connected. Writing it twice would mount the same router twice, which
            # is a real change to a real application -- so this is a refusal, not a no-op.
            self.already = True
            return updated

        line = cst.parse_statement(self.statement)
        at = len(body.body)
        for index, statement in enumerate(body.body):
            if isinstance(statement, cst.SimpleStatementLine) and any(
                isinstance(small, cst.Return) for small in statement.body
            ):
                at = index
                break

        self.changed = True
        return updated.with_changes(
            body=body.with_changes(body=[*body.body[:at], line, *body.body[at:]])
        )


class _AddImport(cst.CSTTransformer):
    """Add `from <module> import <name>` if the file does not already have that name.

    Placed after the last existing import so the file keeps a single import block. Import
    *order* is deliberately not this transformer's business: the repository's formatter
    owns that, and a writer that also sorted imports would be rewriting lines nobody asked
    it to touch, which is the one thing `libcst` was chosen to avoid.
    """

    def __init__(self, module: str, name: str) -> None:
        self.module = module
        self.name = name
        self.changed = False

    def leave_Module(self, original: cst.Module, updated: cst.Module) -> cst.Module:
        wanted = f"from {self.module} import {self.name}"
        rendered = [_RENDERER.code_for_node(line).strip() for line in updated.body]
        if any(line.startswith(wanted) for line in rendered):
            return updated

        last = -1
        for index, statement in enumerate(updated.body):
            if isinstance(statement, cst.SimpleStatementLine) and any(
                isinstance(small, cst.Import | cst.ImportFrom) for small in statement.body
            ):
                last = index

        self.changed = True
        line = cst.parse_statement(wanted)
        at = last + 1
        return updated.with_changes(body=[*updated.body[:at], line, *updated.body[at:]])


def connect(project: Path | str, source_id: str, target_id: str) -> WriteResult:
    """Write the call that connects one node to another, into the generated zone (P21).

    **The fourth write verb, and the first of a second family** (Q31). `set_knob`,
    `set_node_title` and `set_body` are the three a *person* drives, and every one of them is
    denied the generated zone because that zone is assembly the graph owns. This one writes
    into that zone and nowhere else, which is what the zone is for. The two families do not
    overlap at any address.

    It is addressed by **two** nodes rather than one, because a connection is a relation, and
    it obeys the same three rules as every other write: the gate undoes it if it made things
    worse, it becomes the new snapshot reference when it stands, and it refuses rather than
    guesses.

    **No arrow is drawn by this.** An edge appears afterwards because a type now crosses a
    boundary, or because a run drew a flow (Q9) -- and a write that succeeds while no arrow
    appears is information, not a bug.
    """
    project = Path(project)
    graph = parse_project(project)

    source = graph.node(source_id)
    if source is None:
        return _refused(f"no node with id {source_id!r}")
    target = graph.node(target_id)
    if target is None:
        return _refused(f"no node with id {target_id!r}")
    if source_id == target_id:
        return _refused("a node cannot be connected to itself")

    composition = composition_for(source.kind, target.kind)
    if composition is None:
        # Both kinds named, and no guess at a call signature. A wrong write into a generated
        # zone is a broken project; this is a sentence, and the agent is behind it.
        return _refused(
            f"nothing describes how to connect {source.kind} to {target.kind} — "
            f"ask the agent to write it"
        )

    # Searched for by the name the composition gave, and refused when that is not exactly
    # one function: "the only generated function" is a rule that holds until a project has
    # two, and then it silently picks one.
    found = [
        function
        for function in graph.functions
        if function.zone == "generated" and function.path.rsplit(".", 1)[-1] == composition.into
    ]
    if len(found) != 1:
        which = "no" if not found else f"{len(found)}"
        return _refused(
            f"{which} generated function called {composition.into!r} — "
            f"connecting {source.kind} to {target.kind} writes into that one"
        )
    into = found[0]

    module, _, name = source.carrier.rpartition(".")
    if not module:
        return _refused(f"{source.carrier!r} is not addressable as a module member")
    statement = composition.call.format(name=name, id=source.id)

    path = project / into.location.file
    before = path.read_text(encoding="utf-8")

    adder = _AddToGenerated(composition.into, statement)
    tree = cst.parse_module(before).visit(adder)
    if adder.already:
        return _refused(f"{source_id!r} is already connected to {target_id!r}")
    if not adder.changed:
        return _refused(f"{composition.into!r} was not found where the graph said it was")

    if composition.imports_source:
        importer = _AddImport(module, name)
        tree = tree.visit(importer)

    after = tree.code
    if after == before:
        return WriteResult(written=True, file=into.location.file)

    return _keep_or_undo(
        project, graph, path, into.location.file, before, after, "the connection was undone"
    )


def _keep_or_undo(
    project: Path,
    before_graph: Graph,
    path: Path,
    relative: str,
    before: str,
    after: str,
    undone: str,
) -> WriteResult:
    """Write it, then let the gate decide whether it stays.

    Shared by the verbs that edit through a transformer rather than a knob's declaration.
    Compared against the errors that were **already there**: a project with a pre-existing
    fault must still be editable, so what disqualifies a write is what it *introduced*, not
    what it failed to fix.

    The snapshot moves only when the write stands, because a snapshot taken from a state
    the gate rejected would make that breakage the thing everything after is measured
    against.
    """
    errors_before = {(d.code, d.address) for d in check_graph(before_graph).errors}
    path.write_text(after, encoding="utf-8")

    rechecked = check_graph(parse_project(project))
    introduced = [d for d in rechecked.errors if (d.code, d.address) not in errors_before]
    if introduced:
        path.write_text(before, encoding="utf-8")
        return WriteResult(
            written=False,
            file=relative,
            refused=f"{undone}: it would have broken the gate",
            diagnostics=tuple(introduced),
        )

    save_snapshot(take_snapshot(parse_project(project)), project)
    return WriteResult(written=True, file=relative)


def claim_member(project: Path | str, group_id: str, member_id: str) -> WriteResult:
    """Claim a node as a member of a group, by editing that group's own declaration.

    **The fifth write verb, and the second of the family a person drives** (Q35, amending
    Q31). It edits a keyword on the markup call, which is the address `set_node_title`
    already writes to -- not a generated zone, and not a body -- so it opens no new kind of
    write. What is new is that it is addressed by **two** nodes, because membership is a
    relation, exactly as `connect` is.

    It exists because an insert cannot do it and must not learn to. `blueprint.insert`
    writes whole files that were not there; amending a group's `members` is an edit to code
    that already exists, and P20's rule is that an insert produces code and nothing else --
    no post-insert hook, ever. So a catalog entry lands a node, and claiming it is a second
    press with its own refusals.

    Three refusals, and each one is an invariant rather than caution:

    * **a node has at most one parent** (I-3). A member some other group already claims is
      refused naming that group, because the alternative is a graph the gate then rejects
      for `node.multiple_parents` -- a write whose only outcome is a diagnostic.
    * **the group must be a group.** The top level holds groups only, and a `members=` on
      something that is not one would make a second node top-level-invalid instead of one.
    * **members are object references, never strings** -- so the member's carrier has to be
      importable by name into the group's module, and the import is written with it.

    Like every other write here: validated against the gate, undone if it made things worse,
    and the snapshot moves only when it stands.
    """
    project = Path(project)
    graph = parse_project(project)

    group = graph.node(group_id)
    if group is None:
        return _refused(f"no node with id {group_id!r}")
    member = graph.node(member_id)
    if member is None:
        return _refused(f"no node with id {member_id!r}")
    if group_id == member_id:
        return _refused("a node cannot be a member of itself")

    if group.carrier_type != CarrierType.GROUP.value:
        return _refused(
            f"{group_id!r} is a {group.kind}, not a group -- only a group holds members"
        )

    if member_id in group.members:
        return _refused(f"{member_id!r} is already a member of {group_id!r}")

    # I-3: at most one parent, and the existing one is named rather than silently replaced.
    # Moving a node between groups is a different intention from claiming an unclaimed one,
    # and a verb that did both would do the second by accident.
    claimed_by = [one.id for one in graph.nodes if member_id in one.members]
    if claimed_by:
        return _refused(
            f"{member_id!r} is already claimed by {', '.join(sorted(claimed_by))} -- "
            "a node has one parent, so remove it there first"
        )

    module, _, name = member.carrier.rpartition(".")
    if not module:
        return _refused(f"{member.carrier!r} is not addressable as a module member")

    path = project / group.location.file
    before = path.read_text(encoding="utf-8")

    bindings = collect_bindings(cst.parse_module(before), package_name(path, project))
    adder = _AddMember(bindings, group.location.object, name)
    tree = cst.parse_module(before).visit(adder)
    if adder.already:
        return _refused(f"{name!r} is already listed in {group_id!r}'s members")
    if not adder.changed:
        return _refused(
            f"the declaration of {group_id!r} was not found where the graph said it was"
        )

    tree = tree.visit(_AddImport(module, name))

    after = tree.code
    if after == before:
        return WriteResult(written=True, file=group.location.file)

    return _keep_or_undo(
        project, graph, path, group.location.file, before, after, "the claim was undone"
    )
