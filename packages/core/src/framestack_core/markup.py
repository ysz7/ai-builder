"""How the markup layer is spelled, and how to find it in a syntax tree.

Two tools ask the same question of the same code -- the strip ("is this our decorator, so
it comes off?") and the parser ("is this our decorator, so it makes a node?") -- and they
must answer it identically. Two copies of that knowledge would drift, and the drift would
be silent: a decorator form the parser recognized but the strip did not would survive
stripping and take `bp` into the deployed application, breaching I-2 without any test
noticing. So the knowledge lives here, once.

Nothing in this module decides anything about the graph. It reports what the syntax says.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import libcst as cst

__all__ = [
    "GROUP_MANIFEST",
    "MARKUP_DECLARATIONS",
    "MARKUP_DECORATORS",
    "MARKUP_METADATA",
    "Bindings",
    "BindingCollector",
    "alias_local_name",
    "collect_bindings",
    "dotted_name",
]

#: Decorators the markup layer defines. Inert: they mark, they never wrap.
MARKUP_DECORATORS = frozenset({"node", "editable", "generated"})

#: Calls whose result is a node declaration rather than program state.
MARKUP_DECLARATIONS = frozenset({"group_node"})

#: Metadata that rides inside `Annotated`.
MARKUP_METADATA = frozenset({"Param"})

#: The module a group node is declared in, by convention fixed in the system prompt.
GROUP_MANIFEST = "__node__.py"


@dataclass
class Bindings:
    """The local names the markup is reachable under in one module.

    Collected in a pass of its own rather than while rewriting: a visitor that learned
    names as it walked would miss any use above its import, and nothing guarantees imports
    come first in a file it did not write.
    """

    #: local name -> canonical `bp` name (`ed` -> `editable`)
    from_bp: dict[str, str] = field(default_factory=dict)
    #: names bound to the `bp` module itself (`import bp as builder`)
    bp_modules: set[str] = field(default_factory=set)
    #: local names for `typing.Annotated`
    annotated: set[str] = field(default_factory=set)
    #: names bound to the `typing` module
    typing_modules: set[str] = field(default_factory=set)
    #: local name -> the dotted origin it was imported from
    imports: dict[str, str] = field(default_factory=dict)

    @property
    def uses_markup(self) -> bool:
        return bool(self.from_bp or self.bp_modules)

    def resolve(self, expression: cst.BaseExpression) -> str | None:
        """Canonical `bp` name this expression refers to, if any."""
        if isinstance(expression, cst.Call):
            return self.resolve(expression.func)
        if isinstance(expression, cst.Name):
            return self.from_bp.get(expression.value)
        if isinstance(expression, cst.Attribute):
            base = expression.value
            if isinstance(base, cst.Name) and base.value in self.bp_modules:
                return expression.attr.value
        return None

    def is_annotated(self, expression: cst.BaseExpression) -> bool:
        if isinstance(expression, cst.Name):
            return expression.value in self.annotated
        if isinstance(expression, cst.Attribute):
            base = expression.value
            return (
                isinstance(base, cst.Name)
                and base.value in self.typing_modules
                and expression.attr.value == "Annotated"
            )
        return False


class BindingCollector(cst.CSTVisitor):
    """Reads a module's imports. Import statements only -- it never enters a body."""

    def __init__(self, package: str = "") -> None:
        #: the dotted package the module lives in, so relative imports resolve
        self.package = package
        self.bindings = Bindings()

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        module = self._absolute_module(node)
        if isinstance(node.names, cst.ImportStar):
            return False

        for alias in node.names:
            if not isinstance(alias.name, cst.Name):
                continue
            imported = alias.name.value
            local = alias_local_name(alias)
            if local is None:
                continue

            if module == "bp":
                self.bindings.from_bp[local] = imported
            elif module == "typing" and imported == "Annotated":
                self.bindings.annotated.add(local)
            if module:
                self.bindings.imports[local] = f"{module}.{imported}"
        return False

    def visit_Import(self, node: cst.Import) -> bool:
        for alias in node.names:
            module = dotted_name(alias.name)
            local = alias_local_name(alias)
            if module is None or local is None:
                continue

            if module == "bp":
                self.bindings.bp_modules.add(local)
            elif module == "typing":
                self.bindings.typing_modules.add(local)
            self.bindings.imports[local] = module
        return False

    def _absolute_module(self, node: cst.ImportFrom) -> str:
        """Resolve `from . import x` and `from ..pkg import x` against this module's package."""
        if not node.relative:
            return dotted_name(node.module) or ""

        parts = self.package.split(".") if self.package else []
        # One dot means "this package", each further dot climbs one level.
        climb = len(node.relative) - 1
        base = parts[: len(parts) - climb] if climb else parts
        tail = dotted_name(node.module)
        return ".".join([*base, tail]) if tail else ".".join(base)


def collect_bindings(module: cst.Module, package: str = "") -> Bindings:
    collector = BindingCollector(package)
    module.visit(collector)
    return collector.bindings


def alias_local_name(alias: cst.ImportAlias) -> str | None:
    """The name an import binds locally -- the alias if there is one, the name otherwise."""
    asname = alias.asname
    if asname is not None:
        return asname.name.value if isinstance(asname.name, cst.Name) else None
    return dotted_name(alias.name)


def dotted_name(node: cst.BaseExpression | cst.Attribute | None) -> str | None:
    """Flatten `a.b.c` to "a.b.c"; None for anything else."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = dotted_name(node.value)
        return None if base is None else f"{base}.{node.attr.value}"
    return None
