"""Planning and inserting a blueprint that carries code (P20).

**Insertion produces code and nothing else.** Files are written into the project, the
project is re-parsed, and the graph is whatever the parser now says. Nothing downstream --
the gate, the checks, the snapshot, the writer, repair -- can tell an inserted node from a
written one, because there is nothing to tell: they only ever see files. That is what keeps
I-1 true through a gesture that looks like dragging a template onto a canvas.

**The inserted node is not green.** It proves itself the way everything else does, by a run.
A template that shipped its own verdict would be I-5 with a back door, and it is precisely
the lie every flow-document builder tells.

Who vouches for the code is settled as Q28, and the answer is **nobody**: this codebase does
not get to have an opinion about whether a stranger's Python is malicious, and every
mechanism that would let it pretend to is absent on purpose. What it owes instead is that
the code arrives **visibly**, arrives **inert**, and arrives **from a place somebody named**:

- *Visibly.* `plan_blueprint` returns every file and its full contents, plus what the entry
  imports and what it therefore needs installed. `insert_blueprint` takes the plan's
  identity as a required keyword with no default -- `apply_repair`'s shape, for
  `apply_repair`'s reason -- so nothing can be written that was not the thing described.
- *Inertly.* Copying files executes nothing. No import, no install, **no post-insert hook,
  ever**: an entry is files and only files, and there is no mechanism here for one to run
  anything, which is a rule rather than an accident of this implementation. The first
  execution is a press somebody makes.
- *From somewhere named.* Two sources and no third (`catalog.py`): the catalog shipped
  inside the application, and a local path passed in or pointed at by `CATALOG_ENV`.

What is checked is what can be checked honestly: containment, refusal on collision instead
of a merge, and the gate afterwards with the insert undone if it came back worse. What is
refused by name is an import allowlist or a scanner -- bypassed trivially, and read as a
guarantee -- and a sandbox for the first run, which cannot exist because `Observe` has to
run the project in the project's own environment or the evidence is not about the project.

Named for one entry rather than for the catalog, and deliberately: `catalog.py` is the
catalog, `blueprint.py` is what one of its entries would do to a project. It also keeps the
module out of the way of `framestack_core/blueprints/`, which is the bundled catalog's data
directory -- a module and a package directory sharing a name resolve today and are a trap
tomorrow.

**Nothing about the entry's origin is written down** (Q28.6). A marker saying "this came
from blueprint foo" is a manifest: it goes stale at the first edit, it is a second store of
state (I-1), and it immediately invites an "update from the blueprint" operation. Without
it, upstream drift does not exist -- not because it is handled, but because there is no link
along which it could happen. What records the change is the git diff.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from framestack_core.catalog import CODE_DIR, all_blueprints, blueprint_files
from framestack_core.diagnostics import Code, Diagnostic
from framestack_core.gate import check_graph
from framestack_core.parser import parse_project
from framestack_core.snapshot import save_snapshot, take_snapshot

__all__ = [
    "InsertResult",
    "Plan",
    "PlannedFile",
    "insert_blueprint",
    "plan_blueprint",
]

#: The state directory, which an entry may never write into. The same denial the agent has,
#: and for the same reason: a blueprint that could drop a file in here would be writing
#: evidence about itself.
STATE_DIR = ".framestack"


@dataclass(frozen=True)
class PlannedFile:
    """One file an insert would write, and whether anything is already there."""

    #: Project-relative, always with forward slashes: this is an address a client shows.
    path: str
    contents: str
    #: Something already exists at this path. A collision is a **refusal**, never a merge --
    #: merging somebody's project with a template is the class of operation this codebase
    #: has consistently refused to do silently.
    collides: bool = False


@dataclass(frozen=True)
class Plan:
    """What inserting this entry would do, before anything is written."""

    blueprint: str
    title: str
    #: "bundled" or "named". It decides whether a client asks first (Q28.2) and nothing else.
    origin: str
    files: tuple[PlannedFile, ...] = ()
    #: Every top-level module the entry's Python imports and this interpreter cannot find.
    #: **Facts, not a verdict** -- "show, do not judge". Dependencies are declared here and
    #: installed by nobody: `env.*` installs, and only because a person pressed it (Q28.5).
    requires: tuple[str, ...] = ()
    #: Every third-party module it imports. The summary Q28.4 owes a reader -- and the
    #: standard library is left out of it deliberately: a reader scanning for what a
    #: stranger's code reaches for does not learn anything from `typing` sitting next to
    #: `langchain_core`, and a list padded with the harmless is a list nobody reads.
    imports: tuple[str, ...] = ()
    #: The identity of exactly this plan. `insert_blueprint` is given it back and refuses if
    #: the entry has changed since -- so nothing can be written that was not what was shown.
    identity: str = ""
    #: **A part, not a whole project** (Q36). It lands a node the top level cannot hold, so
    #: inserting it leaves exactly one gate error against that node and claiming it into a
    #: group is the next press (`node.claim`, Q35). Carried on the plan rather than looked
    #: up again at insert time, and shown before anything is written: "this needs a home" is
    #: something a person should read *before* pressing, not discover from a red node.
    part: bool = False
    refused: str | None = None

    @property
    def collisions(self) -> tuple[str, ...]:
        return tuple(one.path for one in self.files if one.collides)


@dataclass
class InsertResult:
    """What an insert did, or why it did nothing."""

    inserted: bool
    #: Written in the order they were planned. Empty when the insert was refused or undone.
    files: tuple[str, ...] = ()
    refused: str | None = None
    #: Gate errors the insert introduced, when it was undone because of them.
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


def plan_blueprint(
    project: Path | str,
    blueprint_id: str,
    catalog: Path | str | None = None,
) -> Plan:
    """Everything inserting this entry would do, and nothing done.

    A read: it opens the catalog and the project's own directory listing, and it writes
    nothing and runs nothing. An entry that carries no code plans no files, which is not a
    failure -- it is a specification-text entry, which is what every entry was before P20.
    """
    root = Path(project).resolve()
    entry = next((one for one in all_blueprints(catalog) if one.id == blueprint_id), None)
    if entry is None:
        return Plan(blueprint_id, blueprint_id, "named", refused=f"no blueprint {blueprint_id!r}")

    source = Path(entry.path).parent
    planned: list[PlannedFile] = []
    for path in blueprint_files(source):
        relative = path.relative_to(source / CODE_DIR).as_posix()
        problem = _containment_problem(root, relative)
        if problem is not None:
            return Plan(entry.id, entry.title, entry.origin, refused=problem)
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return Plan(
                entry.id,
                entry.title,
                entry.origin,
                refused=f"{relative} could not be read: {type(exc).__name__}",
            )
        planned.append(
            PlannedFile(path=relative, contents=contents, collides=(root / relative).exists())
        )

    imports = _imports_of(planned)
    return Plan(
        blueprint=entry.id,
        title=entry.title,
        origin=entry.origin,
        files=tuple(planned),
        requires=tuple(name for name in imports if not _importable(name)),
        imports=imports,
        identity=_identity(entry.id, planned),
        part=entry.part,
    )


def insert_blueprint(
    project: Path | str,
    blueprint_id: str,
    *,
    plan: str,
    catalog: Path | str | None = None,
) -> InsertResult:
    """Write the entry's files into the project, or refuse and write nothing.

    `plan` is the identity `plan_blueprint` returned, and it is a **required keyword with no
    default**. That is `apply_repair(resolution=...)`'s shape and it is here for the same
    kind of reason: there must be no call that inserts a stranger's code without having been
    handed the description of what it was going to insert. It is checked rather than
    trusted -- an entry that changed on disk between the plan and the press no longer matches
    its identity, and the insert is refused rather than quietly writing the new thing.

    A client that asks first (a third-party entry) and one that does not (a bundled entry,
    whose trust decision was made at install) run exactly this code path; where they differ
    is whether a person saw the plan, which is a question about the client, not about this.
    """
    root = Path(project).resolve()
    intended = plan_blueprint(root, blueprint_id, catalog)
    if intended.refused is not None:
        return InsertResult(False, refused=intended.refused)
    if not intended.files:
        return InsertResult(False, refused=f"{blueprint_id!r} carries no code to insert")
    if plan != intended.identity:
        return InsertResult(
            False,
            refused="this entry is not what the plan described — read it again before inserting",
        )
    if intended.collisions:
        # A refusal with an address, never a merge (Q28.4). The person moves or deletes what
        # is in the way; this application does not get to decide whose version wins.
        listed = ", ".join(intended.collisions)
        return InsertResult(False, refused=f"already in this project: {listed}")

    before_graph = parse_project(root)
    errors_before = {(d.code, d.address) for d in check_graph(before_graph).errors}
    _nodes_before = before_graph.nodes

    written: list[Path] = []
    for one in intended.files:
        target = root / one.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(one.contents, encoding="utf-8")
        written.append(target)

    rechecked = check_graph(parse_project(root))
    introduced = [d for d in rechecked.errors if (d.code, d.address) not in errors_before]
    if intended.part:
        # **A part is defined by the one error it lands with** (Q36). An `mcp.server` is
        # never top-level, so an entry that lands one *cannot* be whole on its own: the
        # gate is right to report `node.top_level_not_group`, and undoing the insert over
        # it means the entry can never be inserted at all -- which is what this branch was
        # found doing, after Q35 had already been written on the assumption that claiming
        # was a separate press.
        #
        # Narrow on purpose, and declared rather than inferred: only this code, only on an
        # entry whose catalog says `part`, and only against a node **this insert landed**.
        # Every other error still undoes it, so the guarantee that survives is the one that
        # mattered -- an insert never leaves a project broken in a way nobody named.
        landed = {node.id for node in parse_project(root).nodes} - {
            node.id for node in _nodes_before
        }
        introduced = [
            diagnostic
            for diagnostic in introduced
            # `node` and not `address`: the address is `file:line object`, which is what a
            # person reads and an editor jumps to. The node id is the separate field, and
            # matching on the wrong one is how this filter silently matched nothing.
            if not (diagnostic.code == Code.TOP_LEVEL_NOT_GROUP.value and diagnostic.node in landed)
        ]
    if introduced:
        # Ours to undo, exactly as a knob write is: the person asked for a node, not for a
        # project that no longer parses, and they should not be left holding one.
        for target in reversed(written):
            target.unlink(missing_ok=True)
        _prune(root, written)
        return InsertResult(
            False,
            refused="the insert was undone: it would have broken the gate",
            diagnostics=tuple(introduced),
        )

    # The new files must not read as a divergence next time §8 asks. They are the project's
    # own code from this moment on -- which is the whole of what "nothing is recorded about
    # where they came from" means in practice.
    save_snapshot(take_snapshot(parse_project(root)), root)
    return InsertResult(True, files=tuple(one.path for one in intended.files))


def _containment_problem(root: Path, relative: str) -> str | None:
    """Why this path may not be written, or `None`.

    Everything an insert writes lands inside the project, and `.framestack/` is denied
    outright -- the same denial the agent has (Q21), because a blueprint that could drop a
    file in there would be writing evidence about itself.
    """
    if Path(relative).is_absolute() or relative.startswith("/"):
        return f"{relative} is an absolute path"
    target = (root / relative).resolve()
    try:
        inside = target.relative_to(root)
    except ValueError:
        return f"{relative} would be written outside the project"
    if inside.parts and inside.parts[0] == STATE_DIR:
        return f"{relative} would be written into {STATE_DIR}/"
    return None


def _imports_of(files: list[PlannedFile]) -> tuple[str, ...]:
    """Every top-level module the entry's Python imports.

    Parsed with `ast`, never imported: reading what a file says it needs must not run it,
    and this whole module exists to keep arriving and running apart.

    It is a **summary shown to a reader**, and deliberately not a gate. An allowlist or a
    scanner here would be bypassed by anyone who wanted to and would read as a guarantee to
    everyone who did not, which is worse than saying plainly that nobody vouches for this.
    """
    found: set[str] = set()
    for one in files:
        if not one.path.endswith(".py"):
            continue
        try:
            tree = ast.parse(one.contents)
        except SyntaxError:
            continue  # a file that will not parse is the gate's finding, not this one's
        for statement in ast.walk(tree):
            if isinstance(statement, ast.Import):
                found.update(alias.name.partition(".")[0] for alias in statement.names)
            elif isinstance(statement, ast.ImportFrom) and statement.level == 0:
                found.add((statement.module or "").partition(".")[0])
    # The entry's own packages are not a dependency on anything: they arrive with it, and
    # the standard library is not news about anybody's code.
    own = {one.path.split("/")[0].removesuffix(".py") for one in files}
    return tuple(
        sorted(
            name
            for name in found
            if name
            and name not in own
            and name not in sys.stdlib_module_names
            and name not in sys.builtin_module_names
        )
    )


def _importable(name: str) -> bool:
    """Is this module already here? Asked of the import system, and **never imported**.

    `find_spec` would import a parent package to look inside it, so the check is kept to the
    top-level name and done with the finders directly. A module that is present answers
    nothing about whether the entry works -- it only stops "needs `langgraph`" being said
    about a project that has it.
    """
    if name in sys.builtin_module_names or name in sys.stdlib_module_names:
        return True
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _identity(blueprint_id: str, files: list[PlannedFile]) -> str:
    """A digest over the entry and every byte it would write.

    What makes `insert_blueprint`'s keyword worth requiring: it is not a token proving a
    dialog was shown, it is the content itself, so an entry edited between the plan and the
    press no longer matches and the insert is refused.
    """
    digest = hashlib.sha256(blueprint_id.encode("utf-8"))
    for one in files:
        digest.update(b"\0")
        digest.update(one.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(one.contents.encode("utf-8"))
    return digest.hexdigest()


def _prune(root: Path, written: list[Path]) -> None:
    """Remove directories an undone insert created and left empty.

    Only ones that are empty, and never the project root: an undo that removed a directory
    somebody else's file was in would be a worse bug than the one it is cleaning up after.
    """
    for target in written:
        parent = target.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
