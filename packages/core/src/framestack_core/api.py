"""The API the shell and the UI are handed.

Versioned from the first day it exists. The UI is delivered separately and on its own
schedule, so the two sides will be out of step at some point; a payload that announces its
version can be handled, one that changes shape silently cannot.

Everything here is assembly: it puts another module's result in one envelope and adds
nothing of its own. A decision made here would be a decision made twice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from framestack_core.chat import COMMANDS as CHAT_COMMANDS
from framestack_core.chat import STACKS, blocks, changes, send
from framestack_core.compose import EDITABLE, read_compose, write_compose
from framestack_core.database import read_database
from framestack_core.deploy import deploy_status as read_deploy_status
from framestack_core.deploy import (
    read_deploy,
    start_deploy,
    stop_deploy,
)
from framestack_core.editor import open_in_editor, open_url
from framestack_core.layout import create_project, read_layout, write_layout
from framestack_core.mcp import (
    authorisation,
    connect_server,
    give_up,
    probe_server,
    read_server,
    write_secret,
)
from framestack_core.observe import last_observation, read_observation, start_observation
from framestack_core.ollama import pull_model, read_models, read_pull, stop_pull
from framestack_core.parser import read_graph
from framestack_core.routes import read_routes
from framestack_core.run import last_run, read_run, start_run, stop_run
from framestack_core.session import (
    COMMANDS,
    EFFORTS,
    MODELS,
    MODES,
    account,
    answer_permission,
    configure_session,
    forget_session,
    interrupt,
    poll_session,
    rename_session,
    session_status,
    sign_in,
    sign_out,
    start_session,
    stop_session,
)
from framestack_core.settings import read_settings, write_setting
from framestack_core.shell import (
    close_shell,
    list_shells,
    open_shell,
    read_shell,
    resize_shell,
    write_shell,
)
from framestack_core.status import read_status
from framestack_core.usage import read_usage
from framestack_core.watch import forget_watch, read_watch

#: Bumped when the payload's shape changes in a way a client would notice. Additive fields
#: do not bump it; removing or retyping one does.
#:
#: 3: the rebuild. The annotation layer and the kind registry are gone, and with them every
#: payload that described a node, a knob, a diagnostic or a verdict. What is left is the
#: chat session, the terminal, the layout and the project directory.
#:
#: Phase 1 adds `graph.read` and does **not** move this. A new method is additive -- a
#: client that has never heard of it is unaffected -- and the version is a promise about the
#: shape of what an existing caller already receives. Spending a bump on an addition would
#: teach the far side to expect one for everything, and then the number says nothing.
GRAPH_API_VERSION = 3


# -- the contract ---------------------------------------------------------------
#
# Written out rather than derived from what the code happens to emit: a contract is a
# decision, and a schema inferred from current behaviour would ratify a mistake as readily
# as a design. The test validates real payloads against this, strictly -- an undeclared
# field fails just as loudly as a missing one.
#
# Notation: "str"/"int"/"bool" are scalars, a trailing "?" allows null, [x] is a list of
# x, {...} is an object with exactly these keys, {"<key>": x} is a map with arbitrary keys
# and values shaped like x, and {"<nullable>": x} allows a structure to be absent.


#: The `shell.*` payload: one terminal the person types into.
#:
#: The sixth instance of the P13 shape, and the only one that is **not a claim about the
#: graph**: a shell colours no node and proves no check, which is exactly why it may run what
#: `command.start` refuses (see `shell.py`). Output is polled with an offset the caller keeps.
SHELL_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "shell": "str",
    "running": "bool",
    "output": "str",
    "offset": "int",
    # Every terminal open for this project, so a panel draws its tabs from one answer.
    "shells": [{"id": "str", "name": "str", "running": "bool", "pid": "int"}],
}


#: The `graph.read` payload: what the project is, read from its own directories.
#:
#: **There is no colour in here, and its absence is the contract.** A verdict is earned by a
#: run (I-3) and nothing here runs anything, so a node says what it *is* and what it depends
#: on; whether any of it works is Observe's answer, and it arrives in Phase 2 as a field of
#: its own rather than as a default somebody has to remember to disbelieve.
#:
#: `missing` and `reason` are the incomplete case, sent rather than hidden: a directory that
#: looks like a system and is not one is the state a half-written package is in, and naming
#: the export it lacks is the difference between a graph that explains itself and one that
#: quietly disagrees with the file tree.
GRAPH_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    # Absolute, so a client holding several projects can tell them apart. Every path inside
    # a node is relative to it.
    "root": "str",
    "nodes": [
        {
            "id": "str",
            "name": "str",
            # One of the four kinds, `"file"`, or `"mcp"`. Never a framework: the stack is
            # not part of the contract, and a payload that named one would put it back in.
            #
            # `file` and `mcp` are **not kinds** — they have no required export and nothing
            # that could ever prove them. A caller deciding whether a node is a package must
            # ask whether its kind is one of the four, never whether it is "not a file": that
            # test meant the right thing only while `file` was the sole exception to it.
            "kind": "str",
            "path": "str",
            "complete": "bool",
            "exports": ["str"],
            "missing": ["str"],
            "reason": "str",
            "parent": "str",
            "children": ["str"],
            "files": ["str"],
            # The entry points an edge may land on: `index` and `search` for a rag, one per
            # `HANDLERS` key for a worker, `run` for an agent, none for an api. What the
            # package **binds**, never what its kind requires -- a missing export is said in
            # `missing`, and a port for a name nothing binds would be an attachment point
            # for an import that cannot be written.
            "ports": ["str"],
            # Where one of this node's own files stops parsing, or `""`. A broken file
            # **marks** a node and never blanks one: a file mid-write is ordinary in a graph
            # that re-reads itself on save, and nothing else about the node moves for it.
            "broken": "str",
        }
    ],
    # Read from imports and from `mcp.json`, never declared. Nothing in the UI creates one.
    # An `mcp` edge lands on the **server**, not on the file that configures it: the agent
    # reaches that server, and the file is where the fact is written down.
    #
    # `port` is which of the target's ports the edge lands on, `""` for the package itself.
    # `api -> rag` says nothing; `worker -> rag.index` and `agent -> rag.search` say that
    # uploads index and questions retrieve.
    "edges": [
        {
            "id": "str",
            "source": "str",
            "target": "str",
            "kind": "str",
            "label": "str",
            "port": "str",
        }
    ],
}


#: The `observe.*` payload: what a run proved, and what it printed while it proved it.
#:
#: One schema for all three verbs because they are one shape, as `shell.*` is: a run was
#: started, a run was polled, or the last verdict set was asked for. Output is polled with an
#: offset the caller keeps (P13) — a suite can take minutes, and a verb that answered only at
#: the end would freeze the terminal and the chat behind it.
#:
#: **`skipped` is a verdict here and `green` is never a default.** A check that could not run
#: has proven nothing, and the whole product rests on that being said out loud rather than
#: rendered as an absence somebody has to notice.
OBSERVE_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "running": "bool",
    "output": "str",
    "offset": "int",
    # Null where this project has never been observed — which is not the same as observed and
    # found wanting, and is why it is a nullable structure rather than an empty verdict list.
    "observation": {
        "<nullable>": {
            # Of the observation, in UTC. The commit is what makes the set a claim about a
            # state of the code rather than a floating fact somebody has to date by hand.
            "at": "str",
            "commit": "str",
            "ok": "bool",
            "detail": "str",
            "verdicts": [
                {
                    "node": "str",
                    # green, red, amber, grey or skipped. Amber is a distinct state and not a
                    # shade of green: "nothing I could check failed and something was never
                    # checked" is a different claim from "everything passed".
                    "verdict": "str",
                    "reason": "str",
                    # The evidence itself, as pytest names it, rather than a count of it. A
                    # person can paste one of these into a terminal and see what we saw.
                    "tests": ["str"],
                }
            ],
        }
    },
}


#: The `settings.*` payload: the knobs of one system, as its own class declares them.
#:
#: One schema for the read and the write because they answer the same question -- what does
#: this class say now -- and the write answers it by **re-reading the file** rather than by
#: describing what it believes it did.
#:
#: `path` is `""` where the system has no `settings.py`, and that is `ok: true`: a system with
#: no knobs is the ordinary case, and a refusal in front of it would make the commonest state
#: look like a fault.
SETTINGS_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    "path": "str",
    "class_name": "str",
    "fields": [
        {
            "name": "str",
            # The annotation exactly as the author wrote it, not our reading of it.
            "annotation": "str",
            # integer, number, toggle, text, select, or none. What a caller branches on.
            "control": "str",
            # The default, **as the field's own type** -- an int, a float, a bool or a string.
            # Opaque here because the type is genuinely the user's rather than ours, and a
            # contract that flattened it to text would make the panel guess it back.
            "value": "<opaque>",
            "choices": ["str"],
            # Where it is written. What "open in editor" points at, so a person can always
            # leave the panel and look at the code it is talking about.
            "line": "int",
            # Why there is no control, when there is none. Never a repair, never a guess.
            "reason": "str",
        }
    ],
}


#: The `mcp.*` payload: what `mcp.json` declares about one server, and what `Connect` did.
#:
#: **`env` is names and never values**, and that is the contract rather than an oversight. An
#: entry may legitimately hold a secret inline, and this payload crosses into a webview — one
#: console log away from somewhere permanent. The names are what a person needs to see; the
#: values stay in the file they are already in.
#:
#: There is **no `connected` field here, and its absence is still deliberate**: this payload
#: says what the file declares and what `Connect` did, and whether a server answers is a
#: different question with a different mechanism. That question is `mcp.probe`, which speaks
#: the protocol and carries the tool count as its evidence — a tick nobody verified is the
#: same defect as a green node nobody ran a test for.
MCP_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    "name": "str",
    # Exactly as the file gives them. `""` where the entry declares no command, which is an
    # entry somebody has yet to finish rather than a fault.
    "command": "str",
    "args": ["str"],
    "env": ["str"],
    # Which terminal `Connect` started it in, so the caller can show what it is printing.
    "shell": "str",
    # `stdio` for a `command` entry, `http` for a `url` one, `""` for an entry a person has
    # yet to finish. It decides what `Connect` means, so it is stated rather than inferred.
    "transport": "str",
    "url": "str",
    # The three variables this server's authorisation uses, and which of them `.env` sets --
    # **by name, both of them**. That a key is set is worth sending; what it is set to is one
    # console log from being permanent.
    "keys": ["str"],
    "given": ["str"],
}


#: The `mcp.probe` payload: what a server answered when it was asked what it offers.
#:
#: **`connected` is earned and nothing else produces it.** It means this server answered
#: `tools/list` at `at` — not that an entry exists, not that a command is on `PATH`, not that
#: a token is in `.env`. A server nobody has asked has no probe at all, and the absence is
#: drawn as absence rather than as a hopeful default.
#:
#: `ok` and `connected` are different claims. `ok` is "the question was asked"; `connected`
#: is "it was answered". A probe that reached a server which refused is a successful probe
#: with a negative answer, and merging the two would throw away the sentence saying why.
#:
#: Nothing here is stored. An answer about a live process goes stale the moment the process
#: does, and a remembered one would be a claim outliving the thing it was about.
MCP_PROBE_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    "name": "str",
    "connected": "bool",
    # In the server's own order. The count is the proof; the names are what a person
    # recognises it by. **Nothing in this codebase can call one of them.**
    "tools": ["str"],
    "server": "str",
    "transport": "str",
    "at": "str",
}


#: The `mcp.authorize` / `mcp.authorized` / `mcp.cancel` payload: how one browser exchange went.
#:
#: **No token is in it, and there is no field one could be put in.** The flow writes the token
#: to `.env` and reports the variable's *name*; a payload carrying the value would be a secret
#: crossing into a webview, which is the one thing this whole area is arranged to prevent.
#:
#: `url` is the consent screen the browser was sent to — it carries a client id and a PKCE
#: challenge, both public — and `redirect` is the loopback address the person has to register
#: in the provider's console, which is why it is shown before anything can work.
MCP_AUTH_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    "running": "bool",
    "url": "str",
    "redirect": "str",
    # The **name** of the variable the token was written to. Never the value.
    "stored": "str",
    "at": "str",
}


#: The `routes.read` payload: what one service serves, and where each request goes next.
#:
#: **Beside the graph, never in it.** A route is contents of the api node -- forty routes must
#: not become forty nodes -- and a route list goes stale at a different moment than the graph
#: does, exactly as a verdict set does. A caller that never opens the panel never pays for it.
#:
#: `targets` is where the request goes: node ids, or `postgres` for a handler whose calls go
#: through `repositories/`. Empty with `unsure` false means the handler calls nothing at all;
#: empty with `unsure` true means it called something that resolved to nothing, which the
#: panel draws as `?`. **The two are different claims and are never merged** -- doubt
#: manufactured about a function that plainly has no downstream is the same defect as a green
#: node nobody ran a test for, pointed the other way.
ROUTES_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    "routes": [
        {
            "method": "str",
            "path": "str",
            "handler": "str",
            "file": "str",
            "targets": ["str"],
            "unsure": "bool",
        }
    ],
}


#: The `database.read` payload: what the project's storage is, never whether it is running.
#:
#: **Beside the graph, as the verdict set is.** The graph holds the node -- one per backend,
#: never one per table -- and this holds the reading of it: the connection string the project
#: states and the tables it declares. They go stale at different moments and one of them
#: costs a walk of the project, so a caller that only wants to draw the canvas does not pay
#: for the panel.
#:
#: There is no status field here and its absence is deliberate. A dependency has a status
#: rather than a verdict, and a status comes from a connection check -- which arrives with the
#: thing that can make one. A field reading "unknown" on every read would be a control whose
#: only possible answer is that it has no answer.
DATABASE_SCHEMA = {
    "api_version": "int",
    "present": "bool",
    # A literal out of the project's own settings. Never an environment, never a connection.
    "target": "str",
    "vector": "bool",
    # `postgres`, or `postgres + pgvector` where a model declares a vector column.
    "label": "str",
    "tables": [{"name": "str", "file": "str", "vector": "bool"}],
}


#: The `status.read` payload: whether one dependency can be reached, and when it was asked.
#:
#: **A status is not a verdict**, and they never share a colour scale. A verdict comes from a
#: test and belongs to code you own; this comes from a connection and belongs to something
#: outside the project. `reachable` is not `green`: reached is not proven.
#:
#: Five states, and each is a different claim. `unknown` is not `unreachable` -- "never
#: checked, or not checkable from here" is a different sentence from "it refused" -- and
#: `configured` / `unconfigured` belong to the nodes where a check would cost money. **No
#: check here is ever billable**: a status that costs money is one nobody can afford to poll.
STATUS_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "node": "str",
    "status": "str",
    # Why. A colour nobody can act on is decoration, so a refusal carries its reason.
    "detail": "str",
    # When it was asked, so a caller can tell a fresh answer from one it still holds.
    "at": "str",
}


#: The `ollama.*` payload: what is on this machine, and how a pull is going.
#:
#: One schema for all four verbs, as `shell.*` and `observe.*` have: the list was read, a pull
#: was started, polled or asked to stop. Output is polled with an offset the caller keeps,
#: because a pull takes minutes and a verb that answered only at the end would freeze the panel.
#:
#: **The list is not a catalogue.** It is whatever this machine has pulled, asked at the moment
#: somebody looks. A registry of model names shipped with the toolchain would be stale the week
#: after it shipped, and it is the "catalogue" the plan puts out of scope.
OLLAMA_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    # Bytes, as the daemon reports them. Formatting is the interface's business.
    "models": [{"name": "str", "size": "int"}],
    "pulling": "str",
    "running": "bool",
    "output": "str",
    "offset": "int",
}


#: The `editor.open` payload. Which program was started, so the answer says what happened.
EDITOR_SCHEMA = {"api_version": "int", "ok": "bool", "detail": "str", "editor": "str"}


#: The `chat.send` payload: what a message was dispatched as, or what has to be answered first.
#:
#: **`asking` is the field that matters.** A dispatcher that always dispatched would be one
#: that guessed, and a wrong command writes the wrong files into somebody's project. The two
#: things it can be unsure about — which command, and which stack — are both questions with a
#: short list of answers and a person sitting in front of them, so it asks.
#:
#: There is no field here for "sent without a command", and its absence is the contract: every
#: turn carries exactly one command's prompt, and the free-form write path does not exist.
CHAT_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    # One of `chat.choices`' commands. `""` when it asked instead of dispatching.
    "command": "str",
    # "command", "stack", or "" when nothing needs answering. The caller sends the answer back
    # as the `command` or `stack` parameter of the next `chat.send`.
    "asking": "str",
    "question": "str",
    "choices": ["str"],
    "sent": "bool",
}


#: The `chat.changes` payload: what the working tree looks like after a turn that wrote.
#:
#: Asked of `git` and never computed here. Observe is **offered** on the back of this and
#: never run (P11): a verdict is earned by a run somebody asked for, and a graph that re-ran
#: its own tests after every edit would be one whose colours nobody could tie to a commit.
CHANGES_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "diff": "str",
    "files": ["str"],
}


#: The `chat.choices` payload: the commands, and the stacks each kind may be written on.
#:
#: The stacks are a **generation preference and not a node type** — they decide what goes
#: inside a package and nothing else, which is why a LangGraph agent rewritten onto Pydantic
#: AI is still the same node. Sent here rather than hard-coded in the interface so there is
#: one list of them.
CHAT_CHOICES_SCHEMA = {
    "api_version": "int",
    "commands": ["str"],
    "stacks": {"<key>": ["str"]},
    # What a palette may offer, declared here rather than in the interface. A palette with
    # its own list could offer a command the prompts have never heard of, and the first
    # symptom would be a button that starts a turn the agent does not understand.
    #
    # **There is no code in here.** A block carries a command and what a person supplies
    # before pressing it; what gets written is whatever the agent writes from that command's
    # prompt. A field holding a scaffold would make this a template gallery, which is the one
    # thing the palette must never become.
    "blocks": [
        {
            "command": "str",
            "argument": "str",
            # The kind whose colour and glyph draws it, so a block looks like the node it
            # will become. `""` where it becomes no node at all.
            "kind": "str",
            "label": "str",
            "hint": "str",
            # "", "stack" (one of `choices`), or "name" (free text — the alternative is a
            # catalogue of databases and servers, and a catalogue is a gallery).
            "takes": "str",
            "choices": ["str"],
            # Whether the convention allows only one at the root, and what must exist first.
            "once": "bool",
            "requires": "str",
        }
    ],
}


#: The `layout.read` payload: where the person put things (Q13).
#:
#: `"<opaque>"` is not a shrug — it is the contract. The core stores this and refuses to
#: look inside, because a core that understood a coordinate would sooner or later be asked
#: to produce one, and a graph the toolchain laid out is a graph it has an opinion about.
LAYOUT_READ_SCHEMA = {"api_version": "int", "layout": {"<key>": "<opaque>"}}

#: The `layout.write` payload. A refusal is a result, as everywhere else.
LAYOUT_WRITE_SCHEMA = {"api_version": "int", "ok": "bool", "detail": "str"}


#: The payload of every `agent.*` session verb. One schema because they are one shape: an
#: agent was found, a session was opened, something was said, or events came back. `events`
#: is what an interface can act on -- what is happening, which file, what was refused -- and
#: the raw stream stays in the log where it can be read whole.
AGENT_SESSION_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "session": "str?",
    "running": "bool",
    "available": "bool",
    "version": "str",
    # One step of a turn. `detail` is what a tool was called with, or what it answered;
    # `id` is the agent's own `tool_use_id`, which is what lets a result be shown against the
    # call it answers rather than merely after it. Both are "" where they do not apply.
    # One step of a turn. `detail` is what a tool was called with or what it answered; `id`
    # is the agent's own `tool_use_id`, which is what pairs a result with the call it answers
    # rather than merely following it; `tool` is the agent's name for what it called.
    "events": [
        {
            "kind": "str",
            "text": "str",
            "file": "str",
            "detail": "str",
            "id": "str",
            "tool": "str",
            # Only an `asking` carries this, and only once somebody has pressed something:
            # `""` is a request still waiting, and it is a different state from "denied"
            # (Q21). `id` on an `asking` is the agent's `request_id` -- what an answer is
            # addressed by -- rather than a `tool_use_id`.
            "answer": "str",
            # Only an `AskUserQuestion` carries these (Q37), and it carries them as the
            # agent wrote them. `<opaque>` because the fields are that tool's, not ours: a
            # contract here would go stale the first time the tool gained one.
            "questions": ["<opaque>"],
        }
    ],
    # Where the reader got to. Events are polled, never pushed (P13).
    "offset": "int",
    # The conversations this project has had -- ids and labels, never a transcript.
    "sessions": [{"id": "str", "label": "str", "at": "str"}],
    # Tokens the last turn carried. A **number, never a percentage**: the window to divide by
    # belongs to the model, which is reported beside it rather than assumed.
    "context": "int",
    # Which model is answering, as the agent named it. Empty until it has said.
    "model": "str",
    # The agent's own running estimate of what the turn has cost so far. Usage proper is
    # reported exactly twice in a turn -- at the start of a message and at its end -- so a
    # number that *moves* while it works is the agent's estimate or it is nobody's.
    "spending": "int",
    # What the agent says it can be asked to do -- **names only**, because names only is what
    # it sends. Empty from a poll that carried no `init`; the caller keeps the last list.
    "commands": ["str"],
    # How this project's sessions are started. All three are **flags at spawn** -- there is no
    # way to change one in a running conversation -- so setting one restarts the process under
    # `--resume`, which keeps the conversation and not the process it was being had in.
    # Null where the verb was not asked -- absent is not the same as "no model, no effort".
    "settings": {
        "<nullable>": {
            "model": "str",
            "effort": "str",
            "mode": "str",
            # Whether the agent may run commands. Not the mode: no permission mode grants
            # Bash, and a person saying "yes" once is what makes the project's tests runnable.
            "commands": "str",
        }
    },
}

#: The `agent.account` payload: who the agent is signed in as.
#:
#: Read from the CLI, never held here. The credential belongs to the agent, which put it on
#: this machine through its own browser flow -- the core has no HTTP client to a model and no
#: SDK (Q16), so there is nothing to store. What this answers is the question the application
#: could not answer before: whose account is a turn about to spend?
AGENT_ACCOUNT_SCHEMA = {
    "api_version": "int",
    "signed_in": "bool",
    "method": "str",
    "email": "str",
    "plan": "str",
    "organisation": "str",
    # Why not, when the answer is no. Never a guess about what went wrong.
    "detail": "str",
}


#: The `agent.choices` payload: what a session may be set to.
#:
#: Asked rather than hard-coded on the far side: the offered set is a fact about which flags
#: this agent honours, and one of them (`manual`) is accepted and ignored, which is exactly
#: the kind of thing a menu written from documentation gets wrong.
AGENT_CHOICES_SCHEMA = {
    "api_version": "int",
    "models": ["str"],
    "efforts": ["str"],
    "modes": ["str"],
    "commands": ["str"],
}


#: The `run.*` payload: one export, called once, and what it gave back.
#:
#: **There is no verdict in here and there will not be one.** Green is earned by a passing
#: test that executed the code (I-3); this is a person typing a query and pressing a button,
#: which proves the call returned and nothing more. A payload that carried a colour would let
#: a node go green because somebody used it, which is the flow-document defect wearing a
#: different hat.
#:
#: One schema for all four verbs, as `observe.*` and `shell.*` are: a call was started,
#: polled, stopped, or the last one was asked for.
RUN_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    # Which export was called, named by the action: `search`, `index`, `run`, `request`,
    # `handle`, `handlers`. Never a method of an implementation -- every one of these is an
    # export the convention already requires.
    "action": "str",
    "running": "bool",
    # What the project's own code printed. Polled with an offset the caller keeps (P13).
    "output": "str",
    "offset": "int",
    # Null where this node has never been run -- not the same as run and found wanting.
    "outcome": {
        "<nullable>": {
            "node": "str",
            "action": "str",
            "at": "str",
            "ok": "bool",
            # The export's own return value. `<opaque>` because the shape is genuinely the
            # user's: a contract for what somebody's `search` returns would be this toolchain
            # having an opinion about their code.
            "value": "<opaque>",
            # The child's traceback, verbatim. `""` when it returned.
            "error": "str",
        }
    },
    # What was handed to `index` from this window. A memory of uploads, never a claim about
    # what the index holds -- the convention gives RAG two exports and neither lists anything.
    "documents": ["str"],
}


#: The `deploy.*` payload: the compose stack, up or down.
#:
#: `services` is **asked of `docker compose config`** and never read out of the file. A YAML
#: reader here would be a second opinion about a format that already has a first one. It is
#: empty from a poll, which does not ask -- the answer costs a process and does not change
#: while the stack runs.
DEPLOY_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "running": "bool",
    "output": "str",
    "offset": "int",
    # Whether there is a docker to use, and what it says it is. Sent so the panel can explain
    # a button that will not work before somebody presses it.
    "available": "bool",
    "version": "str",
    "services": ["str"],
}


#: The `compose.*` payload: what the stack is made of, and what of it is up.
#:
#: **Two mechanisms, kept apart in the fields themselves.** `state` and `published` come from
#: `docker compose ps` -- what the daemon is actually doing -- and everything beside them is
#: what the file declares. A `ports:` line is what somebody asked for; a published port is what
#: happened, and merging the two would let a stopped stack look like a running one.
#:
#: `state` is `""` where the daemon holds no container for the service, which is a different
#: claim from `exited` and is never merged with one. `image` is `""` for a service that builds
#: its own, which is ordinary rather than a failure.
#:
#: **A status is not here.** A container's state is what the daemon reports; whether the thing
#: inside it answers is the dependency's question, asked by `status.read` with a connection.
COMPOSE_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "present": "bool",
    "available": "bool",
    "path": "str",
    # The five fields a panel may change. Declared in the payload so a client draws exactly
    # those controls and never a sixth it invented -- the limit is a decision of this build's,
    # and a control the core cannot answer for is a button whose only outcome is an error.
    "fields": ["str"],
    "services": [
        {
            "name": "str",
            "image": "str",
            "ports": ["str"],
            "environment": ["str"],
            "volumes": ["str"],
            "depends_on": ["str"],
            "state": "str",
            "published": ["str"],
        }
    ],
}


#: The `usage.read` payload: what one node's last run cost.
#:
#: **Tokens are measured and dollars are arithmetic**, which is why `cost` is nullable in two
#: places rather than defaulted to zero. A step whose model this build has no price for shows
#: its tokens and `null`; a run where none of the steps could be priced has a `null` total.
#: `$0.00` would be a false statement where "we do not know" is the true one, and the
#: `unpriced` names say which models are the reason.
#:
#: Nothing here is instrumentation in somebody's project: the measurement is a wrapper in the
#: child process `Run` already spawns, written into `.framestack/` and deleted with it (I-6).
USAGE_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "node": "str",
    "calls": [
        {
            "at": "str",
            "model": "str",
            "input": "int",
            "output": "int",
            # Null where the model is not in the price table. Never a guess.
            "cost": "number?",
        }
    ],
    "tokens": "int",
    "cost": "number?",
    "unpriced": ["str"],
    # Where this project's traces go, if its `.env` says it sends any. A link and never a
    # fetch: Langfuse is linked out to, never read from and never fallen back to.
    "langfuse": "str",
}


#: The `watch.*` payload: whether anything the parser reads has changed.
#:
#: **A question, never a push.** The caller holds `revision` and sends it back; a graph it
#: has just read is not stale, so the first ask answers `changed: false`. That is the same
#: shape every log offset in this codebase has, and it is why live re-parse needs no second
#: message type on the wire.
#:
#: `files` is a hint for a person and is capped. Whatever it says, the answer is the same:
#: read the graph again. A change *set* would be a second description of the project, which
#: is the thing this whole application refuses to keep.
WATCH_SCHEMA = {
    "api_version": "int",
    "ok": "bool",
    "detail": "str",
    "revision": "int",
    "changed": "bool",
    "files": ["str"],
}


def create_new_project(parent: Path | str, name: str) -> dict[str, Any]:
    """Make an empty directory for a project. `detail` is the path when it worked."""
    return {"api_version": GRAPH_API_VERSION, **create_project(parent, name).as_dict()}


def graph_get(project: Path | str) -> dict[str, Any]:
    """The project as a graph. A read: it imports nothing and runs nothing."""
    return {"api_version": GRAPH_API_VERSION, **read_graph(project).as_dict()}


def observe_start(project: Path | str) -> dict[str, Any]:
    """Run the project's tests and colour the graph from what happened. Never implicit."""
    return {"api_version": GRAPH_API_VERSION, **start_observation(project).as_dict()}


def observe_read(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What the run has printed since `offset`, and the verdicts once there are any."""
    return {"api_version": GRAPH_API_VERSION, **read_observation(project, offset).as_dict()}


def observe_last(project: Path | str) -> dict[str, Any]:
    """The stored verdict set. A read: it starts nothing and proves nothing new."""
    return {"api_version": GRAPH_API_VERSION, **last_observation(project).as_dict()}


def run_start(
    project: Path | str, node: str, action: str, given: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call one export. Never implicit (P11), and it colours nothing."""
    return {"api_version": GRAPH_API_VERSION, **start_run(project, node, action, given).as_dict()}


def run_read(project: Path | str, node: str, offset: int = 0) -> dict[str, Any]:
    """Poll the call. The caller keeps the offset it was last given (P13)."""
    return {"api_version": GRAPH_API_VERSION, **read_run(project, node, offset).as_dict()}


def run_last(project: Path | str, node: str) -> dict[str, Any]:
    """What this node last returned, and what was uploaded to it. A read: it starts nothing."""
    return {"api_version": GRAPH_API_VERSION, **last_run(project, node).as_dict()}


def run_stop(project: Path | str, node: str) -> dict[str, Any]:
    """End a call somebody started."""
    return {"api_version": GRAPH_API_VERSION, **stop_run(project, node).as_dict()}


def watch_read(project: Path | str, revision: int = 0) -> dict[str, Any]:
    """Has the project changed since `revision`? A read: it parses nothing and runs nothing."""
    return {"api_version": GRAPH_API_VERSION, **read_watch(project, revision).as_dict()}


def watch_stop(project: Path | str) -> dict[str, Any]:
    """Stop watching one project."""
    return {"api_version": GRAPH_API_VERSION, **forget_watch(project).as_dict()}


def usage_read(project: Path | str, node: str) -> dict[str, Any]:
    """What this node's last run cost. A read: it starts nothing and calls no provider."""
    return {"api_version": GRAPH_API_VERSION, **read_usage(project, node).as_dict()}


def deploy_status(project: Path | str) -> dict[str, Any]:
    """Whether this project can be deployed, and whether it already is."""
    return {"api_version": GRAPH_API_VERSION, **read_deploy_status(project).as_dict()}


def deploy_up(project: Path | str) -> dict[str, Any]:
    """Bring the compose stack up. Never implicit (P11)."""
    return {"api_version": GRAPH_API_VERSION, **start_deploy(project).as_dict()}


def deploy_poll(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What compose has printed since `offset` (P13)."""
    return {"api_version": GRAPH_API_VERSION, **read_deploy(project, offset).as_dict()}


def deploy_down(project: Path | str) -> dict[str, Any]:
    """Take the stack down -- the client and the containers both."""
    return {"api_version": GRAPH_API_VERSION, **stop_deploy(project).as_dict()}


def compose_read(project: Path | str) -> dict[str, Any]:
    """What the stack declares and what of it is up. A read: it brings nothing up."""
    return {
        "api_version": GRAPH_API_VERSION,
        "fields": list(EDITABLE),
        **read_compose(project).as_dict(),
    }


def compose_write(project: Path | str, service: str, field: str, value: Any) -> dict[str, Any]:
    """Change one of the five fields, through a round-trip that keeps the rest byte-identical."""
    return {
        "api_version": GRAPH_API_VERSION,
        "fields": list(EDITABLE),
        **write_compose(project, service, field, value).as_dict(),
    }


def chat_send(
    project: Path | str,
    text: str,
    command: str = "",
    stack: str = "",
    images: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    """Send one message, as exactly one command. **The only way into the agent.**

    `agent.say` used to be the other way, and it is gone rather than discouraged: a verb that
    sent whatever it was handed is a free-form write path, and this phase's whole claim is
    that there is not one. A message reaches the agent with a command's prompt in front of it
    or it does not reach the agent.
    """
    return {
        "api_version": GRAPH_API_VERSION,
        **send(project, text, command, stack, images).as_dict(),
    }


def chat_changes(project: Path | str) -> dict[str, Any]:
    """What has changed in the working tree, asked of `git`. Runs no tests."""
    return {"api_version": GRAPH_API_VERSION, **changes(project).as_dict()}


def chat_choices() -> dict[str, Any]:
    """The commands, and the stacks each kind may be generated on."""
    return {
        "api_version": GRAPH_API_VERSION,
        "commands": list(CHAT_COMMANDS),
        "stacks": {kind: list(names) for kind, names in STACKS.items()},
        "blocks": [block.as_dict() for block in blocks()],
    }


def settings_get(project: Path | str, node: str) -> dict[str, Any]:
    """One system's knobs. Reads the file; never imports it and never creates it."""
    return {"api_version": GRAPH_API_VERSION, **read_settings(project, node).as_dict()}


def settings_put(project: Path | str, node: str, field: str, value: Any) -> dict[str, Any]:
    """Set one field's default, through libcst. Everything else stays byte-identical."""
    return {
        "api_version": GRAPH_API_VERSION,
        **write_setting(project, node, field, value).as_dict(),
    }


def mcp_read(project: Path | str, node: str) -> dict[str, Any]:
    """What `mcp.json` declares about one server. A read: it starts nothing and asks nobody."""
    return {"api_version": GRAPH_API_VERSION, **read_server(project, node).as_dict()}


def mcp_probe(project: Path | str, node: str) -> dict[str, Any]:
    """Ask one server what it offers. Never implicit -- it starts a process or a request."""
    return {"api_version": GRAPH_API_VERSION, **probe_server(project, node).as_dict()}


def mcp_secret(project: Path | str, node: str, field: str, value: str) -> dict[str, Any]:
    """Put a client id or secret in `.env`. The answer is the entry re-read, values absent."""
    return {"api_version": GRAPH_API_VERSION, **write_secret(project, node, field, value).as_dict()}


def mcp_authorized(project: Path | str, node: str) -> dict[str, Any]:
    """How a browser exchange is going. A read: it opens nothing and asks no provider."""
    return {"api_version": GRAPH_API_VERSION, **authorisation(project, node).as_dict()}


def mcp_cancel(project: Path | str, node: str) -> dict[str, Any]:
    """Stop waiting for a browser. The listener goes; nothing was written."""
    return {"api_version": GRAPH_API_VERSION, **give_up(project, node).as_dict()}


def mcp_connect(project: Path | str, node: str) -> dict[str, Any]:
    """Run the server's own command in a terminal, so it can authorise itself. Never
    implicit (P11), and it stores no credential -- there is nowhere here that one would go."""
    return {"api_version": GRAPH_API_VERSION, **connect_server(project, node).as_dict()}


def ollama_models(project: Path | str) -> dict[str, Any]:
    """What this machine has pulled. A read: it fetches nothing and starts nothing."""
    return {"api_version": GRAPH_API_VERSION, **read_models(project).as_dict()}


def ollama_pull(project: Path | str, model: str) -> dict[str, Any]:
    """Start pulling one model. Never implicit -- only a press gets here."""
    return {"api_version": GRAPH_API_VERSION, **pull_model(project, model).as_dict()}


def ollama_read(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What the pull has printed since `offset`, and whether it is still going."""
    return {"api_version": GRAPH_API_VERSION, **read_pull(project, offset).as_dict()}


def ollama_stop(project: Path | str) -> dict[str, Any]:
    """Stop watching a pull. The daemon keeps whatever it already wrote."""
    return {"api_version": GRAPH_API_VERSION, **stop_pull(project).as_dict()}


def status_read(project: Path | str, node: str) -> dict[str, Any]:
    """Whether one dependency can be reached. Connects; starts nothing; costs nothing."""
    return {"api_version": GRAPH_API_VERSION, **read_status(project, node).as_dict()}


def database_read(project: Path | str) -> dict[str, Any]:
    """The project's storage, as its own Python states it. Connects to nothing."""
    return {"api_version": GRAPH_API_VERSION, **read_database(project).as_dict()}


def routes_read(project: Path | str, node: str) -> dict[str, Any]:
    """What one service serves. A read: nothing is imported, nothing is started."""
    return {"api_version": GRAPH_API_VERSION, **read_routes(project, node).as_dict()}


def editor_open(project: Path | str, path: str, line: int = 0) -> dict[str, Any]:
    """Open one of the project's files in the person's own editor, at the line."""
    return {"api_version": GRAPH_API_VERSION, **open_in_editor(project, path, line).as_dict()}


def editor_browse(url: str) -> dict[str, Any]:
    """Open a page the project serves, in the person's own browser."""
    return {"api_version": GRAPH_API_VERSION, **open_url(url).as_dict()}


def layout_get(project: Path | str) -> dict[str, Any]:
    """Where the person put things. Empty is the ordinary first answer, not a failure."""
    return {"api_version": GRAPH_API_VERSION, "layout": read_layout(project)}


def layout_put(project: Path | str, layout: dict[str, Any]) -> dict[str, Any]:
    """Store the whole layout. The client holds it; the core keeps it and reads nothing."""
    return {"api_version": GRAPH_API_VERSION, **write_layout(project, layout).as_dict()}


def shell_open(project: Path | str, name: str = "") -> dict[str, Any]:
    """Open one terminal in the project's directory. Never implicit (P11)."""
    return {"api_version": GRAPH_API_VERSION, **open_shell(project, name).as_dict()}


def shell_write(project: Path | str, shell: str, text: str) -> dict[str, Any]:
    """Type into it. What is sent is what was typed -- not even a newline is added."""
    return {"api_version": GRAPH_API_VERSION, **write_shell(project, shell, text).as_dict()}


def shell_read(project: Path | str, shell: str, offset: int = 0) -> dict[str, Any]:
    """What it printed since `offset`. The caller keeps the offset it was given (P13)."""
    return {"api_version": GRAPH_API_VERSION, **read_shell(project, shell, offset).as_dict()}


def shell_resize(project: Path | str, shell: str, columns: int, rows: int) -> dict[str, Any]:
    """Tell it how wide its window is -- the one thing wrapping programs read."""
    return {
        "api_version": GRAPH_API_VERSION,
        **resize_shell(project, shell, columns, rows).as_dict(),
    }


def shell_close(project: Path | str, shell: str) -> dict[str, Any]:
    """Close it, and the process group it started with it."""
    return {"api_version": GRAPH_API_VERSION, **close_shell(project, shell).as_dict()}


def shell_list(project: Path | str) -> dict[str, Any]:
    """The terminals open here. A read: it opens nothing."""
    return {"api_version": GRAPH_API_VERSION, **list_shells(project).as_dict()}


def agent_session(project: Path | str) -> dict[str, Any]:
    """Is there an agent on this machine, and is a session open? Starts nothing."""
    return {"api_version": GRAPH_API_VERSION, **session_status(project).as_dict()}


def agent_open(
    project: Path | str, resume: str | None = None, fork: bool = False
) -> dict[str, Any]:
    """Open a session: a new one, one continued by id, or one forked from it (Q16)."""
    return {"api_version": GRAPH_API_VERSION, **start_session(project, resume, fork).as_dict()}


def agent_poll(project: Path | str, offset: int = 0) -> dict[str, Any]:
    """What the agent has said since `offset`. The caller keeps the offset it was given."""
    return {"api_version": GRAPH_API_VERSION, **poll_session(project, offset).as_dict()}


def agent_permission(
    project: Path | str,
    request: str,
    allow: bool,
    always: bool = False,
    answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Answer one standing request for permission. The turn resumes from where it stopped.

    `answers` belongs to `AskUserQuestion` and is refused on anything else (Q37): that tool
    is the agent asking a person to decide rather than to permit, and its own schema names
    the field a decision travels in.
    """
    return {
        "api_version": GRAPH_API_VERSION,
        **answer_permission(project, request, allow, always, answers).as_dict(),
    }


def agent_interrupt(project: Path | str) -> dict[str, Any]:
    """Stop the turn that is running. The conversation and its process both survive."""
    return {"api_version": GRAPH_API_VERSION, **interrupt(project).as_dict()}


def agent_shut(project: Path | str) -> dict[str, Any]:
    """Close the session -- this sidecar's, or one a crashed sidecar left behind."""
    return {"api_version": GRAPH_API_VERSION, **stop_session(project).as_dict()}


def agent_forget(project: Path | str, session: str) -> dict[str, Any]:
    """Drop one conversation from this project's list -- our reference, not the transcript."""
    return {"api_version": GRAPH_API_VERSION, **forget_session(project, session).as_dict()}


def agent_account() -> dict[str, Any]:
    """Who the agent is signed in as. Asks; signs nobody in."""
    return {"api_version": GRAPH_API_VERSION, **account().as_dict()}


def agent_sign_in(console: bool = False) -> dict[str, Any]:
    """Run the agent's own browser sign-in and report what it left behind."""
    return {"api_version": GRAPH_API_VERSION, **sign_in(console).as_dict()}


def agent_sign_out() -> dict[str, Any]:
    """Sign the agent out. Ours to ask for, the CLI's to carry out."""
    return {"api_version": GRAPH_API_VERSION, **sign_out().as_dict()}


def agent_rename(project: Path | str, session: str, label: str) -> dict[str, Any]:
    """Name one conversation. The label is the person's; everything else about it is not."""
    return {"api_version": GRAPH_API_VERSION, **rename_session(project, session, label).as_dict()}


def agent_choices() -> dict[str, Any]:
    """What a session may be set to. A statement about the agent, not about the project."""
    return {
        "api_version": GRAPH_API_VERSION,
        "models": list(MODELS),
        "efforts": list(EFFORTS),
        "modes": list(MODES),
        # Whether the agent may run commands. A separate choice from the mode because it is
        # a separate mechanism: no permission mode grants Bash, and this is what does.
        "commands": list(COMMANDS),
    }


def agent_configure(
    project: Path | str,
    model: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    commands: str | None = None,
) -> dict[str, Any]:
    """Set what sessions here are started with, restarting the open one onto it."""
    return {
        "api_version": GRAPH_API_VERSION,
        **configure_session(
            project, model=model, effort=effort, mode=mode, commands=commands
        ).as_dict(),
    }
