"""The AST reader: an annotated project in, a graph IR out.

**It never imports the project.** Everything here is read off the syntax tree. Importing
would execute the user's code to draw a picture of it -- a route with a module-level
database connection would open one, and a project that fails to import would have no
graph at all, exactly when the graph is most needed. Static reading also means a broken
project still renders, which is what makes the repair system (§9) possible.

Two passes, and the split matters. A module can only be read on its own terms -- it knows
its imports and its own definitions -- while membership and edges are statements about
*pairs* of modules. So pass one records facts per module, and pass two resolves names
against the whole project. Anything a module claimed that pass two cannot resolve is
simply absent from the graph, and the gate (P3) is what turns that absence into a
diagnostic.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from framestack_core.ir import (
    Edge,
    Function,
    Graph,
    Knob,
    Location,
    Node,
    Parameter,
    Signature,
)
from framestack_core.kinds import CarrierType
from framestack_core.markup import (
    GROUP_MANIFEST,
    MARKUP_DECLARATIONS,
    MARKUP_METADATA,
    Bindings,
    collect_bindings,
)
from framestack_core.paths import iter_python_files, module_name, package_name

__all__ = ["parse_project", "parse_source", "signature_of"]

#: Renders syntax nodes back to source text, for annotations and defaults.
_RENDERER = cst.Module([])


def _code(node: cst.CSTNode | None) -> str | None:
    return None if node is None else _RENDERER.code_for_node(node).strip()


def _summary(carrier: cst.FunctionDef | cst.ClassDef) -> str:
    """The first line of the carrier's docstring, or "" (Q29).

    Asked of `libcst`, which already holds the tree -- never cut out of source text by
    whoever is drawing the node. It is what the node says about itself in the author's own
    words, and nothing reads it to decide anything: no gate, no verdict, no check.

    The **first line** and not the whole thing, because the surface it exists for is one
    grey line under a card's title. A docstring that opens with a summary line gives that
    line; one that does not gives its first line anyway, which is the author's problem to
    fix in the place the convention is already written down.
    """
    doc = carrier.get_docstring()
    return "" if doc is None else doc.strip().splitlines()[0].strip()


@dataclass
class _RawNode:
    """A node as one module can describe it: members and references are still local names."""

    id: str
    kind: str
    title: str | None
    carrier: str
    carrier_type: str
    location: Location
    zone: str | None = None
    signature: Signature | None = None
    knobs: tuple[Knob, ...] = ()
    member_names: tuple[str, ...] = ()
    summary: str = ""


@dataclass
class _ModuleFacts:
    module: str
    file: str
    bindings: Bindings
    nodes: list[_RawNode] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    #: names defined at module level, so a bare name can be told from an import
    definitions: set[str] = field(default_factory=set)
    #: `settings = ApiSettings()` -- a name standing in for a carrier
    alias_calls: dict[str, str] = field(default_factory=dict)
    #: carrier -> the local names its body mentions, in source order
    references: dict[str, list[str]] = field(default_factory=dict)


class _ReferenceCollector(cst.CSTVisitor):
    """Bare names a body mentions.

    Attribute *attrs* are skipped: in `settings.page_size` the reference is to `settings`,
    and treating `page_size` as one would invent edges out of field names.
    """

    def __init__(self) -> None:
        self.names: list[str] = []

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        node.value.visit(self)
        return False

    def visit_Name(self, node: cst.Name) -> None:
        self.names.append(node.value)


def _literal(node: cst.BaseExpression | None) -> Any:
    """The Python value of a literal, or None when it is not one.

    Deliberately narrow. A knob whose bound is computed has no single value the graph can
    show or write, so refusing to evaluate it is the honest answer -- the gate reports it
    rather than the parser inventing something.
    """
    if node is None:
        return None
    if isinstance(node, cst.SimpleString):
        return node.evaluated_value
    if isinstance(node, cst.Integer | cst.Float):
        return node.evaluated_value
    if isinstance(node, cst.Name):
        return {"True": True, "False": False, "None": None}.get(node.value)
    if isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Minus):
        inner = _literal(node.expression)
        return -inner if isinstance(inner, int | float) else None
    if isinstance(node, cst.Tuple | cst.List):
        values = [_literal(element.value) for element in node.elements]
        return tuple(values) if all(value is not None for value in values) else None
    return None


def _member_names(kwargs: dict[str, cst.BaseExpression]) -> tuple[str, ...]:
    """The names a `members=[...]` argument lists.

    Names, not values: members are given by object reference (a rename or a moved file
    still resolves), so what the syntax offers is an identifier to look up in pass two.
    """
    members = kwargs.get("members")
    if not isinstance(members, cst.Tuple | cst.List):
        return ()
    return tuple(
        element.value.value for element in members.elements if isinstance(element.value, cst.Name)
    )


def _call_kwargs(call: cst.Call) -> dict[str, cst.BaseExpression]:
    return {
        argument.keyword.value: argument.value
        for argument in call.args
        if argument.keyword is not None
    }


class _ModuleParser:
    """Reads one module. Knows nothing about any other module."""

    def __init__(self, path: Path, root: Path, source: str) -> None:
        self.path = path
        self.file = path.relative_to(root).as_posix()
        self.module = module_name(path, root)
        self.package = package_name(path, root)
        self.is_manifest = path.name == GROUP_MANIFEST

        wrapper = MetadataWrapper(cst.parse_module(source))
        self.module_cst = wrapper.module
        self.positions = wrapper.resolve(PositionProvider)
        # A second, structural read of the same text. `ast` drops formatting and comments,
        # which is precisely what a body digest must ignore: reconciliation answers "is it
        # still valid", not "did the bytes move", and a formatter must not make noise (§8).
        self.bodies = _body_digests(source)
        self.bindings = collect_bindings(self.module_cst, self.package)
        self.facts = _ModuleFacts(module=self.module, file=self.file, bindings=self.bindings)

    # -- addressing -------------------------------------------------------------

    def location(self, node: cst.CSTNode, obj: str) -> Location:
        position = self.positions[node]
        return Location(
            file=self.file,
            object=obj,
            start_line=position.start.line,
            end_line=position.end.line,
        )

    def definition_location(self, node: cst.FunctionDef | cst.ClassDef, obj: str) -> Location:
        """A definition's address, counted from its first decorator.

        libcst puts a definition's position on the `def` or `class` line, but most of what
        a diagnostic has to point at -- a missing carrier, a lost boundary, a knob that
        moved -- lives in the decorators above it. An address that excluded them would
        send the repair to the wrong line.
        """
        location = self.location(node, obj)
        if not node.decorators:
            return location
        first = self.positions[node.decorators[0]].start.line
        return Location(
            file=location.file,
            object=obj,
            start_line=first,
            end_line=location.end_line,
        )

    # -- entry point ------------------------------------------------------------

    def parse(self) -> _ModuleFacts:
        for statement in self.module_cst.body:
            if isinstance(statement, cst.FunctionDef):
                self._function(statement, owner=None)
            elif isinstance(statement, cst.ClassDef):
                self._class(statement)
            elif isinstance(statement, cst.SimpleStatementLine):
                for small in statement.body:
                    if isinstance(small, cst.Assign):
                        self._assign(small, statement)
        return self.facts

    # -- markup on a definition -------------------------------------------------

    def _markup(
        self, decorators: Sequence[cst.Decorator]
    ) -> tuple[dict[str, Any], tuple[str, ...], str | None, bool]:
        """Split decorators into: `@node` arguments, its members, the zone, and the lock."""
        node_args: dict[str, Any] = {}
        members: tuple[str, ...] = ()
        zone: str | None = None
        locked = False

        for decorator in decorators:
            name = self.bindings.resolve(decorator.decorator)
            if name is None:
                continue
            call = decorator.decorator if isinstance(decorator.decorator, cst.Call) else None
            kwargs = _call_kwargs(call) if call else {}

            if name == "node":
                node_args = {key: _literal(value) for key, value in kwargs.items()}
                members = _member_names(kwargs)
            elif name == "editable":
                zone = "editable"
                lock = _literal(kwargs.get("signature_locked"))
                # The prompt's default is a locked signature; an absent argument means
                # locked, not unlocked, or the contract would quietly become optional.
                locked = True if lock is None else bool(lock)
            elif name == "generated":
                zone = "generated"

        return node_args, members, zone, locked

    def _signature(self, function: cst.FunctionDef) -> Signature:
        return signature_of(function)

    # -- definitions ------------------------------------------------------------

    def _function(self, function: cst.FunctionDef, owner: str | None) -> None:
        name = function.name.value
        qualified = f"{owner}.{name}" if owner else name
        path = f"{self.module}.{qualified}"

        node_args, members, zone, locked = self._markup(function.decorators)
        signature = self._signature(function)
        location = self.definition_location(function, qualified)

        self.facts.functions.append(
            Function(
                path=path,
                zone=zone,
                signature=signature,
                signature_locked=locked,
                location=location,
                body_digest=self.bodies.get(qualified) if zone == "generated" else None,
                body_source=_code(function.body) if zone == "generated" else None,
            )
        )
        if owner is None:
            self.facts.definitions.add(name)

        if node_args:
            self.facts.nodes.append(
                _RawNode(
                    id=self._node_id(node_args, path),
                    kind=str(node_args.get("kind") or ""),
                    title=node_args.get("title"),
                    carrier=path,
                    carrier_type=CarrierType.FUNCTION.value,
                    location=location,
                    zone=zone,
                    signature=signature,
                    member_names=members,
                    summary=_summary(function),
                )
            )
        self._record_references(path, function.body)

    def _class(self, klass: cst.ClassDef) -> None:
        name = klass.name.value
        path = f"{self.module}.{name}"
        self.facts.definitions.add(name)

        node_args, members, zone, _ = self._markup(klass.decorators)
        location = self.definition_location(klass, name)
        knobs = tuple(self._knobs(klass, name))

        for statement in klass.body.body:
            if isinstance(statement, cst.FunctionDef):
                self._function(statement, owner=name)

        if node_args:
            self.facts.nodes.append(
                _RawNode(
                    id=self._node_id(node_args, path),
                    kind=str(node_args.get("kind") or ""),
                    title=node_args.get("title"),
                    carrier=path,
                    carrier_type=CarrierType.CLASS.value,
                    location=location,
                    zone=zone,
                    knobs=knobs,
                    member_names=members,
                    summary=_summary(klass),
                )
            )
        self._record_references(path, klass.body)

    def _knobs(self, klass: cst.ClassDef, owner: str) -> list[Knob]:
        knobs: list[Knob] = []
        for statement in klass.body.body:
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small in statement.body:
                if not isinstance(small, cst.AnnAssign):
                    continue
                knob = self._knob(small, statement, owner)
                if knob is not None:
                    knobs.append(knob)
        return knobs

    def _knob(
        self, assignment: cst.AnnAssign, line: cst.SimpleStatementLine, owner: str
    ) -> Knob | None:
        target = assignment.target
        if not isinstance(target, cst.Name):
            return None

        annotation = assignment.annotation.annotation
        if not isinstance(annotation, cst.Subscript):
            return None
        if not self.bindings.is_annotated(annotation.value):
            return None

        elements = [
            element.slice.value
            for element in annotation.slice
            if isinstance(element.slice, cst.Index)
        ]
        if not elements:
            return None

        param = next(
            (
                element
                for element in elements[1:]
                if self.bindings.resolve(element) in MARKUP_METADATA
            ),
            None,
        )
        if param is None or not isinstance(param, cst.Call):
            return None

        name = target.value
        kwargs = _call_kwargs(param)
        choices = _literal(kwargs.get("choices"))
        return Knob(
            name=name,
            type=_code(elements[0]) or "",
            default=_code(assignment.value),
            widget=_literal(kwargs.get("widget")),
            label=_literal(kwargs.get("label")),
            help=_literal(kwargs.get("help")),
            min=_literal(kwargs.get("min")),
            max=_literal(kwargs.get("max")),
            step=_literal(kwargs.get("step")),
            choices=tuple(str(choice) for choice in choices) if choices else None,
            location=self.location(line, f"{owner}.{name}"),
        )

    def _assign(self, assignment: cst.Assign, line: cst.SimpleStatementLine) -> None:
        target = assignment.targets[0].target
        if not isinstance(target, cst.Name):
            # Tuple and attribute targets bind no single name the graph could address.
            return
        name = target.value
        self.facts.definitions.add(name)

        value = assignment.value
        if not isinstance(value, cst.Call):
            return

        if self.bindings.resolve(value) in MARKUP_DECLARATIONS:
            self._group(value, line, name)
            return

        # `settings = ApiSettings()`: the name stands in for the carrier everywhere it is
        # used, and without this hop every knob node would look unreferenced.
        called = value.func
        if isinstance(called, cst.Name):
            self.facts.alias_calls[name] = called.value

    def _group(self, call: cst.Call, line: cst.SimpleStatementLine, name: str) -> None:
        kwargs = _call_kwargs(call)
        member_names = _member_names(kwargs)

        # The carrier of a group is the subsystem, not the file that declares it: the
        # manifest is bookkeeping, and pointing the node at it would make a moved
        # declaration look like a moved node.
        carrier = self.package if self.is_manifest else f"{self.module}.{name}"
        node_id = self._node_id({key: _literal(v) for key, v in kwargs.items()}, carrier)

        self.facts.nodes.append(
            _RawNode(
                id=node_id,
                kind=str(_literal(kwargs.get("kind")) or ""),
                title=_literal(kwargs.get("title")),
                carrier=carrier,
                carrier_type=CarrierType.GROUP.value,
                location=self.location(line, name),
                member_names=member_names,
            )
        )

    def _node_id(self, args: dict[str, Any], carrier: str) -> str:
        """The declared id, or a synthetic one when it is missing or not a literal.

        A node with no usable id still has to reach the gate -- it is precisely the case
        P3 must report -- and it needs a handle to be reported *by*. The angle brackets
        cannot collide with a declared id, which is a Python-identifier-shaped string.
        """
        declared = args.get("id")
        if isinstance(declared, str) and declared:
            return declared
        return f"<unidentified:{carrier}>"

    def _record_references(self, carrier: str, body: cst.CSTNode) -> None:
        collector = _ReferenceCollector()
        body.visit(collector)
        self.facts.references[carrier] = collector.names


def _body_digests(source: str) -> dict[str, str]:
    """Qualified function name -> a digest of its body, formatting excluded.

    Read with `ast` rather than the concrete tree on purpose. The concrete tree carries
    every space and comment, so a digest taken from it would change when a formatter ran --
    and reconciliation would report a divergence where nothing about the code's meaning
    moved.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    digests: dict[str, str] = {}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for statement in body:
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{statement.name}"
                dumped = ast.dump(
                    ast.Module(body=statement.body, type_ignores=[]),
                    include_attributes=False,
                )
                digests[name] = hashlib.sha256(dumped.encode()).hexdigest()[:16]
            elif isinstance(statement, ast.ClassDef):
                visit(statement.body, f"{prefix}{statement.name}.")

    visit(tree.body, "")
    return digests


# -- pass two: resolution across modules ----------------------------------------


class _Resolver:
    def __init__(self, facts: list[_ModuleFacts]) -> None:
        self.facts = facts
        self.by_module = {fact.module: fact for fact in facts}
        self.node_by_carrier: dict[str, _RawNode] = {}
        for fact in facts:
            for node in fact.nodes:
                self.node_by_carrier.setdefault(node.carrier, node)

    def carrier_for(self, fact: _ModuleFacts, name: str, depth: int = 0) -> str | None:
        """The carrier a local name refers to, following alias hops.

        `settings = ApiSettings()` binds a name to a carrier, and that name is usually
        imported and used somewhere else -- so the hop has to be followed in the module
        that *made* it, not in the one that used it. Depth is capped because a chain of
        aliases across several modules is not a graph anyone can read anyway, and an
        unbounded walk would hang on a cycle.
        """
        if depth > 4:
            return None

        candidates = self._candidates(fact, name)
        for candidate in candidates:
            if candidate in self.node_by_carrier:
                return candidate

        aliased = fact.alias_calls.get(name)
        if aliased is not None and aliased != name:
            return self.carrier_for(fact, aliased, depth + 1)

        for candidate in candidates:
            module, _, attribute = candidate.rpartition(".")
            origin = self.by_module.get(module)
            if origin is not None and origin is not fact and attribute in origin.alias_calls:
                return self.carrier_for(origin, attribute, depth + 1)
        return None

    def _candidates(self, fact: _ModuleFacts, name: str) -> list[str]:
        candidates: list[str] = []
        if name in fact.definitions:
            candidates.append(f"{fact.module}.{name}")
        imported = fact.bindings.imports.get(name)
        if imported is not None:
            candidates.append(imported)
            # `from app.api import users` then `users.thing` is not a carrier reference,
            # but `from app.api.users import users_router` is -- the import table holds
            # the dotted origin either way, so both are simply looked up.
        return candidates

    def members(
        self, fact: _ModuleFacts, node: _RawNode
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """The members that resolved, and the names that did not."""
        resolved: list[str] = []
        unresolved: list[str] = []
        for name in node.member_names:
            carrier = self.carrier_for(fact, name)
            if carrier is None:
                unresolved.append(name)
                continue
            member = self.node_by_carrier[carrier]
            if member.id not in resolved:
                resolved.append(member.id)
        return tuple(resolved), tuple(unresolved)

    def edges(self, fact: _ModuleFacts, node: _RawNode) -> list[Edge]:
        edges: list[Edge] = []
        seen: set[str] = set()
        for name in fact.references.get(node.carrier, []):
            carrier = self.carrier_for(fact, name)
            if carrier is None or carrier == node.carrier:
                continue
            target = self.node_by_carrier[carrier]
            if target.id in seen:
                continue
            seen.add(target.id)
            edges.append(Edge(source=node.id, target=target.id, contract=self.contract(target)))
        return edges

    def contract(self, target: _RawNode) -> str:
        """What crosses the boundary: the target's signature, read, never guessed (§6)."""
        if target.signature is not None:
            return target.signature.render()
        return target.carrier.rsplit(".", 1)[-1]


def signature_of(function: cst.FunctionDef) -> Signature:
    """A function's contract, read off the syntax tree.

    Module level and public because the writer needs the *same* answer when it is handed a
    replacement body (P15/Q15): "is this the same signature?" must be decided by one
    implementation, or a second one drifts and the lock stops meaning anything.
    """
    params = function.params
    collected: list[Parameter] = []

    for param in (*params.posonly_params, *params.params):
        collected.append(_parameter_of(param))
    if isinstance(params.star_arg, cst.Param):
        collected.append(_parameter_of(params.star_arg, prefix="*"))
    for param in params.kwonly_params:
        collected.append(_parameter_of(param))
    if params.star_kwarg is not None:
        collected.append(_parameter_of(params.star_kwarg, prefix="**"))

    returns = _code(function.returns.annotation) if function.returns else None
    return Signature(parameters=tuple(collected), returns=returns)


def _parameter_of(param: cst.Param, prefix: str = "") -> Parameter:
    return Parameter(
        name=f"{prefix}{param.name.value}",
        annotation=_code(param.annotation.annotation) if param.annotation else None,
        default=_code(param.default),
    )


def parse_project(root: Path) -> Graph:
    """Read an annotated project and return its graph."""
    root = root.resolve()
    facts: list[_ModuleFacts] = []
    unparsed: list[Location] = []

    for path in iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            facts.append(_ModuleParser(path, root, source).parse())
        except (cst.ParserSyntaxError, UnicodeDecodeError, OSError) as exc:
            # A file that will not parse is reported, not raised: the rest of the project
            # still has a graph, and the badge on what is missing is the point (§7).
            unparsed.append(
                Location(file=relative, object=type(exc).__name__, start_line=1, end_line=1)
            )

    resolver = _Resolver(facts)
    nodes: list[Node] = []
    edges: list[Edge] = []
    functions: list[Function] = []

    for fact in facts:
        functions.extend(fact.functions)
        for raw in fact.nodes:
            members, unresolved_members = resolver.members(fact, raw)
            nodes.append(
                Node(
                    id=raw.id,
                    kind=raw.kind,
                    title=raw.title,
                    carrier=raw.carrier,
                    carrier_type=raw.carrier_type,
                    location=raw.location,
                    zone=raw.zone,
                    signature=raw.signature,
                    knobs=raw.knobs,
                    members=members,
                    unresolved_members=unresolved_members,
                    summary=raw.summary,
                )
            )
            edges.extend(resolver.edges(fact, raw))

    return Graph(
        root=root.as_posix(),
        nodes=tuple(sorted(nodes, key=lambda node: node.id)),
        functions=tuple(sorted(functions, key=lambda function: function.path)),
        edges=tuple(sorted(edges, key=lambda edge: (edge.source, edge.target))),
        unparsed=tuple(unparsed),
    )


def parse_source(source: str, *, module: str = "module") -> Graph:
    """Parse a single module held in memory. For tests and for one-file probes."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / f"{module}.py"
        path.write_text(source, encoding="utf-8")
        graph = parse_project(root)
    return Graph(
        root="",
        nodes=graph.nodes,
        functions=graph.functions,
        edges=graph.edges,
        unparsed=graph.unparsed,
    )
