"""The repair system: acting on a divergence, and refusing to act alone.

§9 splits repairs by **whose fault** the divergence is, and the split decides who is
allowed to choose.

**Case 1 — the editable zone broke its contract.** The signature is in the reference and
the body is in the file, so the fix restores one without discarding the other. There is no
judgement call here: the contract was locked, the user was told it was locked, and putting
it back is what "locked" meant. The toolchain does this itself.

**Case 2 — the generated zone was touched.** Two non-equivalent paths, and the tool takes
neither on its own. Reverting erases work; accepting may bless a breakage inside a green
node. A tool that always reverts will one day delete an edit a human needed, and a tool
that always accepts will one day legitimise broken code — either habit spends the graph's
only currency, which is being believed. So both options are surfaced and the caller
decides. `resolution` is a required argument with no default, and there is a test that
this cannot be circumvented.

Everything else goes to the agent as a **structured request** rather than a mechanical
edit: what, where, which rule, and what the repair must not disturb. That is the difference
between a repair that lands first time and a blind edit that breaks the neighbour.

Every outcome re-enters the gates, and only a pass updates the reference (I-5).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import libcst as cst

from aibuilder_core.diagnostics import Diagnostic
from aibuilder_core.observe import run_observations
from aibuilder_core.parser import parse_project
from aibuilder_core.reconcile import Divergence, DivergenceCode, Fault, Resolution, reconcile
from aibuilder_core.snapshot import Snapshot, load_snapshot, save_snapshot, take_snapshot
from aibuilder_core.writer import _apply

__all__ = ["RepairResult", "apply_repair", "list_repairs", "repair_request"]

#: Divergences the toolchain can resolve by editing code itself. Everything else is
#: described to the agent instead -- a mechanical edit it cannot make correctly is worse
#: than an instruction it can follow.
MECHANICAL = {
    (DivergenceCode.SIGNATURE_BROKEN.value, Resolution.REPAIR.value),
    (DivergenceCode.GENERATED_TOUCHED.value, Resolution.REVERT.value),
}


@dataclass(frozen=True)
class RepairResult:
    applied: bool
    #: Whether the reference moved. Only a both-conditions pass earns that (I-5).
    snapshot_updated: bool = False
    file: str | None = None
    refused: str | None = None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    #: Nodes whose observable check failed after the repair. The code may still be right;
    #: the reference does not move until they pass.
    unproven: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "snapshot_updated": self.snapshot_updated,
            "file": self.file,
            "refused": self.refused,
            "diagnostics": [asdict(diagnostic) for diagnostic in self.diagnostics],
            "unproven": list(self.unproven),
        }


def _refused(reason: str) -> RepairResult:
    return RepairResult(applied=False, refused=reason)


def repair_request(divergence: Divergence) -> str:
    """The instruction an agent can act on without seeing anything else.

    Deliberately not "fix the API". It names the file, the object, the rule that was
    broken, and what must survive the fix -- everything §9 requires a problem to carry.
    """
    lines = [
        f"In {divergence.location.file}, at {divergence.location.object} "
        f"(lines {divergence.location.start_line}-{divergence.location.end_line}):",
        f"  problem: {divergence.message}",
        f"  rule: {divergence.rule}",
        f"  required: {divergence.repair}",
    ]
    if divergence.reference:
        lines.append(f"  the last valid state was: {divergence.reference}")
    if divergence.fault == Fault.CONTRACT.value:
        lines.append("  do not discard the body; only the signature is to be restored")
    if divergence.fault == Fault.GENERATED.value:
        lines.append("  do not choose between reverting and re-annotating; the user does")
    return "\n".join(lines)


def list_repairs(project: Path | str) -> list[dict[str, Any]]:
    """Every divergence, with what may be done about it and the request text for an agent."""
    project = Path(project)
    snapshot = load_snapshot(project)
    if snapshot is None:
        return []

    return [
        {
            **asdict(divergence),
            "mechanical": [
                resolution
                for resolution in divergence.resolutions
                if (divergence.code, resolution) in MECHANICAL
                or resolution == Resolution.ACCEPT.value
            ],
            "request": repair_request(divergence),
        }
        for divergence in reconcile(snapshot, parse_project(project))
    ]


# -- the edits ---------------------------------------------------------------------


class _RestoreSignature(cst.CSTTransformer):
    """Put a locked signature back, leaving the body exactly as the user left it."""

    def __init__(self, target: str, params: cst.Parameters, returns: cst.Annotation | None):
        self.target = target
        self.params = params
        self.returns = returns
        self.changed = False
        self._stack: list[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._stack.append(node.name.value)
        return True

    def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
        self._stack.pop()
        return updated

    def leave_FunctionDef(
        self, original: cst.FunctionDef, updated: cst.FunctionDef
    ) -> cst.FunctionDef:
        qualified = ".".join([*self._stack, updated.name.value])
        if qualified != self.target:
            return updated

        self.changed = True
        return updated.with_changes(params=self.params, returns=self.returns)


class _RestoreBody(cst.CSTTransformer):
    """Put a generated body back to what the reference holds."""

    def __init__(self, target: str, body: cst.BaseSuite) -> None:
        self.target = target
        self.body = body
        self.changed = False
        self._stack: list[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._stack.append(node.name.value)
        return True

    def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
        self._stack.pop()
        return updated

    def leave_FunctionDef(
        self, original: cst.FunctionDef, updated: cst.FunctionDef
    ) -> cst.FunctionDef:
        qualified = ".".join([*self._stack, updated.name.value])
        if qualified != self.target:
            return updated

        self.changed = True
        return updated.with_changes(body=self.body)


def _parse_signature(rendered: str) -> tuple[cst.Parameters, cst.Annotation | None]:
    """Turn `(a: int) -> str` back into syntax, by parsing a function that has it."""
    statement = cst.parse_statement(f"def _{rendered}: ...")
    assert isinstance(statement, cst.FunctionDef)
    return statement.params, statement.returns


def _local_name(path: str, module: str) -> str:
    """The name a function is known by inside its own module."""
    return path[len(module) + 1 :] if path.startswith(f"{module}.") else path.rsplit(".", 1)[-1]


# -- applying one ------------------------------------------------------------------


def apply_repair(
    project: Path | str,
    *,
    code: str,
    target: str,
    resolution: str,
    observe: bool = True,
) -> RepairResult:
    """Resolve one divergence the way the caller chose.

    `resolution` has no default, and that is the design. §9's second case has two
    non-equivalent answers and the tool is not entitled to either; making the argument
    required is how "the toolchain does not choose" is enforced rather than intended.
    """
    project = Path(project)
    snapshot = load_snapshot(project)
    if snapshot is None:
        return _refused("there is no reference to repair against; take a snapshot first")

    divergence = next(
        (
            d
            for d in reconcile(snapshot, parse_project(project))
            if d.code == code and target in (d.node, d.location.object)
        ),
        None,
    )
    if divergence is None:
        return _refused(f"no {code} divergence for {target!r}")

    if resolution not in divergence.resolutions:
        offered = ", ".join(divergence.resolutions)
        return _refused(
            f"{resolution!r} is not offered for this divergence; choose one of: {offered}"
        )

    if resolution == Resolution.ACCEPT.value:
        return _accept(project, observe)

    if (code, resolution) not in MECHANICAL:
        return _refused(
            "this divergence has no mechanical repair; hand the request to the agent "
            "(see `request` from list_repairs)"
        )

    return _edit(project, snapshot, divergence, resolution, observe)


def _edit(
    project: Path,
    snapshot: Snapshot,
    divergence: Divergence,
    resolution: str,
    observe: bool,
) -> RepairResult:
    graph = parse_project(project)
    path = divergence.location.file
    module = _module_of(path)
    function_path = f"{module}.{divergence.location.object}"

    previous = snapshot.function(function_path)
    if previous is None:
        return _refused(f"the reference holds nothing for {function_path}")

    local = _local_name(function_path, module)

    if divergence.code == DivergenceCode.SIGNATURE_BROKEN.value:
        params, returns = _parse_signature(previous.signature)
        transformer: cst.CSTTransformer = _RestoreSignature(local, params, returns)
        missing = f"{function_path} was not found where the graph said it was"
    else:
        if previous.body_source is None:
            return _refused(f"the reference holds no body for {function_path}")
        body = cst.parse_statement(f"def _():\n{_indent(previous.body_source)}")
        assert isinstance(body, cst.FunctionDef)
        transformer = _RestoreBody(local, body.body)
        missing = f"{function_path} was not found where the graph said it was"

    write = _apply(project, graph, path, transformer, missing)
    if not write.written:
        return RepairResult(
            applied=False,
            file=write.file,
            refused=write.refused,
            diagnostics=write.diagnostics,
        )

    return _settle(project, observe, file=path)


def _accept(project: Path, observe: bool) -> RepairResult:
    """Take the current state as the new reference. No code is touched."""
    return _settle(project, observe, file=None)


def _settle(project: Path, observe: bool, file: str | None) -> RepairResult:
    """Re-enter the gates, and move the reference only on a both-conditions pass (I-5)."""
    from aibuilder_core.gate import check_graph

    graph = parse_project(project)
    result = check_graph(graph)
    if result.errors:
        return RepairResult(
            applied=file is not None,
            file=file,
            refused="the project still has unresolved errors; the reference was not moved",
            diagnostics=result.errors,
        )

    unproven: tuple[str, ...] = ()
    if observe:
        run = run_observations(graph, project)
        unproven = tuple(
            sorted(node for node, observation in run.observations.items() if not observation.passed)
        )
        if unproven:
            return RepairResult(
                applied=file is not None,
                file=file,
                refused=(
                    "the code parses but does not work yet; the reference stays where it "
                    "was until the observable checks pass"
                ),
                unproven=unproven,
            )

    save_snapshot(take_snapshot(graph), project)
    return RepairResult(applied=True, snapshot_updated=True, file=file)


def _module_of(relative_file: str) -> str:
    parts = Path(relative_file).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _indent(body: str) -> str:
    return "\n".join(f"    {line}" if line.strip() else line for line in body.splitlines())
