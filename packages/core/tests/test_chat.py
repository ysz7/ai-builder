"""The chat, as four narrow commands and no free-form write path (Phase 4).

The claim under test is **structural**, not textual: there is no code path that sends a
person's words to the agent without exactly one command's prompt in front of them. So most
of what is checked here is what `send` refuses to do — dispatch when it is unsure, dispatch a
command it does not have, or reach the agent at all when a question is still unanswered.

Nothing here calls a model. The classifier is a subprocess and is replaced where it is in the
way; a test suite that spent somebody's tokens to prove a dispatcher works would be exactly
the kind of check the observer refuses to trust.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from contract import validate, wire_form

from framestack_core import chat
from framestack_core.api import (
    CHANGES_SCHEMA,
    CHAT_CHOICES_SCHEMA,
    CHAT_SCHEMA,
    chat_changes,
    chat_choices,
    chat_send,
)
from framestack_core.chat import (
    COMMANDS,
    STACKS,
    TYPED,
    _kind_in,
    blocks,
    prompt_for,
    remember_stack,
    send,
    stack_of,
)
from framestack_core.handlers import HANDLERS

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "reference"


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))
    return root


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture what would reach the agent instead of starting one.

    The seam is `session.say`, which is the one door: if a message could reach the agent
    without going through it, this fixture would see nothing and the tests would still pass —
    so `test_there_is_no_other_way_to_reach_the_agent` checks the door itself.
    """
    seen: list[dict[str, Any]] = []

    def fake(root: Any, text: str, images: Any = (), said: Any = None) -> Any:
        seen.append({"text": text, "said": said, "images": images})

        class Answer:
            ok = True
            detail = "sent"

        return Answer()

    monkeypatch.setattr(chat, "say", fake)
    return seen


@pytest.fixture
def label(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make the classifier answer whatever a test wants, without spending a token."""

    def choose(answer: str) -> None:
        monkeypatch.setattr(chat, "classify", lambda project, text: answer)

    return choose


# -- the prompts --------------------------------------------------------------------------


def test_a_turn_carries_the_base_and_exactly_one_command() -> None:
    """Never more than two files.

    An agent holding all four sets of instructions at once is back to choosing between them,
    which is the thing the dispatch exists to do instead.
    """
    built = prompt_for("add-system")

    assert "must export  run(message: str, **kw) -> str" in built  # the base
    assert "Create a new system package" in built  # its own file
    assert "Add a tool function" not in built
    assert "You are given the output of a failing check" not in built


def test_every_command_has_a_prompt_that_ships() -> None:
    """A prompt missing from the build fails as an agent given no instructions.

    That is the worst way for this to break — the turn goes through, the code comes back
    wrong, and nothing anywhere says a file was missing. So it is checked as a build fact.
    """
    for command in COMMANDS:
        assert prompt_for(command).strip(), command


def test_no_prompt_names_a_symbol_the_rebuild_deleted() -> None:
    """Appendix A.7, as far as it can be tested mechanically.

    The list there is mostly about *instructions* — write a manifest, place a node, define
    execution order — and those are judgement calls a test cannot make. The five names are
    not: they are the annotation layer, and a prompt that mentions one has drifted back
    towards the design this rebuild exists to undo. Checked because it is the half a person
    cannot notice by reading a diff of a text file.
    """
    forbidden = ("@node", "@editable", "@generated", "group_node", "Param")
    for path in sorted(chat.PROMPTS.glob("*.txt")):
        body = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in body, f"{path.name} says {word!r}"


def test_the_base_forbids_a_manifest_rather_than_asking_for_one() -> None:
    """The other half of A.7's manifest rule, stated the way the prompt states it."""
    base = prompt_for("question")

    assert "Never create or modify a manifest" in base
    assert "The structure is the directory layout." in base


def test_the_reference_records_a_stack_for_every_kind(tmp_path: Path) -> None:
    """A project that has answered already is never asked again — read from a real `.env`."""
    root = project(tmp_path)

    assert {kind: stack_of(root, kind) for kind in STACKS} == {
        "agent": "plain",
        "rag": "chroma",
        "api": "fastapi",
        "worker": "arq",
    }


# -- dispatch ------------------------------------------------------------------------------


def test_a_typed_command_is_never_classified(
    tmp_path: Path, sent: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person who typed the command has already answered the question."""
    monkeypatch.setattr(
        chat, "classify", lambda project, text: pytest.fail("the classifier was asked")
    )
    root = project(tmp_path)
    remember_stack(root, "rag", "qdrant")

    answer = send(root, "/add-system rag")

    assert answer.command == "add-system"
    assert answer.sent is True
    assert len(sent) == 1


def test_the_agent_never_sees_a_message_without_a_command_in_front_of_it(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    """The structural claim of the whole phase, stated as one assertion."""
    label("question")

    send(project(tmp_path), "what does the worker do?")

    assert sent[0]["text"].startswith("You write ordinary, production-quality Python")
    assert "Answer the user's question about this project. Write nothing." in sent[0]["text"]
    assert sent[0]["text"].endswith("what does the worker do?")


def test_the_transcript_keeps_what_the_person_typed(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    """The agent gets the whole thing; the record keeps their words.

    A transcript that showed the prompt would open every exchange with two pages of
    instructions the person did not write, which is a conversation nobody can read back.
    """
    label("question")

    send(project(tmp_path), "what does the worker do?")

    assert sent[0]["said"] == "what does the worker do?"
    assert sent[0]["said"] != sent[0]["text"]


def test_an_unsure_classification_asks_rather_than_guessing(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    """A wrong command writes the wrong files, and the person is right there to be asked."""
    label("unsure")

    answer = send(project(tmp_path), "hmm")

    assert answer.sent is False
    assert answer.asking == "command"
    assert set(answer.choices) == set(COMMANDS)
    assert sent == []


def test_the_answer_to_that_question_dispatches_without_asking_again(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    label("unsure")
    root = project(tmp_path)

    answer = send(root, "hmm", command="repair")

    assert answer.command == "repair"
    assert answer.sent is True
    assert "Fix only what that check covers." in sent[0]["text"]


def test_a_command_this_build_does_not_have_is_refused(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    answer = send(project(tmp_path), "do the thing", command="deploy-everything")

    assert answer.ok is False
    assert answer.sent is False
    assert sent == []


def test_an_empty_message_reaches_nobody(tmp_path: Path, sent: list[dict[str, Any]]) -> None:
    assert send(project(tmp_path), "   ").ok is False
    assert sent == []


def test_a_project_that_is_not_there_is_a_result_and_not_a_crash(tmp_path: Path) -> None:
    assert send(tmp_path / "nowhere", "anything").ok is False


def test_there_is_no_other_way_to_reach_the_agent() -> None:
    """`agent.say` is **gone**, not discouraged. This is the phase's structural claim.

    A verb that sent whatever it was handed is a free-form write path, and a rule enforced by
    a prompt is a rule the next caller breaks by accident. What the webview can reach is the
    method table, so the method table is where the path had to stop existing.
    """
    assert "chat.send" in HANDLERS
    assert "agent.say" not in HANDLERS
    assert not any(name.endswith(".say") for name in HANDLERS)


def test_a_pasted_picture_still_reaches_the_agent(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    """Deleting the free-form path must not quietly delete what it carried.

    A person pasting a screenshot into the chat is how half of `/repair` starts, and losing
    it would be a feature removed under cover of an architectural change.
    """
    label("question")
    picture = ({"media_type": "image/png", "data": "aGk="},)

    send(project(tmp_path), "what is wrong here?", images=picture)

    assert sent[0]["images"] == picture


# -- the stack preference ---------------------------------------------------------------------


def test_the_stack_is_asked_for_once_and_written_into_env(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    """Recorded where the person can see it, change it, and take it with them.

    A preference kept anywhere else would be one the project could not explain about itself —
    and `.env` is already a node on the canvas, so it is somewhere they are looking.
    """
    root = project(tmp_path)
    # A project that has not answered yet. The reference ships with all four recorded, which
    # is what the test above checks; this one is about the first time somebody is asked.
    (root / ".env").write_text("API_GREETING=hello\n", encoding="utf-8")

    asked = send(root, "/add-system rag")
    assert asked.sent is False
    assert asked.asking == "stack"
    assert asked.choices == STACKS["rag"]
    assert sent == []

    answered = send(root, "/add-system rag", stack="qdrant")
    assert answered.sent is True
    assert stack_of(root, "rag") == "qdrant"
    assert "Use the qdrant stack." in sent[0]["text"]

    again = send(root, "/add-system rag")
    assert again.sent is True
    assert len(sent) == 2


def test_a_stack_that_is_not_one_of_the_kind_s_is_refused(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    """The list is short and known. Passing an unknown one through would generate anything."""
    answer = send(project(tmp_path), "/add-system rag", stack="langgraph")

    assert answer.ok is False
    assert sent == []


def test_recording_a_stack_leaves_the_rest_of_env_exactly_as_it_was(tmp_path: Path) -> None:
    """The same promise the settings writer makes about a `.py`, kept for a text file."""
    root = project(tmp_path)
    written = "# what the reference needs\nAPI_GREETING=hello\n\n# a blank line above\n"
    (root / ".env").write_text(written, encoding="utf-8")

    remember_stack(root, "agent", "plain")

    assert (root / ".env").read_text(encoding="utf-8") == (
        written.rstrip("\n") + "\nFRAMESTACK_DEFAULT_STACK_AGENT=plain\n"
    )


def test_recording_a_stack_twice_replaces_the_line_rather_than_repeating_it(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    remember_stack(root, "agent", "plain")
    remember_stack(root, "agent", "langgraph")

    body = (root / ".env").read_text(encoding="utf-8")
    assert body.count("FRAMESTACK_DEFAULT_STACK_AGENT") == 1
    assert stack_of(root, "agent") == "langgraph"


def test_a_recorded_stack_that_is_not_a_known_one_is_ignored(tmp_path: Path) -> None:
    """A hand-edited `.env` is a person's file. A value we do not know is not one we use."""
    root = project(tmp_path)
    (root / ".env").write_text("FRAMESTACK_DEFAULT_STACK_RAG=homegrown\n", encoding="utf-8")

    assert stack_of(root, "rag") == ""


def test_a_message_that_names_no_kind_is_left_to_the_agent(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    """Working out that "retrieval over our docs" means `rag` is not this module's job.

    A table of synonyms here would be a kind registry with a different name, which is the
    thing the rebuild deleted. The prompt tells the agent to ask; nothing is invented.
    """
    label("add-system")

    answer = send(project(tmp_path), "I want retrieval over our documents")

    assert answer.sent is True
    assert "stack" not in answer.asking


# -- what changed ------------------------------------------------------------------------------


def test_changes_are_asked_of_git(tmp_path: Path) -> None:
    root = project(tmp_path)
    for line in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "before"],
    ):
        subprocess.run(["git", *line], cwd=root, check=True, capture_output=True)  # noqa: S603, S607
    (root / "rag" / "settings.py").write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class RagSettings(BaseSettings):\n    top_k: int = 9\n",
        encoding="utf-8",
    )

    answer = chat.changes(root)

    assert answer.ok is True
    assert answer.files == ("rag/settings.py",)
    assert "top_k: int = 9" in answer.diff


def test_a_project_outside_git_is_told_so_rather_than_failing(tmp_path: Path) -> None:
    """Plenty of projects are not under version control, and the chat still works in them."""
    answer = chat.changes(project(tmp_path))

    assert answer.ok is False
    assert "git repository" in answer.detail
    assert answer.diff == ""


def test_nothing_here_runs_the_tests(tmp_path: Path) -> None:
    """Observe is **offered** after a write, never run (P11).

    A graph that re-ran its own tests after every edit would be one whose colours nobody
    could tie to a commit — which is the failure this whole design is arranged against.
    """
    root = project(tmp_path)

    chat.changes(root)

    assert not (root / ".framestack" / "observation.json").exists()


# -- the payload ---------------------------------------------------------------------------------


def test_every_verb_matches_the_declared_contract(
    tmp_path: Path, sent: list[dict[str, Any]], label: Any
) -> None:
    root = project(tmp_path)
    label("question")

    validate(wire_form(chat_choices()), CHAT_CHOICES_SCHEMA)
    validate(wire_form(chat_send(root, "what is this?")), CHAT_SCHEMA)
    validate(wire_form(chat_send(root, "/add-system rag")), CHAT_SCHEMA)
    validate(wire_form(chat_changes(root)), CHANGES_SCHEMA)


# -- what the palette sends (Phase 7) --------------------------------------------------------


def test_every_block_the_palette_can_draw_parses_as_the_command_it_names() -> None:
    """The one seam where the palette and the core could drift apart.

    The palette draws its blocks from `chat.choices` and turns each press into a typed
    message. Nothing checks that string on the way through — a typed command that failed to
    parse would fall through to the classifier and be *guessed at*, which is the one thing
    the dispatcher exists to avoid. So the strings it can produce are asserted here, against
    the same parser that will read them.
    """
    for kind, stacks in STACKS.items():
        chosen = [f"/add-system {kind} --stack {one}" for one in stacks]
        for text in (f"/add-system {kind}", *chosen):
            typed = TYPED.match(text)
            assert typed is not None, text
            assert typed.group(1) == "add-system", text
            assert typed.group(1) in COMMANDS, text
            # The kind has to survive the trip, or the agent is told to write "a system".
            assert _kind_in(text) == kind, text

            wanted = re.search(r"--stack\s+([a-z0-9-]+)", typed.group(2))
            if "--stack" in text:
                assert wanted is not None and wanted.group(1) in stacks, text
            else:
                # No `--stack` is a real answer: it lets the project's own `.env` preference
                # win, which is why the palette offers "this project's default" at all.
                assert wanted is None, text


def test_every_declared_block_names_a_command_that_ships_with_a_prompt() -> None:
    """A block is a promise that a press starts a turn the agent understands.

    Two ways for that to be false, and both are checked here: a block naming a command the
    dispatcher does not have, and a command whose prompt is missing from the build. The
    second is the one that would survive review — the prompts are data files, and a data
    file is exactly the kind of thing that gets added to the repository and not to the
    package.
    """
    declared = blocks()
    assert declared, "a build with no blocks has an empty palette"

    for block in declared:
        assert block.command in COMMANDS, block.command
        assert prompt_for(block.command).strip(), block.command
        # A kind block is drawn as the node it will become, so its argument has to be a kind.
        if block.kind:
            assert block.kind in STACKS, block.kind
            assert block.argument == block.kind
        else:
            assert block.label, block.command
        # `requires` names a kind that must exist first. A typo here disables a block forever.
        assert block.requires == "" or block.requires in STACKS, block.command
        assert block.takes in ("", "stack", "name"), block.command
        assert (block.choices != ()) == (block.takes == "stack"), block.command


def test_a_block_press_parses_as_the_command_the_block_named() -> None:
    """The palette builds `/<command> <argument> <name>`; this is that string, read back.

    Written against `blocks()` rather than against a list of strings, so a block added later
    is covered the day it is added rather than the day somebody remembers this test.
    """
    for block in blocks():
        parts = [f"/{block.command}"]
        if block.argument:
            parts.append(block.argument)
        if block.takes == "name":
            parts.append("something")
        if block.takes == "stack":
            parts.append(f"--stack {block.choices[0]}")

        typed = TYPED.match(" ".join(parts))
        assert typed is not None, block.command
        assert typed.group(1) == block.command, block.command
        if block.kind:
            assert _kind_in(" ".join(parts)) == block.kind
