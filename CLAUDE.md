# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A visual builder for Python applications in which **the Python code is the source of truth** and the
node graph is a projection of it. A project stays ordinary Python; the graph is derived from its
directory structure and its imports, and a node is green only when a real test run entered it.
Assembled applications deploy as plain Python projects with no runtime dependency on the builder.

**The repository is mid-rebuild, and the plan is `docs/framestack_rebuild_plan.md`.** Read it before
proposing anything: it is the specification, and *rule zero is that anything not described in it is
deleted*. Phase 0 (demolition) and Phase 1 (the read-only graph) are done. Phases 2–5 —
Observe, the settings panel, the chat and Run/Deploy — are ahead, in that order, one at a time.

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

There is one layer. A node is a package that satisfies the convention, and that is the only
granularity the application knows. Nesting one level down uses the same rule, so a sub-agent is a
node for the same reason its parent is. **Nothing finer exists** — no nodes inside a package, no
verdict on a function, no annotations. That granularity would need a second mechanism on top of the
convention, and building a second mechanism is what produced the problem this rebuild is fixing.

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

**Settings.** A system may contain `settings.py` with a single `BaseSettings` subclass. The node panel
edits exactly that class and nothing else. A system with no `settings.py` shows no knobs, which is
allowed and normal.

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
`Dockerfile`, `mcp.json`. They are shown, opened and edited. They are never coloured.

**Edges.** An edge exists when one system package imports from another, and the direction follows the
import. An edge to an MCP server is read from `mcp.json`. **No edge is ever created by hand in the
UI** — connecting two nodes means writing an import, which is a code edit made by the chat.

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
slide-out drawer, not a tab. Everything else lives on a node: click it and a panel opens with its
settings, its files, its last verdict and its Run controls.

**A control is drawn when the core can answer for it.** `Observe` arrives with Phase 2, `Run` and
`Deploy` with Phase 5. A button whose only possible outcome is an error is worse than no button. For
the same reason the graph payload carries **no verdict field at all** until Phase 2: a default the
UI had to remember to disbelieve is how a node ends up green because it exists.

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

## Out of scope

Named so they do not creep in: any granularity below a package (nodes for functions, verdicts on a
function, an annotation layer of any kind); more than one level of nesting; any kind beyond the four;
a blueprint library or template gallery; multi-project workspaces; cloud sync; layout persistence
beyond node positions; anything requiring a manifest; executing the graph itself.

If one of these is genuinely needed later, it is a new plan, not an addition to this one.

## Commands

```bash
uv sync                 # Python workspace (core + dev tools)
npm install             # front-end and Tauri CLI

npm run dev             # full app: Vite + Tauri window + Python sidecar
npm run web:dev         # front-end alone in a browser (core absent, ping will fail)
npm run test:py         # all Python tests (core + the reference project's own suite)
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
things. The observer and the writer are rebuilt on the convention in the phases ahead and land
beside these.

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

**Nothing is pushed over the wire.** One request, one answer with `id` echoed; logs are polled with
an offset the caller keeps. Adding a second message shape is a protocol version decision, available
later and additive — do not reach for it as a convenience.

**Nothing starts implicitly.** No service is brought up, no environment created, no dependency
installed, except because somebody pressed a button. Observing runs the project's tests; it does not
bring a container up.

**Outside Python, ask rather than read.** The parser learns no library and no file format, ever. A
compose file is asked of `docker compose config`, a service of the port it publishes, a database of a
connection. Never add a YAML reader, a Dockerfile reader or a migration reader to this codebase: a
parser for someone else's format is a second opinion about a thing that already has a first one, and
it is wrong in ways that look right.

**The core imports no user code.** Everything reads statically so that drawing a graph never runs a
stranger's code; a project that hangs or crashes must cost a subprocess rather than the core the UI
is talking to.

**Four things spawn a process** and they are one shape: the chat agent (`agent.*`, in `session.py`),
the terminal (`shell.*`), and — from Phase 5 — `Run` and `Deploy`. All four follow the same rules:
nothing is pushed, output is polled with an offset the caller keeps, a record on disk survives a
crash, and nothing starts implicitly. The agent is denied writes to `.framestack/`, because an agent
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

## The reference project

[examples/reference/](examples/reference/) is the project the builder is written against: four
systems, four file nodes, and a test suite that proves each export does something. It is what the
parser is tested on and what every acceptance criterion in the plan is stated about. Change it only
deliberately.

Its `agent/tools.py` imports from `rag`, which is the only reason there is an edge between those two
nodes. It carries no Framestack-specific symbol of any kind, and `pytest` works in it with the
builder uninstalled — which is invariant 6, stated as a fixture.

The reference's suite runs in this repository's `pytest` too: a reference whose tests do not pass is
a fixture that proves nothing.

## Conventions

Comments in this codebase explain *why a thing is the way it is* — which invariant it protects, what
breaks without it — rather than restating the code. Match that; a new module without that reasoning
reads as foreign here.

`docs/` is the source of truth for what gets built. **It is gitignored — local only, never
committed.** Anything the toolchain has to read at runtime therefore does not belong there. Nothing
in `docs/` may become a test input or a build input. `assets/` holds design references not wired into
the build, and is gitignored for the same reason.

The product is **Framestack AI Builder**. The toolchain package is `framestack-core` /
`framestack_core` (the sidecar), and the state directory it writes in a user's project is
`.framestack/`.

Note: the git repository root is the **parent** directory (`Awesome Blueprints/`), a monorepo holding
this project alongside `Awesome AI Blueprints` and `Awesome Blueprints Website`.
