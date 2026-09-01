"""The knobs, and the one place they are allowed to come from.

A system may contain `settings.py` with a single `BaseSettings` subclass. **The node panel
edits exactly that class and nothing else.** A system without one shows no knobs, which is
allowed and normal, and nothing here ever creates the file — if a person wants settings, the
chat writes them.

That narrowness is the whole design. The deleted version scanned a project for anything that
looked like a parameter: a default argument, a module constant, a dictionary literal, a
keyword somewhere in a call. It found hundreds, most of them not knobs, and every one of them
was a thing the interface could offer to change without knowing whether changing it meant
anything. One class in one file, named by the convention, is a rule an author can hold in
their head and a rule this module can be exactly right about.

## The write is the point

This is the first write path in the rebuild, and it is deliberately the smallest one there
could be: **one field's default, in one class, in one file.** It goes through libcst, so
everything the edit was not about stays byte-identical — the comments, the ordering, the
blank lines, the quote style of the string next to it. `git diff` after a change is one line
or the edit is wrong.

That matters more than it sounds. A settings panel that reformatted the file would put the
person in the position of reviewing a diff they did not ask for, every time they moved a
slider, and the second time it happened they would stop using the panel and edit the file.

## What is not inspected

No `Field(...)` call is unpacked, no validator is read, no environment variable is resolved,
and the class is never imported. A default that is built by a call rather than written as a
literal is **shown and refused**, with the reason said — because the value in the file is not
a value we can round-trip, and writing a literal over a call would silently delete somebody's
code. Guessing is what the annotation layer did.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from framestack_core.parser import is_system, read_graph

__all__ = [
    "Field",
    "Settings",
    "SETTINGS_FILE",
    "read_settings",
    "write_setting",
]

#: The one file a system's knobs may live in. Named by the convention, like everything else.
SETTINGS_FILE = "settings.py"

#: The base a settings class must name. Matched **by the name as written**, so
#: `pydantic_settings.BaseSettings` and a `BaseSettings` imported plainly both count and
#: nothing has to be imported to find out. A class that reaches the base through two levels of
#: its own subclassing is not recognised; that is a real limit, and the alternative is
#: resolving inheritance without running the code, which is a guess wearing a mechanism's hat.
BASE = "BaseSettings"

#: The annotation a control is chosen from, and the control it becomes. Four scalars and a
#: `Literal`, which is the whole of what the plan asks for -- an interface that can edit any
#: type is an interface that has opinions about somebody's domain model.
CONTROLS = {"int": "integer", "float": "number", "bool": "toggle", "str": "text"}

#: A field this module will show but not edit.
NONE = "none"


@dataclass(frozen=True)
class Field:
    """One knob, as the class declares it."""

    name: str
    #: The annotation exactly as written. Source text rather than an interpretation of it:
    #: the panel shows the author's own words for the type beside the control.
    annotation: str
    #: `integer`, `number`, `toggle`, `text`, `select`, or `none`.
    control: str
    #: The current default, as the field's own type. `None` where there is no control --
    #: which is not the same as a default of `None`, and is why `control` is what a caller
    #: branches on rather than this.
    value: Any
    #: What a `Literal` allows. Empty for every other control.
    choices: tuple[str, ...]
    #: Where it is written, so a person can open the file at the line and see for themselves.
    line: int
    #: Why there is no control, when there is none. Empty otherwise.
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "annotation": self.annotation,
            "control": self.control,
            "value": self.value,
            "choices": list(self.choices),
            "line": self.line,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Settings:
    """A system's knobs, or the reason it has none. A refusal is a result, as everywhere."""

    ok: bool
    detail: str
    node: str
    #: Project-relative path to the file. `""` when the system has no `settings.py`, which is
    #: the ordinary case and not a failure.
    path: str
    #: The class being edited, so the panel can say whose defaults these are.
    class_name: str
    fields: tuple[Field, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "path": self.path,
            "class_name": self.class_name,
            "fields": [field.as_dict() for field in self.fields],
        }


# -- reading the class ---------------------------------------------------------------------


def _is_settings_class(node: cst.ClassDef) -> bool:
    """Does this class name `BaseSettings` among its bases?"""
    for base in node.bases:
        value = base.value
        if isinstance(value, cst.Name) and value.value == BASE:
            return True
        if isinstance(value, cst.Attribute) and value.attr.value == BASE:
            return True
    return False


def _source_of(module: cst.Module, node: cst.CSTNode) -> str:
    """A node as the author wrote it. Used for annotations, never for values."""
    return module.code_for_node(node).strip()


def _literal(node: cst.BaseExpression) -> tuple[bool, Any]:
    """`(is a literal we can round-trip, its Python value)`.

    Deliberately small: a number, a string, a boolean, and a negative number. Anything else
    -- a call, a name, an f-string, a list -- is **not** a value this module will overwrite,
    because writing a literal over `Field(4, ge=1)` would delete a constraint the author put
    there and leave a plausible-looking file behind.
    """
    if isinstance(node, cst.Integer):
        return True, int(node.evaluated_value)
    if isinstance(node, cst.Float):
        return True, float(node.evaluated_value)
    if isinstance(node, cst.Name) and node.value in ("True", "False"):
        return True, node.value == "True"
    if isinstance(node, cst.SimpleString):
        evaluated = node.evaluated_value
        if isinstance(evaluated, str):
            return True, evaluated
        return False, None
    if isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Minus):
        inner, value = _literal(node.expression)
        if inner and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True, -value
    return False, None


def _choices(annotation: cst.BaseExpression) -> tuple[str, ...] | None:
    """The strings a `Literal[...]` allows, or `None` if this is not one.

    Only strings. `Literal[1, 2]` is a real annotation and a select over integers is a real
    control, but the moment both exist the wire has to say which it is carrying, and this is
    the phase for the smallest possible write path.
    """
    if not isinstance(annotation, cst.Subscript):
        return None
    head = annotation.value
    named = head.value if isinstance(head, cst.Name) else getattr(head, "attr", None)
    if getattr(named, "value", named) != "Literal":
        return None

    found: list[str] = []
    for element in annotation.slice:
        index = element.slice
        if not isinstance(index, cst.Index):
            return None
        ok, value = _literal(index.value)
        if not ok or not isinstance(value, str):
            return None
        found.append(value)
    return tuple(found) if found else None


def _field(
    statement: cst.AnnAssign,
    module: cst.Module,
    line: int,
) -> Field | None:
    """One annotated assignment, read as a knob. `None` when it is not one at all."""
    if not isinstance(statement.target, cst.Name):
        return None
    name = statement.target.value
    annotation = _source_of(module, statement.annotation.annotation)

    # A bare annotation binds nothing and has no default to edit. It is not a knob; it is a
    # field the author expects to come from the environment, and this panel edits defaults.
    if statement.value is None:
        return Field(name, annotation, NONE, None, (), line, "it has no default to edit")

    readable, current = _literal(statement.value)
    if not readable:
        return Field(
            name,
            annotation,
            NONE,
            None,
            (),
            line,
            f"its default is {_source_of(module, statement.value)}, which is not a plain value",
        )

    choices = _choices(statement.annotation.annotation)
    if choices is not None:
        if not isinstance(current, str) or current not in choices:
            return Field(
                name, annotation, NONE, None, choices, line, "its default is not one of its choices"
            )
        return Field(name, annotation, "select", current, choices, line, "")

    control = CONTROLS.get(annotation)
    if control is None:
        return Field(name, annotation, NONE, current, (), line, f"{annotation} has no control here")

    # The annotation and the value have to agree, or the control would write a type the
    # author did not declare. `bool` is checked first because it is a subclass of `int`.
    matches = {
        "toggle": isinstance(current, bool),
        "integer": isinstance(current, int) and not isinstance(current, bool),
        "number": isinstance(current, (int, float)) and not isinstance(current, bool),
        "text": isinstance(current, str),
    }[control]
    if not matches:
        return Field(
            name, annotation, NONE, current, (), line, "its default does not match its type"
        )

    return Field(name, annotation, control, current, (), line, "")


def _read(path: Path) -> tuple[str, tuple[Field, ...], str]:
    """`(class name, fields, refusal)` from one `settings.py`."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return "", (), f"{path.name} could not be read: {exc}"
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return "", (), f"{path.name} could not be parsed: {exc.message}"

    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    positions = wrapper.resolve(PositionProvider)

    classes = [
        statement
        for statement in wrapper.module.body
        if isinstance(statement, cst.ClassDef) and _is_settings_class(statement)
    ]
    if not classes:
        return "", (), f"{path.name} has no {BASE} subclass in it"
    if len(classes) > 1:
        # Never guessed at. Two candidate classes is a question only the author can answer,
        # and picking the first would make the panel edit a different file's worth of
        # settings than the one they were looking at.
        names = ", ".join(found.name.value for found in classes)
        return "", (), f"{path.name} has more than one {BASE} subclass ({names})"

    found_class = classes[0]
    fields: list[Field] = []
    for statement in found_class.body.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            if isinstance(small, cst.AnnAssign):
                knob = _field(small, wrapper.module, positions[statement].start.line)
                if knob is not None:
                    fields.append(knob)

    return found_class.name.value, tuple(fields), ""


def _locate(project: Path, node: str) -> tuple[Path | None, str, bool]:
    """`(the file, what to say, whether that is a refusal)`.

    Two different absences, kept apart. **A system with no `settings.py` is not a failure** --
    it is the ordinary case, and `ok: false` in front of it would make the commonest state
    look like a fault. A node nobody has heard of *is* a failure: somebody asked about
    something that is not there, and answering "no knobs" would agree with them.
    """
    graph = read_graph(project)
    found = [item for item in graph.nodes if item.id == node and is_system(item)]
    if not found:
        return None, f"there is no system called {node!r} here", True
    path = project / found[0].path / SETTINGS_FILE
    if not path.is_file():
        # Nothing is created here: a `settings.py` written because a panel was opened would
        # be the toolchain deciding that a system has knobs.
        return None, f"{node} has no {SETTINGS_FILE}", False
    return path, "", False


def read_settings(project: Path | str, node: str) -> Settings:
    """The knobs of one system. Reads the file; never imports it and never creates it."""
    root = Path(project).expanduser()
    if not root.is_dir():
        return Settings(False, f"there is no project at {root}", node, "", "", ())

    path, why, refused = _locate(root, node)
    if path is None:
        return Settings(not refused, why, node, "", "", ())

    class_name, fields, refusal = _read(path)
    relative = path.relative_to(root).as_posix()
    if refusal:
        return Settings(False, refusal, node, relative, "", ())
    return Settings(True, f"{len(fields)} field(s)", node, relative, class_name, fields)


# -- writing one default ----------------------------------------------------------------------


def _render(field: Field, value: Any, existing: cst.BaseExpression) -> tuple[str, str]:
    """`(the literal to write, refusal)`.

    The **quote style of a string is taken from what is already there.** Rewriting `"a"` as
    `'b'` is a change the person did not ask for, and a panel that churned style would be a
    panel whose diffs nobody trusts.
    """
    if field.control == "toggle":
        if not isinstance(value, bool):
            return "", f"{field.name} is a {field.annotation}; it takes true or false"
        return ("True" if value else "False"), ""

    if field.control == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return "", f"{field.name} is an {field.annotation}; it takes a whole number"
        return str(value), ""

    if field.control == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "", f"{field.name} is a {field.annotation}; it takes a number"
        return repr(float(value)), ""

    if field.control in ("text", "select"):
        if not isinstance(value, str):
            return "", f"{field.name} is a {field.annotation}; it takes text"
        if field.control == "select" and value not in field.choices:
            allowed = ", ".join(field.choices)
            return "", f"{field.name} must be one of {allowed}"
        quote = "'" if isinstance(existing, cst.SimpleString) and existing.value[:1] == "'" else '"'
        body = value.replace("\\", "\\\\").replace(quote, "\\" + quote).replace("\n", "\\n")
        return f"{quote}{body}{quote}", ""

    return "", f"{field.name} has no control here: {field.reason}"


class _SetDefault(cst.CSTTransformer):
    """Replace one field's default and touch nothing else.

    A transformer rather than a text edit, and the difference is the invariant: libcst
    rebuilds the file from the tree it parsed, so every byte the edit did not name comes back
    exactly as it was. A regular expression over the same line would be right most of the
    time, and the times it was wrong would be somebody's file.
    """

    def __init__(self, class_name: str, field: str, literal: str) -> None:
        self.class_name = class_name
        self.field = field
        self.literal = literal
        self.inside = False
        self.done = False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        if node.name.value == self.class_name:
            self.inside = True
        return True

    def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
        if original.name.value == self.class_name:
            self.inside = False
        return updated

    def leave_AnnAssign(self, original: cst.AnnAssign, updated: cst.AnnAssign) -> cst.AnnAssign:
        if not self.inside or self.done:
            return updated
        if not isinstance(original.target, cst.Name) or original.target.value != self.field:
            return updated
        self.done = True
        return updated.with_changes(value=cst.parse_expression(self.literal))


def write_setting(project: Path | str, node: str, field: str, value: Any) -> Settings:
    """Set one field's default. Returns the class as it now reads, or the refusal.

    The whole file is re-read afterwards rather than the answer being assembled from what was
    sent: what the panel draws next has to be what is in the file, not what we believe we
    put there.
    """
    root = Path(project).expanduser()
    if not root.is_dir():
        return Settings(False, f"there is no project at {root}", node, "", "", ())

    # A write always needs a file, so both absences refuse here: there is nothing to edit.
    path, why, _ = _locate(root, node)
    if path is None:
        return Settings(False, why, node, "", "", ())

    class_name, fields, refusal = _read(path)
    if refusal:
        return Settings(False, refusal, node, path.relative_to(root).as_posix(), "", ())

    target = next((one for one in fields if one.name == field), None)
    if target is None:
        return Settings(
            False,
            f"{class_name} has no field called {field!r}",
            node,
            path.relative_to(root).as_posix(),
            class_name,
            fields,
        )

    source = path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    existing = _existing_value(module, class_name, field)
    literal, complaint = _render(target, value, existing)
    if complaint:
        return Settings(
            False, complaint, node, path.relative_to(root).as_posix(), class_name, fields
        )

    edited = module.visit(_SetDefault(class_name, field, literal))
    if edited.code == source:
        # Already what was asked for. Not written, because a write that changes nothing still
        # moves a file's timestamp, and something is always watching a timestamp.
        return Settings(
            True,
            f"{field} is already {literal}",
            node,
            path.relative_to(root).as_posix(),
            class_name,
            fields,
        )

    try:
        path.write_text(edited.code, encoding="utf-8")
    except OSError as exc:
        return Settings(
            False,
            f"{path.name} could not be written: {exc}",
            node,
            path.relative_to(root).as_posix(),
            class_name,
            fields,
        )

    after = read_settings(root, node)
    return Settings(
        after.ok, f"{field} is now {literal}", node, after.path, after.class_name, after.fields
    )


def _existing_value(module: cst.Module, class_name: str, field: str) -> cst.BaseExpression:
    """The default that is there now, so a string's quote style can be kept."""
    for statement in module.body:
        if not isinstance(statement, cst.ClassDef) or statement.name.value != class_name:
            continue
        for line in statement.body.body:
            if not isinstance(line, cst.SimpleStatementLine):
                continue
            for small in line.body:
                if (
                    isinstance(small, cst.AnnAssign)
                    and isinstance(small.target, cst.Name)
                    and small.target.value == field
                    and small.value is not None
                ):
                    return small.value
    return cst.Name("None")
