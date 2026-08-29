"""Using what was built: documents into a pipeline, and the project's own commands (P17).

Two verbs and one refusal shape, and the refusals are what the phases are actually about.

* **Indexing is an action on a node** (Q18), dispatched by **kind**. A verb that ran
  whatever happened to be callable would construct something and call it an index -- the
  failure mode this codebase minds most, a button that appears to work.
* **What it reports is what the store said afterwards**, never the documents that went in.
  Counting our own side of the exchange and printing it as the store's answer is the one
  thing this verb must not do.
* **A front end is run, not modelled** (Q20). Nothing here goes on the graph, nothing turns
  a colour, and the commands are **asked of npm** rather than read out of `package.json` --
  a parser for somebody else's format is a second opinion about a thing that already has a
  first one (§5.8).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from test_api import validate, wire_form

from framestack_core.api import (
    COMMAND_LIST_SCHEMA,
    RAG_INDEX_SCHEMA,
    RUN_SCHEMA,
    command_list,
    command_logs,
    command_start,
    command_state,
    command_stop,
    rag_index,
)
from framestack_core.kinds import REGISTRY
from framestack_core.runner import COMMAND_STATE_PATH, project_commands

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
PIPELINE = EXAMPLES / "rag-pipeline"


# -- handing a pipeline its documents (P17.5) -------------------------------------


def test_the_pipeline_indexes_and_reports_what_the_store_said() -> None:
    answered = rag_index(PIPELINE, "rag")

    assert answered["ok"] is True
    assert answered["status"] == "green"
    # The store's own type, because that is what the store said. The number of documents
    # the corpus holds appears nowhere: it is our side of the exchange, not the store's.
    assert "InMemoryVectorStore" in answered["detail"]
    assert "3" not in answered["detail"]


def test_a_kind_that_holds_no_index_is_refused_rather_than_tried() -> None:
    """P17.2's rule with a different verb: dispatch by kind, never by what a carrier looks
    like. `Chunker` is callable, and calling it would build a chunker and call it an index."""
    refused = rag_index(PIPELINE, "rag.chunking")

    assert refused["ok"] is False
    assert refused["status"] == "unproven"
    assert "holds no index" in refused["detail"]


def test_a_node_that_is_not_there_is_named_in_the_refusal(tmp_path: Path) -> None:
    refused = rag_index(PIPELINE, "no.such.node")

    assert refused["ok"] is False
    assert "no node called no.such.node" in refused["detail"]


def test_only_the_kinds_that_named_a_way_in_hold_an_index() -> None:
    """A kind opts in by naming one; a kind that has not shows no button at all."""
    holding = {name for name, kind in REGISTRY.items() if kind.indexes}

    assert holding == {"rag.pipeline"}


def test_indexing_answers_in_the_shape_it_declares() -> None:
    validate(wire_form(rag_index(PIPELINE, "rag")), RAG_INDEX_SCHEMA)


def test_indexing_is_a_method_in_the_core() -> None:
    """The extension point is `HANDLERS`, never a new command in the Rust shell."""
    from framestack_core.handlers import dispatch

    assert dispatch("rag.index", {"project": str(PIPELINE), "node": "rag"})["ok"] is True


# -- the commands the project already has, and running one (P17.6, P17.7) ---------


@pytest.fixture
def with_commands(tmp_path: Path) -> Path:
    """A project that declares two commands, one of which ends and one of which stays."""
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "front",
                "private": True,
                "scripts": {
                    "serve": 'node -e "setInterval(() => {}, 1000)"',
                    "broken": 'node -e "process.exit(3)"',
                },
            }
        ),
        encoding="utf-8",
    )
    try:
        yield tmp_path
    finally:
        command_stop(tmp_path)


needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed")


@needs_npm
def test_the_commands_are_asked_of_npm_not_read_out_of_the_file(with_commands: Path) -> None:
    """§5.8. What `package.json` says is npm's to answer, and it answers in JSON."""
    listed = project_commands(with_commands)

    assert listed.ok
    assert dict(listed.commands).keys() == {"serve", "broken"}


@needs_npm
def test_a_project_with_no_commands_says_so_rather_than_failing(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "bare", "private": true}', encoding="utf-8")

    listed = project_commands(tmp_path)

    assert listed.ok is True
    assert listed.commands == ()


def test_nothing_outside_the_project_can_be_asked(tmp_path: Path) -> None:
    """The directory is passed in, so it is also checked: a verb that would run npm in
    somebody's home directory because a string said so is not a verb, it is a shell."""
    refused = project_commands(tmp_path, "../..")

    assert refused.ok is False
    assert "no directory" in refused.detail


@needs_npm
def test_a_command_starts_is_found_again_and_stops(with_commands: Path) -> None:
    started = command_start(with_commands, "serve")

    assert started["ok"] is True, started["detail"]
    assert started["state"]["target"] == "npm run serve"
    # Recorded on disk, so a crashed session leaves something the next one can stop.
    assert (with_commands / COMMAND_STATE_PATH).is_file()

    assert command_state(with_commands)["ok"] is True
    assert command_stop(with_commands)["ok"] is True
    assert command_state(with_commands)["ok"] is False
    assert not (with_commands / COMMAND_STATE_PATH).is_file()


@needs_npm
def test_a_command_that_fell_over_is_reported_with_its_output(with_commands: Path) -> None:
    started = command_start(with_commands, "broken")

    assert started["ok"] is False
    assert "exited immediately" in started["detail"]
    assert not (with_commands / COMMAND_STATE_PATH).is_file()


@needs_npm
def test_a_declared_name_still_means_the_projects_own_command(with_commands: Path) -> None:
    """The project's vocabulary wins over the shell's.

    P17.7 refused everything else; Q22 lifted that, and this is the half of it that stays: a
    name npm just said exists runs `npm run <name>`, so pressing `serve` in the list cannot
    be turned into something else by a file of that name appearing on the path.
    """
    started = command_start(with_commands, "serve")

    assert started["ok"] is True, started["detail"]
    assert started["state"]["target"] == "npm run serve"
    command_stop(with_commands)


def test_a_command_the_project_never_declared_runs(tmp_path: Path) -> None:
    """P17.7's rule, removed deliberately (Q22).

    It said a verb that ran an arbitrary string would be a shell with a button on it. True,
    and no longer an objection: this application has a real shell in it on purpose, and
    **nothing this verb starts goes on the graph** (Q20), so there is no claim for a command
    nobody declared to falsify. What it bought instead was a person unable to run their own
    test suite from the panel that lists their commands.
    """
    ran = command_start(tmp_path, "echo not-declared-anywhere")

    assert ran["ok"] is True, ran["detail"]
    assert "not-declared-anywhere" in ran["logs"]


def test_a_command_that_finishes_is_not_a_command_that_failed(tmp_path: Path) -> None:
    """`git status` is supposed to end. Reporting a zero exit as a fall-over was the panel
    calling a successful command broken."""
    finished = command_start(tmp_path, "true")
    fell_over = command_start(tmp_path, "exit 3")

    assert finished["ok"] is True
    assert "finished" in finished["detail"]
    assert fell_over["ok"] is False
    assert "exited immediately (3)" in fell_over["detail"]


def test_a_command_still_cannot_reach_outside_the_project(tmp_path: Path) -> None:
    """The one rule that stays, and it is a different rule: containment, not vocabulary.

    `command.*` is a verb about *this* project, and a directory outside it would make it a
    way to run things in somebody's home directory instead.
    """
    refused = command_start(tmp_path, "echo hello", "../..")

    assert refused["ok"] is False
    assert "no directory" in refused["detail"]


def test_an_empty_command_is_refused_rather_than_run(tmp_path: Path) -> None:
    assert command_start(tmp_path, "   ")["ok"] is False


@needs_npm
def test_output_is_polled_with_an_offset_the_caller_keeps(with_commands: Path) -> None:
    """P13, and the fourth process follows it like the other three."""
    command_start(with_commands, "serve")
    first = command_logs(with_commands)
    again = command_logs(with_commands, first["offset"])
    command_stop(with_commands)

    assert first["ok"] is True
    assert again["logs"] == ""
    assert again["offset"] == first["offset"]


def test_nothing_is_running_before_anything_was_started(tmp_path: Path) -> None:
    """P11: a read never starts a process, and 'not running' is a result, not a fault."""
    assert command_state(tmp_path)["ok"] is False
    assert command_stop(tmp_path)["ok"] is False
    assert not (tmp_path / COMMAND_STATE_PATH).is_file()


@needs_npm
def test_the_command_payloads_match_the_declared_contract(with_commands: Path) -> None:
    validate(wire_form(command_list(with_commands)), COMMAND_LIST_SCHEMA)
    validate(wire_form(command_start(with_commands, "serve")), RUN_SCHEMA)
    validate(wire_form(command_state(with_commands)), RUN_SCHEMA)
    validate(wire_form(command_logs(with_commands)), RUN_SCHEMA)
    validate(wire_form(command_stop(with_commands)), RUN_SCHEMA)


@needs_npm
def test_the_command_verbs_are_methods_in_the_core(with_commands: Path) -> None:
    """The extension point is `HANDLERS`, never a new command in the Rust shell."""
    from framestack_core.handlers import dispatch

    assert dispatch("command.list", {"project": str(with_commands)})["ok"] is True


def test_a_front_end_is_not_on_the_graph(with_commands: Path) -> None:
    """Q20, asserted rather than trusted: running something must not model it."""
    from framestack_core.api import read_graph

    before = read_graph(with_commands)["graph"]["nodes"]
    command_list(with_commands)

    assert read_graph(with_commands)["graph"]["nodes"] == before
