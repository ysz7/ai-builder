#!/usr/bin/env python3
"""Rebuild the bundled catalog's `files/` subtrees from `examples/` (P20, Q30).

An entry is **authored, not copied** -- it is a subtree somebody chose, curated to drop
into a project that does not already have it, because a whole example project collides with
any real project on its first path. What this script does is the mechanical half: carry the
chosen paths across so that one edit to an example does not have to be made twice.

`blueprint.md` is hand-written and this script never touches it. Neither does it decide what
an entry contains: `ENTRIES` below is the curation, and changing it is a decision.

Run it after changing an example, then run the test suite -- every bundled entry is planned
and inserted into an empty project there, and the gate has to accept the result. That is
what holds the two in step; there is deliberately no byte-equality check, because what
anybody needs to know is that an entry is *valid*, not that it is *identical* (Q30).

    uv run python scripts/build-blueprints.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
CATALOG = ROOT / "packages/core/src/framestack_core/blueprints"

#: What each entry carries, and from where. The paths are relative to the example project
#: and land at the same relative path in the target project.
ENTRIES: dict[str, dict[str, object]] = {
    "fastapi-service": {
        "title": "FastAPI service",
        "description": "A service, its routers, its routes and its settings, with tests.",
        "source": "fastapi-service",
        "carry": ["app", "tests/test_api.py", "conftest.py"],
    },
    "langgraph-agent": {
        "title": "LangGraph agent",
        "description": "An agent as a group over its state, steps and routers, with tests.",
        "source": "langgraph-agent",
        "carry": ["agent", "tests/test_agent.py", "conftest.py"],
    },
    "rag-pipeline": {
        "title": "RAG pipeline",
        "description": "Four stages with their knobs on the stages themselves, with tests.",
        "source": "rag-pipeline",
        "carry": ["rag", "tests/test_pipeline.py", "conftest.py"],
    },
    "mcp-agent": {
        "title": "MCP agent and server",
        "description": "All three MCP roles at once: a server exposed, consumed, and bound.",
        "source": "mcp-agent",
        "carry": ["agent", "server", "tests/test_agent.py", "tests/test_server.py", "conftest.py"],
    },
}

#: Never carried, whatever a `carry` entry sweeps up. `__pycache__` is a build artifact and
#: `.framestack` is tooling state -- and an entry may not write into it in any case.
SKIP = {"__pycache__", ".framestack", ".venv", ".pytest_cache"}


def carry(source: Path, files: Path, relative: str) -> int:
    """Copy one carried path, landing it at the same relative path it had in the example."""
    if source.is_file():
        destination = files / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return 1

    written = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or set(path.parts) & SKIP:
            continue
        destination = files / relative / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        written += 1
    return written


def main() -> None:
    section = CATALOG / "blueprints"
    items = []
    for entry_id, entry in ENTRIES.items():
        directory = section / entry_id
        files = directory / "files"
        # Only `files/` is rebuilt. `blueprint.md` beside it is written by a person.
        if files.exists():
            shutil.rmtree(files)

        example = EXAMPLES / str(entry["source"])
        total = 0
        for relative in entry["carry"]:  # type: ignore[union-attr]
            source = example / str(relative)
            if not source.exists():
                raise SystemExit(f"{entry_id}: {relative} is not in {example}")
            total += carry(source, files, str(relative))

        document = directory / "blueprint.md"
        if not document.is_file():
            raise SystemExit(f"{entry_id}: no blueprint.md — an entry is text as well as code")
        print(f"{entry_id}: {total} files")
        items.append({"id": entry_id, "title": entry["title"], "description": entry["description"]})

    (CATALOG / "catalogue.json").write_text(
        json.dumps({"items": items}, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
