# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A visual builder for Python applications in which **the Python code is the source of truth** and the
node graph is a projection of it. A project stays ordinary Python; the graph is derived from its
directory structure and its imports, and a node is green only when a real test run entered it.
Assembled applications deploy as plain Python projects with no runtime dependency on the builder.

**The repository is mid-rebuild, and the plan is `docs/framestack_rebuild_plan.md`.** Read it before
proposing anything: it is the specification, and *rule zero is that anything not described in it is
deleted*. All twelve phases are done: demolition, the read-only graph, Observe, the settings
panel, the chat, Run and Deploy, then part two — the agent's own chat, the palette, the pending
marker, compose services, MCP nodes, `Connect`, and the two commands the palette needed.

### Why the rebuild exists

The previous contract asked the coding agent to do several things at once: write working Python,
choose a kind from a 27-entry registry, place annotations correctly, satisfy a per-kind observable
check. The agent could not tell which constraint it broke, so it repaired one and broke another. The
result was an app that felt unpredictable and a graph whose colours flickered.

The new contract is one sentence:

> Put a RAG system in `rag/` and export `search`. Put an agent in `agent/` and export `run`.

**Recognition happens by convention, not by annotation.** No decorators, no `Param`, no kind
registry. Parsing is deterministic and the agent's job shrinks to what it already does well in an
ordinary editor.

A node is a package that satisfies the convention. Nesting one level down uses the same rule, so a
sub-agent is a node for the same reason its parent is. **Below that there is one named exception and
no others**: a module in `agent/tools/` is a node, because the directory says so — no decorator, no
registration, nothing to satisfy. It carries no verdict; its lines live inside the agent package and
are already part of what a test of the agent proves, so giving them two owners would let one node be
green and the other grey for the same run.

Everything finer is still absent — no nodes for functions, no verdict on a function, no annotations.
That granularity would need a second mechanism on top of the convention, and building a second
mechanism is what produced the problem this rebuild is fixing. `agent/tools/` is a *place*, which a
person can see in their own file tree; an annotation is a *claim about code*, which is what went
wrong before.

## The convention

This is the whole protocol.

| Directory | Required export | Node kind |
| --- | --- | --- |
| `rag/` | `search(query: str, **kw) -> list` and `index(paths: list[str]) -> None` | RAG |
| `agent/` | `run(message: str, **kw) -> str` | Agent |
| `api/` | `app` (any ASGI application) | Service |
| `worker/` | `HANDLERS: dict[str, Callable]` | Worker |

The export must be reachable from the package's `__init__.py`. Nothing else is inspected.

**A node is defined by its export, never by what is inside the package.** An `agent/` exporting `run`
is an Agent whether it is built on LangGraph, Pydantic AI, CrewAI or a thirty-line loop. The parser
reads `__init__.py`, checks the symbol exists, and never inspects an implementation, imports a
third-party package or branches on a framework name. The one place a stack matters is *generation*,
which is a preference recorded in `.env` and handled in Phase 4 — not a node type.

RAG requires **both** exports: a package that can be queried but never filled is useless in practice,
and having both makes document upload a first-class action rather than a UI special case.

A directory that looks like a system but is missing its export is an **incomplete node** — visible,
grey, with the reason stated. It is never guessed at. A directory not in the table is not a node.

**Tools.** An `agent/` may contain `tools/`, and a module in it that defines a public function is a
node named `agent.tools.<file>`. Its public functions are its **ports**. A module defining none is a
helper and is not a node. Read on the top-level `agent/` only: a sub-agent's tools would be a second
level of nesting.

**Chat.** An `api/` may contain `routes/chat.py`, and that file being there is the whole of
what makes a **chat** node. It is the second named exception beside `agent/tools/`, and it is
one for the same reason: a place a person can see in their own file tree, never a claim about
code. It carries no verdict — its lines are inside the `api/` package and already owned by
whatever test reached them — and its edge to the agent is nothing special, just the route's own
`from agent import run`. The point of tying the chat to a real route is that one implementation
serves both cases: the person building locally opens it from the panel, and the same route
deploys with the project and serves their colleagues. A panel with no code behind it would be a
node outside the convention.

**Settings.** A system may contain `settings.py` with a single `BaseSettings` subclass. The node panel
edits exactly that class and nothing else. A system with no `settings.py` shows no knobs, which is
allowed and normal.

**A knob says when it is not the thing that decides.** A `BaseSettings` field reads the
environment before its own default, so a panel that wrote the file correctly and stayed
silent would be honest about the write and wrong about the effect — the commonest way to
spend an afternoon is a model name in `.env` shadowing the one being edited. `settings.read`
reads the class's `env_prefix` (a literal, or nothing) and asks `envfile.py` which **names**
`.env` sets; a field carries the key that wins. The name only: a value in a payload is one
console log from being permanent.

A **dependency** has no `settings.py` and never will — it is not a package, and a file invented for
it would be the toolchain writing into somebody's project so a panel had something to show. What it
has is the fields other systems spend on it, and `settings.about` gathers those onto its panel:
selected by **the same evidence that put the node on the canvas** (a name that says `OLLAMA_HOST`,
a default that starts `ollama/` or `postgresql://`), grouped by the system whose file they are, and
written through the one writer. Ollama adds one source and only Ollama: a value that *is* the name
of a model this machine has pulled, asked of the local daemon, because a bare tag like `llama3.1`
is otherwise unattributable without the catalogue the plan puts out of scope — and the same list is
offered as **suggestions** under a model field, never as the values it is limited to.

**What a system holds is drawn at both sizes.** A count on a header said "there is more here"
and nothing else, so a project's tools and routes were absent from the picture until somebody
pressed a fold. Folded, one bar stands for the children and the line lands on **it**; open, the
bar becomes the frame and the lines land on the cards inside. Pressing the fold changes what
the line points at, never whether the thing exists. The line is dotted and thinner than an import,
because it is not one.

**Which side it hangs off is what the parts are, not taste.** A service's routes are its own
flow — a request arrives, a handler answers — so they sit to its **left** and run into it the
way every import on this canvas does. An agent's tools are equipment beside it, so they hang
**underneath**, where they cannot be read as a step in anything. Two answers, in a table
(`holdSide`); a third invented from something structural would be a guess about somebody's
architecture.

The bar is not a node: no verdict, no settings, no Run, and **no entry in `layout.json`**. It
can still be moved — dragging it moves the cards it stands for, and what gets written is
*their* coordinates — which is what makes "it opens where you put it" true without this
application storing a position for something the code does not have. Its box is the frame's
box, so opening the fold grows a region under the bar and moves nothing.

**Nesting.** A system may contain others one level down, in a directory named after the plural of the
kind (`agents/`, `rags/`, `workers/`). Only one level is recognised; a third produces no nodes and no
error. Nested nodes are named by path (`agent.researcher`) and are children of their container.
Colour aggregates upward: a parent is green only when every child and its own code are green, red if
any is red, and amber if any is grey and none is red. Amber is a distinct colour, not a shade of
green.

**One system of each kind per level.** At the root there is one `agent/`, one `rag/`, one `api/`, one
`worker/`. Two unrelated top-level agents on different stacks cannot be expressed; if a project needs
that, it is two projects.

**File nodes.** Four files at the project root are nodes with no verdict: `.env`, `compose.yaml`,
`Dockerfile`, `mcp.json`. They are shown, opened and edited. They are never coloured. `.env` is the
one the **canvas does not draw**: nothing imports it, so it was a card at the edge with no line to
anything, and the one thing a person does with it they do from the dependency that reads it, which
is where `Open .env` is. It is still a node — reported, opened, edited — and that is a drawing
decision in `place.ts`, never a node the core withholds.

**Edges.** An edge exists when one system package imports from another, and the direction follows the
import. An edge to an MCP server is read from `mcp.json`. **No edge is ever created by hand in the
UI** — connecting two nodes means writing an import, which is a code edit made by the chat.

**Declared nodes.** Three things are nodes without being packages, alongside the four files: a
**server** in `mcp.json`, a **container** in `compose.yaml`, and the **database** the project's
own code talks to. None has a required export, so none can be incomplete and **none can ever
carry a verdict** — nothing in a test run executes a Postgres. They are not a fifth kind; ask
`is_system(node)` (`isSystem(kind)` in the UI) to tell a package from one of these, and **never
`kind != "file"`**: that meant "is it a package" only while `file` was the sole exception, and
it would have handed `mcp.json` to coverage as a source directory the day servers became nodes.

They differ in where they come from, and the difference is the rule. A server is in the graph,
because `mcp.json` is a file the parser already reads. The database is in the graph for the same
reason — a `__tablename__` and a connection string are in the project's own Python. A container
is **beside** the graph, because the only honest way to learn a service's name is `docker compose
config --services` — a subprocess, a different question, and a different moment to go stale.

**A verdict and a status are different things**, and they never share a colour scale. A verdict
comes from a test and belongs to code you own; a status comes from a connection check and belongs
to something external — a reachable Postgres is not a proven one. Things of the second sort are
**dependencies**: `postgres`, `redis`, `ollama`, `anthropic`, `openai`, `docker`. Each exists
because the code references it — an import root, a string literal in a settings default, a file at
the root — and **there is no manual add**: pressing `+` on one sends a task to the agent to write
the code that uses it, and the node appears because the code now names it.

`status.py` answers `status.read` for one node at a time, because the polling policy is per node.
**No check is ever billable**: a provider reports whether a key is present, by *name*, never by
calling anything. `SELECT 1` and `PING` need drivers this codebase does not have and will not
acquire — a connector written is a connector maintained — so they are scripts run in the
**project's own interpreter**, and a project without the driver gets `unknown` rather than red.
`unknown` and `unreachable` are different claims and are never merged. A check is a short
synchronous ask like `deploy.status`, not one of the six long-lived processes below. Polling stops
entirely when the window loses focus — an idle machine does nothing on a project's behalf.

**Ollama is the one dependency with panel content of its own**, because it is what makes "nothing
leaves this machine" literally true. `ollama.py` asks the local daemon over plain HTTP — no vendor
SDK, because two endpoints are not worth a connector — and a pull follows the P13 shape: a thread
appending to `.framestack/ollama.log`, polled with an offset the caller keeps. **The model list is
never a catalogue.** It is whatever this machine has pulled, asked when somebody looks; a registry
of names shipped with the toolchain would be stale the week after and is exactly what the plan puts
out of scope. For the same reason a **bare** model tag in settings is not recognised as naming
Ollama — that would need such a list — while `ollama/llama3.1` is, because the prefix is a literal
fact about the string.

What a database *is* the project states, and that is all
`database.py` reads: `__tablename__`, `alembic/versions/`, and a connection string out of a
`BaseSettings` default with its credentials removed. **One node per backend, never one per table**
— twelve tables are twelve rows in a panel, and table-level edges are a hairball whose every line
has to choose a table to land on. The base class of a model is never resolved: that would mean
knowing SQLAlchemy, and the parser learns no library, ever.

### The graph is a projection, not an executor

The line that separates this from flow-document builders, and the one most likely to erode under
pressure. Write it into the UI's behaviour:

- Node position carries no meaning. Moving a node changes nothing in the project.
- There is no connect gesture. Dragging from one node to another does nothing.
- There is no run-the-graph button. Execution order lives in Python; `Run` executes one system's
  entry point, never a traversal of the canvas.
- Every structural change is a code edit produced through the chat, then re-parsed.

If a feature request would require the canvas to decide what runs when, it belongs in a different
product.

## Invariants

These hold in every phase. A change that breaks one is reverted.

1. **Code is the only source of truth.** No manifest, no graph file, no state that exists only in the
   UI.
2. **Recognition is deterministic.** The graph is derived from directory structure and import
   statements. No model is involved in producing a graph.
3. **Green is earned by a run.** A check that could not run reports `skipped`, never green.
4. **Observe is reproducible.** Three consecutive runs on an unchanged project produce an identical
   verdict set.
5. **Every edit goes through libcst.** Everything the edit was not about stays byte-identical.
6. **If you delete Framestack, the project still runs.** There is nothing in a user's project that
   only Framestack understands.

## Surfaces

Two, permanently: the **graph** (system nodes, file nodes, edges from imports, colour from the last
Observe) and the **chat** (one agent, one contract: ordinary Python following the convention). Four
commands reachable from the graph — `Observe`, `Run`, `Deploy`, `Open` — and a terminal that is a
slide-out drawer, not a tab. Everything else lives on a node: click it and a **centred dialog** opens with its
settings, its files, its last verdict and its Run controls — a dialog rather than a flyout
because it is everything about one box, and in a 340px column at the edge that is one long
scroll with the node itself hidden behind it. The rail's panels stay flyouts; the node is the
one surface that takes the middle of the window, laid out in two flowing columns where the
column a block lands in carries no meaning.

**Every write goes through libcst, and the smallest one is the model for the rest.**
`settings.write` changes one field's default in one class in one file; `git diff` afterwards is
one line, and a test asks `git` itself rather than taking our word for it. A default built by a
call is shown and refused rather than overwritten, a wrong type is refused with the file
untouched, and the answer is always the file **re-read** — never a description of what the
writer believes it did.

**A control is drawn when the core can answer for it**, and never before: a button whose only
possible outcome is an error is worse than no button. That is why `Run` and `Deploy` arrived last,
beside `run.*` and `deploy.*`. For the same reason the
**graph payload carries no verdict field**: a verdict comes from `observe.*` and is held beside the
graph, never folded into it — they answer different questions and go stale at different moments, and
a node with no entry has no verdict rather than a default one. A default the UI had to remember to
disbelieve is how a node ends up green because it exists.

## The direction, and who this is for

**It looks like the polished commercial builders, it is built like Dagster, and it proves what nobody
else proves.**

Visual builders are the most crowded niche in AI tooling — Langflow, Dify, Flowise, n8n and a long
tail — and the moat is thin. Building another one loses by default and inherits the defect: in every
one of them a node is green **because it exists**, since the flow document is the source of truth and
the code is an export.

The square nobody occupies is a graph over the user's own project, written back through a concrete
syntax tree, with a verdict that comes from running the project's own tests. LangGraph Studio draws a
graph from code but is read-only and framework-locked; the Python node editors keep their own graph
file as the truth; Dagster and Prefect are the precedent that code-first wins a category from a
UI-first incumbent. **Evidence is the moat** — it requires the code to be real and runnable, which is
exactly what the flow-document architectures traded away.

What follows, day to day:

- **The architecture does not move to meet the surface.** The invariants are not negotiable against a
  nicer gesture. A palette that added a node without writing code, a template that shipped its own
  verdict, an edge stored anywhere but in the code — each is the product becoming Flowise.
- **The audience is the engineer.** The commercial builders sell to a non-technical buyer; every
  trade-off here resolves toward someone who reads Python.
- **Local execution is the pitch.** Everything runs on the user's machine or their server. The graph
  is a view of their own Python, so nothing leaves the network unless their code sends it there.

**An incomplete node explains itself, and that is the one place the graph talks back.** A
package that does not bind the name its kind requires is a *fact* — checkable, and checked by
reading the file — so the card names the missing export and offers to send `/repair` with it
named. The button produces a **message**, never a file: the node turns complete when the code
does. The prompt refuses the dishonest fix by name, because an export satisfied by a stub is a
node that says something untrue.

**The palette writes code; it does not draw nodes.** Pressing a block sends one command to the
chat and nothing else — the node appears because the agent wrote a package and the graph was read
again. The blocks are declared by `chat.py`, so a palette cannot offer a command the prompts have
never heard of, and **no code ships with them**: a block carries a command, never a scaffold. A
marker is drawn while a turn runs, and it is a progress indicator rather than a node — no layout
entry, no verdict, no settings, no Run, gone when the turn ends. Each of those absences is a way
it could otherwise outlive its turn, and a marker that outlives its turn is a node the code does
not have.

A **dependency** block is the same rule pointed at something outside the project: pressing one
sends a task to write the client, the settings and the code that uses them, and the node appears
because the project's own Python now names it. The five offered are the five the recogniser
knows — a block that produced code the parser could not see would look like a failure while
being correct. Each block declares `becomes`, the id of the node a press would eventually
produce, which is how the palette enforces "only one" while knowing none of the convention's
rules; it is a thing to *look for*, never an entry to create.

**`Connect` means two things, because `mcp.json` holds two kinds of entry.** A `command`
entry is a **stdio** server: the MCP authorization spec does not describe it, the ones that need
an account open a browser themselves, and `Connect` runs the entry's own command in the terminal
where a person can watch it — the token stays wherever that server keeps it. A `url` entry is an
**HTTP** server, where the spec does apply, and `Connect` runs Phase 10's path one: the person
registers an OAuth app in the provider's own console, pastes the client id and secret, the system
browser opens on the consent screen, and the token lands in `.env` under a name derived from the
server's. `oauth.py` is that flow; PKCE always, one loopback listener per exchange, torn down
after it. **There is no Framestack OAuth app and there will not be one** — every user under one
registration is one revocation away from everybody stopping at once. Dynamic client registration
is path two and is *later*; the manual path is what it falls back to, so the manual path ships.

**A server is connected because it answered, never because it is configured.** `mcpwire.py` is
the smallest MCP client that can exist: `initialize`, `tools/list`, hang up. **The tool count is
the evidence** — the same rule the verdicts follow, applied to somebody else's program — so
`connected · 8 tools` means a server said so at a time, and a server nobody asked has *no* state
rather than a hopeful one. `mcp.probe` is the only thing that may make the claim, because it is
the only thing that asked; `mcp.read` and `mcp.connect` still say only what this application did.
Nothing is stored: an answer about a live process goes stale the moment the process does. And
nothing in this codebase can call a tool — `tools/list` is a question, `tools/call` is somebody's
mailbox.

Only the **names** of an entry's `env`, and of the `.env` keys a server's authorisation uses,
ever leave the file: a value in a payload is one console log from being permanent. `envfile.py`
is where a secret is written and read, line-wise, so everything the edit was not about stays as
the person left it — and what it reads goes into a request header, never into an answer.

## Out of scope

Named so they do not creep in: any granularity below a package (nodes for functions, verdicts on a
function, an annotation layer of any kind); more than one level of nesting; any kind beyond the four;
a gallery of code templates the toolchain owns and ships; multi-project workspaces; cloud sync;
layout persistence beyond node positions; anything requiring a manifest; executing the graph itself;
a catalogue of databases or MCP servers; a reader for anybody else's file format.

If one of these is genuinely needed later, it is a new plan, not an addition to this one.

## Commands

```bash
uv sync                 # Python workspace (core + dev tools)
npm install             # front-end and Tauri CLI

npm run dev             # full app: Vite + Tauri window + Python sidecar
npm run web:dev         # front-end alone in a browser (core absent, ping will fail)
npm run test:py         # all Python tests (core + examples/full's own suite)
npm run check           # scripts/check.sh: ruff lint + format, mypy --strict, pytest — what CI runs
npm run build           # freeze the sidecar (scripts/build-sidecar.sh), then bundle .app/.dmg
```

`scripts/check.sh` is the gate a phase must pass to count as done, and CI runs that same script.
Single test: `uv run pytest packages/core/tests/test_ping.py -q`. Front-end typecheck:
`npm run web:build` (`tsc --noEmit && vite build`).

Talk to the core by hand, no app involved:

```bash
echo '{"id":1,"method":"ping"}' | uv run python -m framestack_core
```

There are no CLI subcommands. The old ones were faces on the parser, the gate, the observer and the
writer; the ones the new design needs are added back beside the capability they drive, never ahead of
it.

A Rust toolchain (rustup) is required — Tauri will not build without it. `.app`/`.dmg` can only be
built on macOS.

### The sidecar shim

`apps/desktop/src-tauri/binaries/framestack-core-<target-triple>` is a **tracked shell shim** that
execs `scripts/dev-sidecar.sh`, so dev mode runs the core from source with no PyInstaller step.
`npm run build` overwrites that file with the frozen binary; `git checkout -- apps/desktop/src-tauri/binaries`
restores the shim. Do not commit the frozen binary.

## Architecture

Three layers, and the boundaries between them are load-bearing:

| Layer | Where | Rule |
| --- | --- | --- |
| React 19 + React Flow | `apps/desktop/src/` | Renders the graph the core returns; never a second source of truth. |
| Tauri 2 / Rust shell | `apps/desktop/src-tauri/src/` | Transport only. Spawn the core, move JSON, match responses by `id`. |
| Python core | `packages/core/` (`framestack_core`) | Parser, gates, writer, orchestration. All decisions live here. |

Inside the core: `protocol.py` is the wire; `handlers.py` is the method table and `api.py` the
payloads it assembles; `parser.py` derives the graph from the convention; `session.py` is the chat
agent's process; `shell.py` is the terminal the person types into; `layout.py` is where a person put
things; `observe.py` runs the project's tests and turns what happened into colour;
`settings.py` reads and writes the one `BaseSettings` class a system may declare;
`database.py` reads what the project stores things in, `dependencies.py` what else its code
talks to, `status.py` whether any of that can be reached, `compose.py` what the stack is made of and
what of it is running, and `routes.py` what one service serves;
`editor.py`
is `Open`; `chat.py` dispatches a message to exactly one command and declares the **blocks** a
palette may offer; `mcp.py` reads one server's entry, runs or authorises it and asks it what it
offers, with `mcpwire.py` speaking the protocol and `oauth.py` driving the browser, and
`envfile.py` is the one place a secret is written; `run.py` calls one system's
export in the project's own interpreter and `deploy.py` brings the compose stack up;
`usage.py` is what a run cost;
`environment.py` is the one place that answers "which Python does this project's own code run in".

**What a run cost is measured, and it is never a verdict.** `usage.py` stores what a provider
answered — a model, an input count, an output count — in `.framestack/usage.db`, and prices it
**on read** from a table in that file, so a corrected table corrects the history it is applied
to. A model the table does not have shows its tokens and no dollar figure; `$0.00` for a run
nobody has a price for is a false statement where "we do not know" is the true one. The
counting is a wrapper installed in the child process `Run` already spawns, written into the
run's own driver: **no import, no decorator and no dependency in the user's project** (I-6).
Delete `.framestack/` and history is lost, nothing else. Langfuse is linked out to where a
project's `.env` names it, never read from and never fallen back to.

**`Run` calls one export and colours nothing.** It is `Run`, not run-the-graph: one node, one of
the exports the convention already requires, no traversal and no order — a child process driven by
a script written as text, because the core imports no user code. A call that returned is not
evidence, so nothing in `run.py` may ever write an observation; a node green because somebody used
it is the flow-document defect arriving through a side door. For the same reason the network is
**not** guarded there while Observe guards it absolutely: Observe must be reproducible, and an
agent that cannot reach a model is one nobody can try.

**`Deploy` is `docker compose up`, and stopping means `down`.** One target, and no line of
`compose.yaml` is read here — the services come from `docker compose config --services`, asked of
the program that owns the format. `up` is a client attached to containers the daemon owns, so
ending the client is not ending the stack: the sidecar runs `down` on its way out, or "closing the
app stops what it started" is a sentence that is not true.

**There is no free-form write path, and `agent.say` is gone rather than discouraged.**
`chat.send` is the only way a person's words reach the agent, and every turn carries the shared
base plus exactly one command's prompt from `packages/core/prompts/` — never more, because an
agent holding all four sets of instructions is back to choosing between them. A message that
does not name its command is classified by the agent binary itself (`--print`, no tools, no MCP
servers, off the transcript), and a classification that is not confident **asks**: a wrong
command writes the wrong files into somebody's project. Prompts are text files so they can be
reviewed without touching Python, and they ship as PyInstaller data — a prompt that exists only
in the repository is one the shipped application does not have.

**`parser.py` is the whole of recognition, and it is one read.** `graph.read` walks the four
candidate directories, parses each `__init__.py` with libcst and reports the node as complete or as
missing a named export; the walk recurses **exactly one level** into `agents/`, `rags/`, `apis/`,
`workers/`. Exports are the names an `__init__.py` *binds at module level* — a name bound under `if
TYPE_CHECKING:`, inside a `try/except ImportError:` or by a star import is not one, because which of
those exist is a question only running the code can answer. Edges come from import statements
(relatives resolved, mapped to a node by longest module prefix) and from `mcp.json`, one per
configured server, drawn from `agent` to the `mcp.json` file node — the servers themselves are not
nodes. There is no `graph.write` and there will not be one.

**The Rust shell exposes exactly one IPC command, `core_request`.** A new capability is a new *method
in the Python core* (registered in `HANDLERS` in
[handlers.py](packages/core/src/framestack_core/handlers.py)), never a new Tauri command. Anything in
Rust that inspects a method name or interprets a result is misplaced logic.

**The wire is NDJSON over the sidecar's stdio** — one JSON object per line, shape defined in
[protocol.py](packages/core/src/framestack_core/protocol.py). `id` is opaque to the core and echoed
verbatim. **stdout carries the wire and nothing else**; every log line goes to stderr, or the stream
is corrupted (there is a test asserting this). A handler that raises is turned into an error
response, never a crash.

**Requests are answered on a thread each, one at a time per method.** A handler that spawns a
subprocess — classifying a chat message, probing a server, asking `docker compose` — otherwise
stops the core answering anything, and the window freezes around it. What that must not do is
let two calls of the *same* method interleave: every long-lived thing here is a dict keyed by
project, and "start it if it is not already running" read twice at once starts it twice. So
`serve` serialises by method and by nothing else, and **no meaning may ever be taken from the
order answers come back in** — `id` is what matches one to its caller, which is why this is a
fact about the core alone.

**The graph follows the code, and it does so by being asked.** `watch.py` holds a revision per
project and moves it when a file the parser reads has changed *and stopped changing* — the
plan's 300ms settle, so a file an editor is halfway through writing never reaches the parser.
The window keeps the number and asks; **nothing is pushed**, which is why live re-parse needed
no second message type. It does not ask while a chat turn is running: the agent writes several
files per task, and the turn's own end already re-parses once. A `stat` scan rather than a
file-system event API — no dependency, no platform backends, and a project cheap to parse is
cheap to watch.

**A file that does not parse marks one node and blanks none.** `Node.broken` is
`"chunker.py line 42"`, and nothing else about the node moves for it: the exports still come
from `__init__.py`, the path is still the directory's. That is what "keep the last good
version" means here, and it needs no cache to hold — a cache of a previous parse would be
state outside the code, which is the one thing this application does not keep.

**Nothing is pushed over the wire.** One request, one answer with `id` echoed — in whatever order
the handlers finish; logs are polled with an offset the caller keeps. Adding a second message shape is a protocol version decision, available
later and additive — do not reach for it as a convenience.

**Nothing starts implicitly.** No service is brought up, no environment created, no dependency
installed, except because somebody pressed a button. Observing runs the project's tests; it does not
bring a container up.

**Outside Python, ask rather than read.** The parser learns no library and no file format, ever. A
compose file is asked of `docker compose config`, a service of the port it publishes, a database of a
connection. Never add a Dockerfile reader or a migration reader to this codebase: a
parser for someone else's format is a second opinion about a thing that already has a first one, and
it is wrong in ways that look right.

**`compose.py` is the one exception, and its shape is the reason it is allowed.** A panel that
edits `image`, `ports`, `environment`, `volumes` and `depends_on` has to show what is there first,
and it has to put back what it changed without touching the rest — so that file is opened, through
a round-trip loader that preserves comments, key order and quoting, exactly as `settings.py` does
for Python. It is a **writer that reads what it is about to write**, not a second opinion about the
stack: which services exist is still `docker compose config --services`, whether one is up is still
`docker compose ps`, and `deploy.py` still reads not one line of the file. Five fields, named in
`EDITABLE`; a sixth is refused by name rather than quietly ignored.

**Observe is the only thing that executes a project, and it earns every colour it draws.** A node
is green because a passing test ran code inside it — the join of coverage.py's dynamic contexts and
pytest's JUnit report, on the test's name, with no naming convention or directory heuristic
anywhere in it. `grey` ("no test reached it") and `skipped` ("the run did not happen") are
different claims and are never merged; a run that reached the network is `skipped` outright,
because a check that passes or fails for reasons outside the repository is not evidence. Code
executed at *import* time earns nothing: its coverage context is empty, and a module imported during
collection has been proven by nobody.

**The core imports no user code.** Everything reads statically so that drawing a graph never runs a
stranger's code; a project that hangs or crashes must cost a subprocess rather than the core the UI
is talking to.

**Seven things spawn a process** and they are one shape: the chat agent (`agent.*`, in
`session.py`), the terminal (`shell.*`), Observe (`observe.*`), `Run` (`run.*`), `Deploy`
(`deploy.*`), `Connect` (`mcp.connect`, which opens a terminal and runs the server's own command,
or opens a browser on a provider's consent screen) and the probe (`mcp.probe`, which starts a
stdio server, asks it for its tools and stops it again). All of them follow the same rules:
nothing is pushed, output is polled with an offset the caller keeps, a record on disk survives a
crash, and nothing starts implicitly. The probe is the one that keeps nothing — its whole answer
is one short synchronous ask, like `status.read`, because what it is about does not outlive it. For Observe, *running* means the run table still holds it —
the suite exiting is not the end of the run, because the coverage database and the test report
still have to be read, and a caller told "idle" in that window would take the previous verdict set
for the new one. The agent is denied writes to `.framestack/`, because an agent
that could edit the state directory would be forging evidence about itself.

**A permission is a question with an answer.** `--permission-prompt-tool stdio` makes the agent's
stream two-way: it sends a `can_use_tool` control request and **stops**, and `agent.permission` writes
the `control_response` the turn is blocked on, so the same turn carries on rather than being retried
after a settings change. `updatedInput` is echoed back and never rebuilt — a response carrying
anything else would be this toolchain editing a command on its way to a shell.

**The person owns the layout; the code owns the graph.** Node positions live in
`.framestack/layout.json`, reached through `layout.read` / `layout.write` because the webview may call
`core_request` and nothing else. **The core stores it and refuses to understand it**: the contract is
`"<opaque>"`, and the refusal is the protection — a core that knew what a coordinate was would end up
being asked to produce a layout. It answers one question, "where do I draw this node?", and **cannot
add, remove or rename one**: a node with no entry still draws, an entry with no node is unused, and
orphaned coordinates are kept rather than tidied on sight, because an agent rewriting a file makes a
node vanish and come back.

## The examples

Three projects in [examples/](examples/), and they are the fixtures as well as the demonstrations:

* **[examples/full/](examples/full/)** — the whole convention: four systems, a chat route, a
  database in `repositories/`, and the four file nodes. It is the project the builder is written
  against, what the parser is tested on, and what every acceptance criterion in the plan is stated
  about. Change it only deliberately.
* **[examples/rag/](examples/rag/)** — upload, index, ask. Two systems and **no storage**, which is
  why the database tests use it: a test asking "does adding a model add a row" has to start from no
  rows.
* **[examples/agent/](examples/agent/)** — an agent with three tools, one file each, and one MCP
  server.

Each runs with `docker compose up`, passes its own suite with the builder uninstalled, and holds no
credential. **Their suites run in separate processes** — every one of them declares a `rag/` or an
`agent/`, because the convention names those directories, and one interpreter can hold one of each.
`pyproject.toml` runs the core's tests beside `examples/full`, and `scripts/check.sh` runs the other
two on their own.

`examples/full`'s `agent/tools/look_up.py` imports from `rag`, which is the only reason there is an
edge between those two nodes — and the edge belongs to that tool rather than to the agent, which is what makes an
agent node stop being opaque. It carries no Framestack-specific symbol of any kind, and `pytest`
works in it with the builder uninstalled — which is invariant 6, stated as a fixture.

`examples/full`'s suite runs in this repository's `pytest` too: an example whose tests do not pass is
a fixture that proves nothing.

## Conventions

Comments in this codebase explain *why a thing is the way it is* — which invariant it protects, what
breaks without it — rather than restating the code. Match that; a new module without that reasoning
reads as foreign here.

`docs/` is the source of truth for what gets built. **It is gitignored — local only, never
committed.** Anything the toolchain has to read at runtime therefore does not belong there. Nothing
in `docs/` may become a test input or a build input.

`assets/` is the opposite case and is **committed**: it holds the brand art — the logo the README
renders and the light mark the app icon is generated from. A logo a clone does not have is a broken
image on the project's front page. Nothing there is read at runtime either; `npx tauri icon` turns
one file in it into `apps/desktop/src-tauri/icons/`, by hand, and it is the *output* that ships.

The product is **Framestack AI Builder**. The toolchain package is `framestack-core` /
`framestack_core` (the sidecar), and the state directory it writes in a user's project is
`.framestack/`.

Note: the git repository root is the **parent** directory (`Awesome Blueprints/`), a monorepo holding
this project alongside `Awesome AI Blueprints` and `Awesome Blueprints Website`.
