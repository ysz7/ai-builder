"""Agent integration: the system prompt, the two inputs, and the record of what it misses.

§3 says the system has two ways to produce code and that they differ **only in how detailed
the request is**. This module is where that is made true rather than asserted: a brief is
assembled the same way for both, out of the same three parts --

1. the **system prompt**, verbatim, which is the only place the markup rules live;
2. the **request**, which is either the user's sentence (input A) or a blueprint's
   specification text plus what they want done with it (input B);
3. the **project as it stands**, so the agent audits before it writes instead of
   regenerating what already works.

The prompt is part 1 in both cases, byte for byte. There is a test that says so, because
the moment a blueprint can change the rules, parseability starts depending on which
blueprint was picked -- and §3's conclusion ("the annotation rules live in the system
prompt, not in the blueprints") stops holding.

**The `kind` registry has one authority.** `kinds.REGISTRY` is it; the prompt's table is
the same list written for the agent to read. `prompt_kinds` reads that table back out so a
test can hold the two together -- a kind is added deliberately, in both places, and never
invented in generated code (Q2).

**The failure log.** Soft-gate mode exists to collect the agent's misses rather than refuse
its output (§7), so the misses have to be written down somewhere or the mode collects
nothing. `record_outcome` appends what the gates said about a generation; `failure_modes`
tallies it. The log is evidence about the agent, in the same way the snapshot is a
reference for diffing: **nothing reads a fact out of it to draw the graph or decide
anything** (I-1). Delete it and the project is unchanged.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from aibuilder_core.catalog import Blueprint, load_blueprint
from aibuilder_core.gate import GateMode
from aibuilder_core.ir import Graph
from aibuilder_core.kinds import REGISTRY, installed_version, technology_of
from aibuilder_core.project import read_project

__all__ = [
    "AGENT_LOG_PATH",
    "PROMPT_FILE",
    "Brief",
    "InputSource",
    "build_brief",
    "failure_modes",
    "prompt_kinds",
    "prompt_path",
    "record_outcome",
    "system_prompt",
]

#: The prompt document, carried as package data. It is not documentation about the system:
#: it is an input the toolchain reads at runtime and a test asserts against, so it ships
#: with the code that reads it rather than living in `docs/`, which is local-only.
PROMPT_FILE = Path("prompts") / "system-prompt-claude-code.md"

#: Appended to, never read from by the graph. Kept beside the snapshot for the same reason:
#: it belongs to the tooling's view of the project, not to the project.
AGENT_LOG_PATH = Path(".aibuilder") / "agent-log.jsonl"


class InputSource(str, Enum):
    """Which of §3's two inputs produced this brief."""

    CHAT = "chat"
    BLUEPRINT = "blueprint"


def prompt_path() -> Path:
    """Where the system prompt is, running from source or frozen.

    Module-relative in both cases: PyInstaller lays the data file out under the package's
    own directory inside the bundle, so one path answers for both. The frozen root is tried
    after it only so a packaging change cannot silently cost the sidecar its rules.

    A missing prompt is a packaging fault and is raised as one. Falling back to a built-in
    string would be worse than failing: the agent would generate against rules nobody can
    read, and the document that fixes the `bp` syntax would stop being the thing in force.
    """
    candidates = [Path(__file__).resolve().parent / PROMPT_FILE]
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(bundled / "aibuilder_core" / PROMPT_FILE)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"the system prompt is missing at {candidates[0]}")


def system_prompt() -> str:
    """The prompt text, verbatim. Identical for both inputs -- that is the whole point."""
    return prompt_path().read_text(encoding="utf-8")


def prompt_kinds(text: str | None = None) -> dict[str, str]:
    """The `kind` table as the prompt states it: kind -> the carrier it names.

    Read back out of the document so a test can hold it against `kinds.REGISTRY`. The
    registry is the authority; this is how we notice the two have drifted, which is the
    only way an agent ends up told about a kind the checker cannot dispatch on.
    """
    table: dict[str, str] = {}
    for line in (text if text is not None else system_prompt()).splitlines():
        stripped = line.strip()
        if not stripped.startswith("| `"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0].strip("`")
        if name in REGISTRY or "." in name:
            table[name] = cells[1]
    return table


# -- the brief -------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeOutline:
    """One existing node, as much of it as the agent needs to audit rather than rebuild."""

    id: str
    kind: str
    title: str | None
    carrier: str
    file: str
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class Brief:
    """One request to the code-generation agent, assembled and ready to send."""

    source: str
    request: str
    system_prompt: str
    instructions: str
    outline: tuple[NodeOutline, ...] = ()
    blueprint: Blueprint | None = None
    project_exists: bool = True
    kinds: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(REGISTRY)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "request": self.request,
            "system_prompt": self.system_prompt,
            "instructions": self.instructions,
            "project_exists": self.project_exists,
            "kinds": list(self.kinds),
            "outline": [
                {
                    "id": node.id,
                    "kind": node.kind,
                    "title": node.title,
                    "carrier": node.carrier,
                    "file": node.file,
                    "members": list(node.members),
                }
                for node in self.outline
            ],
            "blueprint": (
                None
                if self.blueprint is None
                else {
                    "id": self.blueprint.id,
                    "title": self.blueprint.title,
                    "summary": self.blueprint.summary,
                    "path": self.blueprint.path,
                    "section": self.blueprint.section,
                    "text": self.blueprint.text,
                    "carries_markup": self.blueprint.carries_markup,
                }
            ),
        }


def build_brief(
    project: Path | str,
    *,
    request: str | None = None,
    blueprint: str | None = None,
    catalog: Path | str | None = None,
) -> Brief:
    """Assemble the brief for either input.

    `blueprint` names a catalog entry; `request` is what the user actually asked for. Input
    B is the two together -- a blueprint is an accelerator for a request, not a request of
    its own -- but a blueprint with nothing said about it still has an obvious meaning, so
    it is allowed to stand alone.

    Raises `ValueError` when there is nothing to act on, or when the named blueprint is not
    in the catalog. An invented blueprint id must not silently degrade into a chat request:
    the caller asked for a specification and would get an unaccompanied sentence instead.
    """
    text = (request or "").strip()
    if not text and blueprint is None:
        raise ValueError("a brief needs a request, a blueprint, or both")

    loaded: Blueprint | None = None
    if blueprint is not None:
        loaded = load_blueprint(blueprint, catalog)
        if loaded is None:
            raise ValueError(f"no blueprint {blueprint!r} in the catalog")

    root = Path(project)
    exists = root.is_dir()
    outline = _outline(read_project(root)) if exists else ()

    source = InputSource.BLUEPRINT.value if loaded else InputSource.CHAT.value
    return Brief(
        source=source,
        request=text,
        system_prompt=system_prompt(),
        instructions=_instructions(root, text, loaded, outline, exists),
        outline=outline,
        blueprint=loaded,
        project_exists=exists,
    )


def _outline(graph: Graph) -> tuple[NodeOutline, ...]:
    return tuple(
        NodeOutline(
            id=node.id,
            kind=node.kind,
            title=node.title,
            carrier=node.carrier,
            file=node.location.file,
            members=node.members,
        )
        for node in sorted(graph.nodes, key=lambda node: node.id)
    )


def _instructions(
    root: Path,
    request: str,
    blueprint: Blueprint | None,
    outline: tuple[NodeOutline, ...],
    exists: bool,
) -> str:
    """The message body. The rules are not repeated here -- they are in the prompt."""
    parts: list[str] = [f"# Project\n\n{root}"]
    if not exists:
        parts.append("The project directory does not exist yet; you are creating it.")

    parts.append("# What is being asked\n\n" + (request or _default_ask(blueprint)))

    if blueprint is not None:
        parts.append(
            f"# Blueprint: {blueprint.title} ({blueprint.id})\n\n"
            "The text below is a specification: architecture, contracts, failure modes and "
            "a definition of done. It knows nothing about the markup layer, and it is not "
            "where the markup rules come from -- those are in the system prompt you were "
            "given, and they hold identically whether a blueprint is present or not. "
            "Follow the specification for what to build; follow the prompt for how to mark "
            "it up.\n\n"
            f"Source: {blueprint.path}\n\n"
            f"{blueprint.text or ''}"
        )
        if blueprint.carries_markup:
            parts.append(
                "Note: this blueprint's text mentions the markup layer. Ignore that; the "
                "markup rules in force are the ones in the system prompt."
            )

    parts.append(_outline_section(outline, exists))
    parts.append(_registry_section())
    parts.append(
        "# How this will be judged\n\n"
        "The result is parsed into a graph and gated. A node counts as done only when it "
        "both parses and passes its observable check -- a decorator in the right place "
        "over code that does not run is a failure, not a partial success. Anything the "
        "gate flags comes back to you as an addressed repair request."
    )
    return "\n\n".join(parts)


def _default_ask(blueprint: Blueprint | None) -> str:
    title = blueprint.title if blueprint else "the request"
    return f"Apply the blueprint below to this project: {title}."


def _outline_section(outline: tuple[NodeOutline, ...], exists: bool) -> str:
    header = (
        "# The project as it stands\n\n"
        "Audit this before proposing anything. Existing working code stays; replacing "
        "something that works needs a stated reason. Node ids are already taken."
    )
    if not exists:
        return header + "\n\nNothing yet."
    if not outline:
        return header + "\n\nNo nodes yet: the project carries no markup the parser can see."

    lines = [
        f"- {node.id} ({node.kind}) -- {node.carrier} in {node.file}"
        + (f", members: {', '.join(node.members)}" if node.members else "")
        for node in outline
    ]
    return header + "\n\n" + "\n".join(lines)


def _registry_section() -> str:
    """The registry, from the registry. The prompt states it too; this is the live copy."""
    lines = [
        f"- `{kind.name}` -- {kind.description} Checked by: {kind.check}."
        for kind in sorted(REGISTRY.values(), key=lambda kind: kind.name)
    ]
    return (
        "# The `kind` registry\n\n"
        "Every node's `kind` comes from this list. If what you are building fits none of "
        "them, say so instead of inventing a value -- a new kind is added to the registry "
        "deliberately, and an unregistered one is a gate diagnostic.\n\n" + "\n".join(lines)
    )


# -- the failure log -------------------------------------------------------------------


def record_outcome(
    project: Path | str,
    *,
    source: str,
    request: str = "",
    blueprint: str | None = None,
    observe: bool = False,
) -> dict[str, Any]:
    """Run the gates over what the agent produced and append what they said.

    Soft mode deliberately: this is the phase's collection mechanism, and a mode that
    refused the code would collect one failure and then nothing (§7). `observe` also runs
    the observable checks, so a node that parses but does not work is recorded as what it
    is rather than as a pass.
    """
    from aibuilder_core.api import read_graph  # imported here: api assembles, agent supplies

    root = Path(project)
    result = read_graph(root, mode=GateMode.SOFT, observe=observe)

    entry: dict[str, Any] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "blueprint": blueprint,
        "request": request,
        "observed": observe,
        "diagnostics": [
            {
                "code": diagnostic["code"],
                "severity": diagnostic["severity"],
                "rule": diagnostic["rule"],
                "node": diagnostic["node"],
                "address": (
                    f"{diagnostic['location']['file']}:"
                    f"{diagnostic['location']['start_line']} "
                    f"{diagnostic['location']['object']}"
                ),
            }
            for diagnostic in result["diagnostics"]
        ],
        "verdicts": result["verdicts"],
        "accepted": result["accepted"],
        # What the project was built against, for the technologies whose internals our
        # checks read. Recorded with the outcome so a failure mode that arrives with an
        # upgrade can be seen to have arrived with an upgrade.
        "versions": _versions(result["graph"]["nodes"]),
    }

    path = root / AGENT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")

    return entry


def _versions(nodes: list[dict[str, Any]]) -> dict[str, str | None]:
    """The installed versions of the technologies this graph uses, or `None` if absent.

    Read in the toolchain's own environment, which in v0 is also the one the checks run in.
    When the two come apart -- a project with its own interpreter -- this has to be read
    where the project lives, not here.
    """
    distributions = {
        technology.distribution
        for node in nodes
        if (technology := technology_of(str(node.get("kind", "")))) is not None
    }
    return {name: installed_version(name) for name in sorted(distributions)}


def failure_modes(project: Path | str) -> dict[str, Any]:
    """What the agent gets wrong, tallied over every recorded generation.

    The list P9 works from. It is a summary of the log and of nothing else -- no part of it
    is consulted when the graph is drawn or when a repair is decided.
    """
    entries = _read_log(Path(project))

    counts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for diagnostic in entry.get("diagnostics", []):
            code = str(diagnostic.get("code"))
            tally = counts.setdefault(
                code,
                {
                    "code": code,
                    "count": 0,
                    "rule": diagnostic.get("rule", ""),
                    "severity": diagnostic.get("severity", ""),
                    "addresses": [],
                },
            )
            tally["count"] += 1
            address = diagnostic.get("address")
            if address and address not in tally["addresses"]:
                tally["addresses"].append(address)

    # Counted as clean when nothing was flagged at error severity -- not from the gate's
    # `accepted`, which is true of every soft-mode run by construction and would report a
    # project full of errors as a run of successes.
    return {
        "generations": len(entries),
        "clean": sum(1 for entry in entries if not _errors_in(entry)),
        "codes": sorted(counts.values(), key=lambda item: (-int(item["count"]), str(item["code"]))),
    }


def _errors_in(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        diagnostic
        for diagnostic in entry.get("diagnostics", [])
        if diagnostic.get("severity") == "error"
    ]


def _read_log(project: Path) -> list[dict[str, Any]]:
    """Every entry that is still readable. A corrupt line is skipped, never fatal --
    a truncated append must not cost the whole record."""
    path = project / AGENT_LOG_PATH
    if not path.is_file():
        return []

    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries
