"""Claiming a node as a member of a group is a write into the group's declaration (Q35).

The verb exists because of a wall P20 put there on purpose. `blueprint.insert` writes whole
files and **nothing else** -- no post-insert hook, ever -- but a node it lands is unclaimed,
and the top level holds groups only (I-3, §5.1). So a clicked catalog entry produces a node
the gate rejects until something adds it to a group's `members`, and that something must be
a second press rather than a hidden step of the first.

What these tests hold down is that it stays the *narrow* verb it was introduced as: one
parent per node, groups only, and an edit that touches the members list and nothing around
it. The last of those is not fussiness -- `members=` is the one keyword a person writes
prose around, and the reference project has a comment inside that list.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from framestack_core.gate import check_graph
from framestack_core.parser import parse_project
from framestack_core.writer import claim_member

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "fastapi-service"

#: A consumed server, dropped in unclaimed -- which is exactly the state an insert leaves.
SERVER = '''"""A consumed MCP server, as a catalog entry would land it."""

from typing import Annotated

from bp import Param, generated, node


@node(id="gmail", kind="mcp.server", title="Gmail MCP Server")
class GmailServer:
    """Connection knobs for the Gmail MCP server."""

    command: Annotated[str, Param(label="Command")] = "npx"
    token_env: Annotated[str, Param(label="Credentials env var")] = "GMAIL_MCP_CREDENTIALS"

    @generated()
    def connect(self) -> object:
        # GENERATED.
        return object()
'''


@pytest.fixture
def landed(tmp_path: Path) -> Path:
    """The example with an unclaimed node in it, and the gate already unhappy about it."""
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project)
    (project / "app" / "gmail.py").write_text(SERVER, encoding="utf-8")
    return project


def test_an_unclaimed_node_is_rejected_until_it_is_claimed(landed: Path) -> None:
    """The wall itself, stated first: this is what the verb is for.

    Written as one test over both states rather than two, because the point is the
    transition -- an insert on its own leaves a project the gate rejects, and the claim is
    what makes it whole.
    """
    before = check_graph(parse_project(landed))
    assert [d.code for d in before.errors] == ["node.top_level_not_group"]

    assert claim_member(landed, "api", "gmail").written is True

    after = check_graph(parse_project(landed))
    assert after.errors == ()


def test_the_claim_edits_the_members_list_and_leaves_the_prose_alone(landed: Path) -> None:
    """`libcst` was chosen so a write touches its own syntax node and nothing else.

    The reference's `members=[...]` has a comment above it explaining why the routes are
    not listed. Rebuilding the list to add one element would delete it, and nobody would
    notice until they went looking for the explanation.
    """
    declaration = landed / "app" / "api" / "__node__.py"
    before = declaration.read_text(encoding="utf-8")

    claim_member(landed, "api", "gmail")
    after = declaration.read_text(encoding="utf-8")

    assert "members=[health, users_router, ApiSettings, GmailServer]" in after
    assert "every node has exactly one parent" in after  # the comment inside the call
    # An import, because members are object references and never strings.
    assert "from app.gmail import GmailServer" in after
    # And nothing else moved: one added import line, one changed members line.
    changed = [line for line in after.splitlines() if line not in before.splitlines()]
    assert len(changed) == 2


def test_a_node_keeps_one_parent(landed: Path) -> None:
    """I-3, enforced as a refusal that names the existing parent.

    Without it the write would succeed and the gate would then reject the project for
    `node.multiple_parents` -- a write whose only outcome is a diagnostic. Moving a node
    between groups is a different intention, and a verb that did both would do the second
    by accident.
    """
    refused = claim_member(landed, "api", "health")

    assert refused.written is False
    assert "already" in (refused.refused or "")
    assert "api" in (refused.refused or "")


def test_only_a_group_holds_members(landed: Path) -> None:
    """A `members=` on something that is not a group makes two invalid nodes, not one."""
    refused = claim_member(landed, "health", "gmail")

    assert refused.written is False
    assert "not a group" in (refused.refused or "")


def test_a_claim_that_would_break_the_gate_is_undone(landed: Path) -> None:
    """The same rule every write here follows, and the reason it is shared code.

    Exercised through a member whose carrier the group's module cannot import by name.
    Whatever the cause, the file on disk must come back unchanged rather than being left
    in the state that failed.
    """
    declaration = landed / "app" / "api" / "__node__.py"
    before = declaration.read_text(encoding="utf-8")

    refused = claim_member(landed, "api", "no.such.node")

    assert refused.written is False
    assert declaration.read_text(encoding="utf-8") == before


def test_nothing_records_that_a_claim_happened(landed: Path) -> None:
    """I-1: the code is the only source of truth, and membership is in the code.

    The git diff is the record. A note somewhere saying "gmail was claimed on Tuesday"
    would be a second store of a fact the declaration already holds, and the two would
    disagree the first time somebody edited the file by hand.
    """
    state = landed / ".framestack"
    before = sorted(one.name for one in state.iterdir()) if state.is_dir() else []

    claim_member(landed, "api", "gmail")

    after = sorted(one.name for one in state.iterdir()) if state.is_dir() else []
    # The snapshot moves because the write stood -- that is a diff reference, not a record
    # of this verb (I-6). Nothing else appears, and nothing new is created besides it.
    assert set(after) - set(before) <= {"snapshot.json"}
