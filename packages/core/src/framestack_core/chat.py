"""The chat, as four narrow commands and no free-form write path.

One surface, one agent, and a contract that fits in a paragraph: ordinary Python following
the convention. What makes that contract keepable is the shape of this module rather than the
wording of any prompt.

## There is no way to send a bare message

`send` is the only way into the agent, and it always dispatches to exactly one command. A
message that is not obviously one of them is **classified**, and a classification that is not
confident **asks** rather than guessing — a wrong command writes the wrong files into
somebody's project, and the person is right there.

That is the structural claim, and it is why the free-form path was removed rather than
discouraged. The old design had one prompt covering everything, and an agent asked to write
working Python, choose a kind from a 27-entry registry, place annotations correctly and
satisfy a per-kind check could not tell which constraint it had broken. Four commands, each
loading one file, is the smallest instruction set that covers what a person actually asks for.

## The prompts are files, and they are loaded at dispatch

`packages/core/prompts/` holds one plain-text file per command plus the shared base, and a
turn carries **the base and one command file, never more**. Not concatenated into a session
system prompt at spawn: an agent holding all four sets of instructions at once is back to
choosing between them, which is the thing the dispatch is for.

They are text files rather than string constants so they can be read, reviewed and changed
without touching Python — they are the agent's entire contract, and a contract buried in a
module is one nobody rereads.

## What the core does not do

**No model client, no SDK.** The classifier is the same agent binary, invoked once with
`--print`, told to answer with one word. The core spawns it, reads a line and compares that
line to a list it holds. It has no opinion about how the answer was reached.

**No model of its own is chosen.** The classifier runs on whatever the project's session is
set to, or on the agent's own default when nothing is set. A cheap model would be the right
thing to want here, and pinning one would be this application making a claim about somebody
else's account -- which the first attempt at it proved, by picking a model this machine has
no credits for.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framestack_core.parser import read_graph
from framestack_core.session import (
    STRICT_MCP,
    agent_binary,
    say,
)
from framestack_core.session import read_settings as session_settings

__all__ = [
    "COMMANDS",
    "ENV_FILE",
    "STACKS",
    "Dispatch",
    "changes",
    "prompt_for",
    "send",
]


def _prompts_dir() -> Path:
    """Where the prompt files are, in a checkout and in the frozen binary alike.

    The frozen sidecar carries them as data (see `core.spec`) and unpacks them beside itself,
    so the answer is different in the two cases and both have to work. A prompt that exists
    only in the repository is a prompt the shipped application does not have -- and it would
    fail as an agent given no instructions rather than as a missing file, which is the worst
    way for this particular thing to break.
    """
    bundled = getattr(sys, "_MEIPASS", "")
    if bundled:
        return Path(bundled) / "prompts"
    return Path(__file__).resolve().parents[2] / "prompts"


#: Plain text, one file per command, beside the package. Read at dispatch, never cached: they
#: are the agent's entire contract, and a contract held in memory is one nobody can correct
#: without restarting the application.
PROMPTS = _prompts_dir()

#: The four commands, and the one label that is not a command.
#:
#: `question` is here because the classifier has to be able to say it: most of what a person
#: types at a chat panel is a question, and a dispatcher whose only outputs wrote files would
#: answer "what does this do?" by editing something.
COMMANDS = (
    "add-system",
    "add-tool",
    "add-service",
    "add-mcp",
    "connect",
    "repair",
    "question",
)

#: What the classifier says when it cannot tell. Not a command, and never dispatched.
UNSURE = "unsure"

#: The stacks each kind is generated on, as the plan lists them.
#:
#: **A generation preference, not a node type.** It decides what gets written inside a
#: package and nothing else: the directory name and the exports are the convention's, so code
#: generated on LangGraph and rewritten by hand onto Pydantic AI stays the same node. That is
#: the whole reason the kind registry could be deleted, and it is why this lives here -- in
#: the thing that writes code -- rather than anywhere near the parser.
STACKS: dict[str, tuple[str, ...]] = {
    "agent": ("langgraph", "pydantic-ai", "plain"),
    "rag": ("pgvector", "qdrant", "chroma"),
    "api": ("fastapi", "litestar"),
    "worker": ("postgres-queue", "arq"),
}

# -- what the palette may offer -------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """One thing a person can press to have written.

    **Declared here rather than in the interface, and that is the point.** A palette with its
    own list of blocks is a palette that can offer something the prompts have never heard of;
    the first symptom is a button that starts a turn the agent does not understand. So the
    blocks are a fact about which commands this build ships, and the interface renders them.

    It is emphatically **not** a template gallery. There is no code here, no scaffold and no
    catalogue of databases or servers: a block carries a command, and what gets written is
    whatever the agent writes from that command's prompt.
    """

    #: Which command a press sends. Always one of `COMMANDS`.
    command: str
    #: What is appended to it, where the command takes a fixed argument. `""` when it does not.
    argument: str
    #: Which kind's colour and glyph to draw it with, so a block looks like the node it will
    #: become. `""` where it becomes no node at all.
    kind: str
    #: What to call it, for a block with no kind to be named by. `""` otherwise.
    label: str
    hint: str
    #: What the person supplies before pressing: `""`, `"stack"` (one of `choices`), or
    #: `"name"` (free text, because the alternative is a catalogue and a catalogue is a
    #: gallery).
    takes: str
    choices: tuple[str, ...]
    #: Whether the convention allows only one of these at the root.
    once: bool
    #: A kind that must already exist for this to be addable. `""` when there is none.
    requires: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "argument": self.argument,
            "kind": self.kind,
            "label": self.label,
            "hint": self.hint,
            "takes": self.takes,
            "choices": list(self.choices),
            "once": self.once,
            "requires": self.requires,
        }


def blocks() -> tuple[Block, ...]:
    """Every block this build can offer, derived from the commands it ships.

    The four systems come from `STACKS`, so a kind cannot appear here without appearing in
    the convention. The rest are the other commands that *add* something -- `connect`,
    `repair` and `question` are not blocks, because none of them brings anything into
    existence.
    """
    made: list[Block] = [
        Block(
            command="add-system",
            argument=kind,
            kind=kind,
            label="",
            hint=f"a {kind}/ package",
            takes="stack",
            choices=stacks,
            # One system of each kind per level. Shown disabled rather than hidden: a rule
            # nobody can see is one they keep running into.
            once=True,
            requires="",
        )
        for kind, stacks in STACKS.items()
    ]

    made.append(
        Block(
            command="add-tool",
            argument="",
            kind="",
            label="Tool",
            hint="a function the agent can call",
            takes="name",
            choices=(),
            once=False,
            # A tool is written into `agent/tools.py`, so there has to be an agent.
            requires="agent",
        )
    )
    made.append(
        Block(
            command="add-service",
            argument="",
            kind="",
            # "Container", not "Service": `api` is already Service on the canvas, and two
            # different things under one word is how a person stops trusting either.
            label="Container",
            hint="a container the project runs beside it",
            takes="name",
            choices=(),
            once=False,
            requires="",
        )
    )
    made.append(
        Block(
            command="add-mcp",
            argument="",
            kind="",
            label="MCP server",
            hint="a server the agent can reach",
            takes="name",
            choices=(),
            once=False,
            requires="",
        )
    )
    return tuple(made)


#: Where a project's stack preference is recorded. A file node, and an ordinary `.env`.
ENV_FILE = ".env"

#: How long the classifier may take before the message is treated as unclassifiable.
#:
#: Short on purpose. This runs before the person sees anything happen, and a dispatcher that
#: thought for a minute would feel like an application that had stopped; falling through to
#: "which did you mean?" costs one click and is never wrong.
CLASSIFY_SECONDS = 45

#: A message that names its own command. `/add-system rag --stack qdrant`.
TYPED = re.compile(r"^/([a-z-]+)\s*(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Dispatch:
    """What was done with a message, or what has to be answered before anything can be.

    `asking` is the important field. A dispatcher that always dispatched would be one that
    guessed, and the two things it can be unsure about -- which command, and which stack --
    are both questions with a short list of answers and a person sitting in front of them.
    """

    ok: bool
    detail: str
    #: The command the message was dispatched as. `""` when it asked instead of dispatching.
    command: str
    #: `"command"`, `"stack"`, or `""` when nothing needs answering.
    asking: str
    #: What to put in front of the person. `""` when nothing is being asked.
    question: str
    #: The answers on offer. The caller sends one back as `command` or `stack`.
    choices: tuple[str, ...]
    #: Whether a turn actually reached the agent.
    sent: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "command": self.command,
            "asking": self.asking,
            "question": self.question,
            "choices": list(self.choices),
            "sent": self.sent,
        }


@dataclass(frozen=True)
class Changes:
    """What the working tree looks like after a turn that wrote files.

    Asked of `git`, never computed here. The tool a person will check this with is the one
    that should answer it, and a diff of our own would be a second opinion about a thing that
    already has a first one.
    """

    ok: bool
    detail: str
    #: The unified diff, exactly as `git` printed it. Empty when nothing changed.
    diff: str
    #: The paths that differ, so a panel can list them without parsing the diff.
    files: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "diff": self.diff,
            "files": list(self.files),
        }


# -- the prompts ------------------------------------------------------------------------------


def prompt_for(command: str) -> str:
    """The base and one command file, in that order. **Never more than two files.**

    An agent holding all four sets of instructions at once is back to choosing between them,
    which is what the dispatch exists to do instead.
    """
    base = _text("base")
    body = _text(command)
    if not base or not body:
        return ""
    return f"{base}\n\n---\n\n{body}"


def _text(name: str) -> str:
    path = PROMPTS / f"{name}.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# -- the stack preference ----------------------------------------------------------------------


def _key_for(kind: str) -> str:
    return f"FRAMESTACK_DEFAULT_STACK_{kind.upper()}"


def stack_of(project: Path, kind: str) -> str:
    """This project's recorded stack for a kind, or `""`.

    Reads **only our own key**, and reads it line by line rather than through a parser for
    `.env`. That file belongs to the person and to whatever loads it at runtime; a reader of
    ours that understood the whole format would be a second opinion about it, and it would be
    wrong in the ways a hand-written file is interesting.
    """
    path = project / ENV_FILE
    if not path.is_file():
        return ""
    key = _key_for(kind)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            value = stripped[len(key) + 1 :].strip().strip("\"'")
            return value if value in STACKS.get(kind, ()) else ""
    return ""


def remember_stack(project: Path, kind: str, stack: str) -> bool:
    """Write the preference down. Replaces our own line; appends when there is none.

    Line-wise for the same reason it is read line-wise: everything the edit is not about
    stays exactly as the person left it, including comments, blank lines and ordering. This
    is the same promise the settings writer makes about a `.py`, kept with the tool a text
    file deserves rather than with a syntax tree it does not have.
    """
    path = project / ENV_FILE
    key = _key_for(kind)
    try:
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        lines = existing.splitlines()
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[index] = f"{key}={stack}"
                break
        else:
            lines.append(f"{key}={stack}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _kind_in(text: str) -> str:
    """Which kind an `/add-system` message is about, if it names one plainly.

    Deliberately literal: the word has to be there. Working out that "retrieval over our docs"
    means `rag` is the classifier's job and the agent's, not a table of synonyms here -- and a
    synonym table is a kind registry with a different name.
    """
    words = re.findall(r"[a-z]+", text.lower())
    for kind in STACKS:
        if kind in words:
            return kind
    return ""


# -- classification ------------------------------------------------------------------------------


def _summary(project: Path) -> str:
    """The current graph, in the few lines a classifier needs.

    "The classifier sees the message and the current graph, nothing more." So this is the
    graph and not the code: what exists, what it exports, and what is missing.
    """
    graph = read_graph(project)
    systems = [node for node in graph.nodes if node.kind != "file"]
    if not systems:
        return "This project has no systems yet."
    lines = [
        f"  {node.id} ({node.kind}){'' if node.complete else ' — incomplete: ' + node.reason}"
        for node in systems
    ]
    return "The project's systems:\n" + "\n".join(lines)


def classify(project: Path, text: str) -> str:
    """One label for one message, from the agent, in one word.

    Spawned rather than streamed into the open session, and that is deliberate twice over: a
    classification must not appear in the person's transcript, and it must not be able to
    write anything -- so it runs with no tools and no MCP servers at all.

    Any failure answers `unsure`. There is no reading of a half-answer here: a dispatcher that
    salvaged a label out of a paragraph would be guessing at exactly the moment it was told
    not to.
    """
    binary = agent_binary()
    if binary is None:
        return UNSURE

    line = [
        binary,
        "--print",
        "--output-format",
        "json",
        # No tools and no servers. It is being asked to read one sentence and answer with one
        # word; anything it could reach would be something it could change.
        "--allowed-tools",
        "",
        *STRICT_MCP,
        "--append-system-prompt",
        _text("classify"),
        f"{_summary(project)}\n\nThe message:\n{text}",
    ]
    settings = session_settings(project)
    if settings.get("model"):
        line += ["--model", settings["model"]]

    try:
        answer = subprocess.run(  # noqa: S603 -- the agent binary, found on this machine
            line,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=CLASSIFY_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return UNSURE
    if answer.returncode != 0:
        return UNSURE

    try:
        loaded = json.loads(answer.stdout)
    except json.JSONDecodeError:
        return UNSURE
    if not isinstance(loaded, dict) or loaded.get("is_error"):
        return UNSURE

    said = str(loaded.get("result", "")).strip().strip(".`'\"").lower()
    return said if said in COMMANDS else UNSURE


# -- dispatch --------------------------------------------------------------------------------------


def send(
    project: Path | str,
    text: str,
    command: str = "",
    stack: str = "",
    images: tuple[dict[str, str], ...] = (),
) -> Dispatch:
    """Send one message, as exactly one command. The only way into the agent.

    `command` and `stack` are **answers to questions this function asked**, not options a
    caller invents: a first call may come back with `asking` set, and the second call carries
    the person's answer. Holding the state here rather than on disk means an unanswered
    question costs nothing and expires by being forgotten.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return Dispatch(False, f"there is no project at {root}", "", "", "", (), False)
    if not text.strip():
        return Dispatch(False, "there is nothing to send", "", "", "", (), False)

    body = text
    chosen = command

    # A message that names its own command is an answer, not a guess. Nothing is classified
    # when the person already said what they meant.
    typed = TYPED.match(text.strip())
    if typed and typed.group(1) in COMMANDS:
        chosen = typed.group(1)
        body = typed.group(2).strip() or text.strip()
        found = re.search(r"--stack\s+([a-z0-9-]+)", body)
        if found and not stack:
            stack = found.group(1)

    if not chosen:
        chosen = classify(root, text)
        if chosen == UNSURE:
            return Dispatch(
                True,
                "not sure which command that is",
                "",
                "command",
                "Which of these is it?",
                COMMANDS,
                False,
            )

    if chosen not in COMMANDS:
        return Dispatch(False, f"{chosen!r} is not a command here", "", "", "", COMMANDS, False)

    # The stack is asked about **once per project per kind**, and then it is written into
    # `.env` where the person can see it, change it and take it with them. A preference kept
    # anywhere else would be one the project could not explain about itself.
    if chosen == "add-system":
        kind = _kind_in(body)
        if kind:
            if stack:
                if stack not in STACKS[kind]:
                    return Dispatch(
                        False,
                        f"{stack!r} is not a stack for {kind}",
                        "",
                        "stack",
                        f"Which stack for {kind}?",
                        STACKS[kind],
                        False,
                    )
                remember_stack(root, kind, stack)
            else:
                stack = stack_of(root, kind)
                if not stack:
                    return Dispatch(
                        True,
                        f"no stack recorded for {kind}",
                        chosen,
                        "stack",
                        f"Which stack should {kind} be written on?",
                        STACKS[kind],
                        False,
                    )
            body = f"{body}\n\nUse the {stack} stack."

    instructions = prompt_for(chosen)
    if not instructions:
        return Dispatch(
            False, f"the {chosen} prompt is missing from this build", chosen, "", "", (), False
        )

    # The prompt goes to the agent; the transcript keeps what the person typed. Sending the
    # whole thing as the message would make every turn in the conversation open with two
    # pages of instructions, which is a transcript nobody can read back.
    answer = say(root, f"{instructions}\n\n---\n\n{body}", images, said=text)
    return Dispatch(answer.ok, answer.detail, chosen, "", "", (), answer.ok)


def changes(project: Path | str) -> Changes:
    """What has changed in the working tree, asked of `git`.

    Shown after a command that wrote, and **Observe is offered rather than run** (P11): a
    verdict is earned by a run somebody asked for, and a graph that re-ran its own tests after
    every edit would be one whose colours nobody could tie to a commit.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        return Changes(False, f"there is no project at {root}", "", ())

    try:
        diff = subprocess.run(  # noqa: S603, S607 -- git, by name, on the person's PATH
            ["git", "diff", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        listed = subprocess.run(  # noqa: S603, S607
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Changes(False, f"git could not be asked: {exc}", "", ())

    if listed.returncode != 0:
        # Not a repository, most likely. A real answer and not a failure: plenty of projects
        # are not under version control, and the chat still works in them.
        return Changes(False, "this project is not a git repository, so there is no diff", "", ())

    files = tuple(sorted(line[3:].strip() for line in listed.stdout.splitlines() if len(line) > 3))
    return Changes(
        True,
        f"{len(files)} file(s) changed" if files else "nothing has changed",
        diff.stdout if diff.returncode == 0 else "",
        files,
    )
