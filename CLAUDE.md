# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A visual builder for Python applications in which **the Python code is the source of truth** and the
node graph is a two-way projection of it. A coding agent writes ordinary Python plus an inert,
AST-addressable markup layer (`bp`); a parser projects that into a graph; edits made in a node are
written back through the syntax tree with `libcst`. Assembled applications deploy as plain Python
projects with no runtime dependency on the builder.

Current state: **P0–P21 done.** Window opens, React Flow renders a
scaffold canvas, Rust reaches the Python core over NDJSON, the five `bp` primitives exist and are proven inert, and
`strip` removes the markup with the example service answering identically before and after. The parser
turns an annotated project into a graph IR, the static gate judges it into addressed diagnostics, and
the observable checks run the project to prove nodes actually work, and reconciliation reports what
no longer matches the last valid state, the writer edits knobs and node declarations back into
code through the syntax tree, and the repair system acts on divergences — or refuses to, and says
who must decide, the agent integration assembles one brief for both inputs and logs what the agent
gets wrong, and the FastAPI slice runs end to end — brief, graph, knob write, breakage, repair, green
again, stripped copy proving the same things — and the same loop closes on a LangGraph agent and a
RAG pipeline, which is what makes the mechanism general rather than FastAPI-shaped. Everything around
the application is there too: the environment it runs in (P11), the vocabulary for a database, a vector
store and docker (P12), the ability to run and stop things (P13), background work (P14), and MCP with
the three roles that wear the word "tool" (P15), the workspace itself (P16), and using what was built
(P17): a pipeline handed its documents, an agent talked to from its own node with the answer counting
as evidence, and the project's own commands run from inside the builder.

**"Python only" bounds the application's source language, not the project's contents.** Docker files,
compose, migrations and environment configuration are part of a production project and in scope. Such
an artifact **may be a node carried by the file itself** (Q10, which amended I-3): the file stays the
source of truth — read, acted on, never regenerated from the node — it carries no markup, and its kind
comes from the registry rather than from a bare filename match. Knobs only where a key in a structured
format can be addressed; actions instead of knobs where it cannot; green only when the image actually
built or the services actually came up (I-5).

A file-carried node is built as [architecture §5.7](docs/architecture.md) describes, and it is built: **a reader
beside the parser, never inside it** — `parser.py` keeps meaning "Python source into IR" and learns
no file formats; identity is the project-relative path; knobs are declared by the kind rather than by
the file; reconciliation tracks only the keys the graph wrote; and the checks live in the runner, not
in `probe.py`, which is the module that imports the user's project and must stay the only one.

**Background work is a subsystem, and its two claims are different claims** (P14). A queue, its tasks
and its schedule are a top-level group of their own — never members of the service — because a task
outlives the request that queued it and runs in a process the service never starts. *The task works*
is proven by a run that entered it (the project's tests, in eager mode); *the queue delivers* is
proven by the broker answering and a worker replying to a ping. Never let one stand in for the other.
A task's carrier stays a **plain function** with registration in a generated zone: a carrier wrapped
in a task decorator is no longer the function the graph named, and a run through it cannot be seen.
The worker refuses to start while the broker is down instead of bringing it up, and its readiness is a
reply through the queue, never a line in a log.

**MCP is three roles, and none of them is the others** (P15). A server this project *consumes* is a
declaration of how to reach a foreign program — the node is the declaration, never the server, exactly
as `compose.yaml` declares `redis:7-alpine` without redis's source being in the repository. A tool this
project *exposes* is its own code and is a node. A tool *bound to an agent* is `langgraph.tool`,
because "bound" is a fact the compiled graph holds. **A remote tool is contents, never a node** (Q12):
it has no carrier, so it is read from `tools/list` and shown on the server's node, and what the agent
may call is a knob. Servers are configured in the project's Python, never in a `.mcp.json` — that file
is the *builder's* configuration and is out of scope.

**Connecting is an action, and the check has no path to one.** `mcp.server_reachable` never connects
and no flag makes it; `mcp.inspect` / `mcp.call` are the buttons, and they run in the project's
interpreter through the project's own `connect()`. Straight into the SDK and the tracer sees only
library frames — no flow arrow, so no evidence the agent uses the server at all. **A knob never holds
a secret**: it holds the *name* of the environment variable, or the first write puts somebody's key on
its way to git. **Nothing about a connection is written down**, which is what makes a stale graph
impossible rather than merely unlikely.

**If it is not on the graph, it is not in the code** (Q12, P15). I-3's missing half: every carrier has
a node, checked by **asking the library what it holds** after a run — never by parsing. A surplus is a
diagnostic with an address (`graph.undeclared_carrier`) and it does not touch `accepted`, because the
gate is a static judgement and this one needed a run. The claim carries its own `proven` / `unproven`
state, the probe imports **every** module rather than only the annotated ones, and a module that will
not import costs the claim rather than the nodes. Kinds opt in through `NodeKind.completeness`.

**The workspace is StackAI's and the architecture is unmoved** (P18). An icon rail and a top bar
around a full-bleed canvas; the dock is deleted and its faces went to the rail, onto the node, and
into a sheet nobody has to look at. The node card is the reference's, element for element -- a family
tab above it, a header, a description line, field blocks, a pill -- with one swap that is the point of
the whole redesign: **their footer carries telemetry and ours carries evidence**, so
`proven by test_users.py::test_create` is drawn in the pixels a competitor spends on a token count.
Light is the base and dark the exception, and every token has a value in both. `Observe` is the black
primary where the reference puts `Publish`, because the most emphatic button on the screen is the one
that produces evidence. Nothing here needed a new core method: the payload gained the test's id as
data (I-5's evidence, addressable rather than parsed out of prose) and the carrier's first docstring
line (Q29), and every panel is still a view of one `graph.read`.

**The registry is the boundary, and now it is visible** (P19). `kinds.REGISTRY` has always been the
honest limit of what can be proven -- a kind outside it has no observable check, so a node of it could
never be more than unproven -- and nothing had ever shown it to anybody. The library behind `+` is a
view of `graph.kinds`: every kind under its family, with what carries it and what proves it. **The
front end holds no list of kinds and no list of families**; `family_of` and `families()` are the
registry's own rule, sent in the payload, because a family exists *because a kind named it*. The first
version of that panel had its families hard-coded and silently omitted `db` and `vector` -- four kinds
that appeared nowhere -- which is what `test_every_kind_belongs_to_a_family_the_registry_reports`
exists to prevent. A blueprint catalog joins the same panel when one is **named** (`FRAMESTACK_BLUEPRINTS`
or a caller), and never when one merely happens to be on the disk.

**An insert produces code and nothing else** (P20, Q28). A catalog entry may carry real annotated
working code under `files/`; `blueprint.plan` says what it would write and `blueprint.insert` writes
it, taking **the plan's identity as a required keyword with no default** — `apply_repair`'s shape, so
there is no call that writes a stranger's Python without having been handed the description of it, and
it is checked rather than trusted. Downstream nothing can tell an inserted node from a written one,
because there is nothing to tell: the gate, the checks, the snapshot and the writer only ever see
files. **The inserted node is not green** — it proves itself by a run, or I-5 has a back door.
A collision is a **refusal with an address, never a merge**; containment denies `.framestack/` exactly
as the agent is denied it; and **arriving is not running** — no import, no install, **no post-insert
hook, ever**. Two sources and no third: the catalog bundled in the package
(`framestack_core/blueprints/`, which is data — the module beside it is `blueprint.py`), and a path
somebody named. **Nothing about an entry's origin is written down**, so upstream drift cannot exist;
the git diff is the record. A bundled entry is **authored, not copied** from `examples/` (Q30) — an
example is a whole project and collides on its first path — and what holds the two in step is that
every bundled entry is planned and inserted into an empty project in the test suite, with the gate
having to accept the result.

**The person owns the layout; the code owns the graph** (Q13). Node positions live in
`.framestack/layout.json` — and, since P18, whether a card shows all of its knobs or the first few,
which is the same kind of fact about the same person — tooling state beside `run.json` and the
snapshot, reached through
`layout.read` / `layout.write` because the webview may call `core_request` and nothing else. **The core
stores it and refuses to understand it**: the contract is `"<opaque>"`, and the refusal is the
protection — a core that knew what a coordinate was would end up being asked to produce a layout. It
answers one question, "where do I draw this node?", and **cannot add, remove or rename
one**: a node with no entry still draws, an entry with no node is unused, and orphaned coordinates are
kept rather than tidied on sight, because an agent rewriting a file makes a node vanish and come back.
Which is also why there is no `node.create` (Q14): a node exists because code declares it, so "add a
node" is a generation, and the new ids are a set difference the canvas computes rather than guesses.

**Four things spawn a process, and they are one shape** — `run.*` (uvicorn), `work.*` (celery),
`agent.*` (Claude Code, in `session.py`) and `talk.*` (the project's own interpreter, in
`converse.py`). All four follow P13: nothing is pushed, output is polled with an offset the caller
keeps, a record on disk survives a crash, and **nothing starts implicitly**. The agent being one of
them is Q16 amended about *where the process lives* and nothing else: the core still holds no HTTP
client to a model and no SDK, and every decision about what to ask and what to do with the answer
stays in the application. The agent is denied writes to `.framestack/`, because an agent that could
edit the snapshot would be forging evidence about itself.

**A permission is a question with an answer** (Q21, amending Q17). `--permission-prompt-tool stdio`
makes the agent's stream two-way: it sends a `can_use_tool` control request and **stops**, and
`agent.permission` writes the `control_response` the turn is blocked on, so the same turn carries on
rather than being retried after a settings change. `updatedInput` is echoed back and never rebuilt —
a response carrying anything else would be this toolchain editing a command on its way to a shell —
and "Always" sends back **the rules the agent itself suggested**, which it writes into the project's
own `.claude/settings.local.json`. Because a person is on the other end, the deny-list is only
`.framestack/`: a denied tool never asks, so anything refused by name is the one thing they cannot
overrule. What is stored on this side is which requests were answered and nothing about policy —
the stream carries no line for an answer, so without it every re-read would resurrect a decision.

**Talking to what the project built is an action on a node, never a node of its own** (Q18, P17). A
chat surface has no carrier, so by I-3 it is not a node, and a node the canvas draws rather than the
code declares is the second source of truth I-1 forbids — the precedent is P15's `mcp.inspect` and
`mcp.call`, which are buttons on the server's node. The message reaches the project through
`probe.py` as a new `ask`, **never by spawning the project's CLI and reading its output** (§5.8) and
never over HTTP, which would make an agent with no web layer require one. **The project remembers the
conversation** — its checkpointer, its `thread_id` — which is why the process lives between questions
rather than being spawned per turn, and why nothing about the dialogue is stored on this side.

**A conversation is evidence, and it expires with the conversation** (P17.4). A person asked a real
question, a real process ran the real code, something real came back: that is I-5 satisfied at the rank
`run.call` has. It ranks **below the project's tests and above the direct checks**, and that ranking
lives in `probe.run_plan` and nowhere else — the plan carries what was said, the probe decides what it
is worth. Nothing is written down: `conversations_held` reads the open transcript, so closing a
conversation takes its claim with it and a colleague who has not talked to the node sees `unproven`
rather than somebody else's yesterday. A conversation nobody had proves nothing.

**Indexing is the same relation with a different verb** (P17.5). A kind opts in through
`NodeKind.indexes`, the entry point is the `build_index()` the system prompt already guarantees, and
what comes back is **what the store said afterwards** — its type and what it answers `len` with, never
the documents that went in. `len` is Python's own question; reaching past it into a library's internals
would need a `kinds.TECHNOLOGIES` entry, which RAG deliberately does not have.

**A terminal is not a verb on a node, which is why it may run what a verb may not** (Q22).
`shell.*` opens the person's own `$SHELL` on a **pty** in the project's directory and they type
into it; `command.start` still refuses anything the project does not declare. The two are not in
tension: `command.*` is a button whose result the graph is asked to mean something by, and a shell
makes no claim about anything -- it colours no node, proves no check and is read by nothing. It is
the sixth process of the P13 shape, `write` sends **verbatim** (the newline is the caller's, and so
is `\x03`), closing a tab signals the **process group** so a server started in it cannot outlive it,
and a shell is the sidecar's lifetime because a pty master cannot be reopened from a pid.

**A front end is run, not modelled** (Q20, P17.6–17.7). No nodes, no knobs, no verdict: one verb to
start it, one to stop it, and a node that cannot be red would be decoration. The commands are **asked
of `npm pkg get scripts`**, never read out of `package.json` (§5.8), the directory to ask in is passed
in rather than discovered, and a **name the project declares still means the project's own command** —
`npm run <name>`, so the vocabulary the project owns cannot be shadowed by a file appearing on the
path. Anything else is run as typed: P17.7's rule against arbitrary strings was **removed** (Q22),
because the objection it rested on — that would be a shell with a button on it — stopped being an
objection when this application gained a real shell on purpose, and because nothing `command.*` starts
goes on the graph, so there is no claim a stranger's command could falsify. What is still enforced is
containment: the directory must be inside the project. `command.*` is the fifth process of the P13
shape and it waits for nothing: a dev server picks its own port and announces it in prose, so the start
proves only that it did not fall over, and the panel says "running", never "ready" — and a command that
*finished* is reported as finished rather than as a fall-over, because `git status` is supposed to end.

**A contract edge and a flow are different relations** (Q9). Edges are types crossing a boundary, read
from signatures. Flow — a pipeline's order, an agent's wiring — is never parsed out of assembly code
and never declared in markup; it comes from a run: the compiled graph the framework exposes, or the
order instrumented carriers were entered in. No run, no flow arrows.

[examples/fastapi-service/](examples/fastapi-service/) is the annotated reference project: it is what
the parser is written against, and the shape every generation rule in the system prompt has an
instance of. Change it only deliberately — the graph snapshot test compares against it byte for byte.
[examples/mcp-agent/](examples/mcp-agent/) is the one that holds all three MCP roles at once — it
consumes the server it exposes, which is what keeps that path exercised on a machine with no accounts
and no network. [examples/langgraph-agent/](examples/langgraph-agent/) and
[examples/rag-pipeline/](examples/rag-pipeline/) are the other two topologies: a group over state
nodes, and a group over pipeline stages whose **knobs live on the stages themselves**. Each example
carries its own test suite, and that suite is the run its graph is observed by — a stage with no test
is a node with no evidence, by design.

Note: the git repository root is the **parent** directory (`Awesome Blueprints/`), a monorepo holding
this project alongside `Awesome AI Blueprints` and `Awesome Blueprints Website`.

## The direction, and who this is for

Settled by a competitive read of the visual-builder market, recorded in full as Q25. Read it before
proposing anything that changes the shape of the product.

**It looks like StackAI, it is built like Dagster, and it proves what nobody else proves.**

Visual builders are the most crowded niche in AI tooling — three of the top five agent repositories
on GitHub are one (Langflow ~146k stars and owned by DataStax/IBM, Dify ~136k, Flowise ~51k),
alongside n8n and a long tail, and reviews of that market say plainly that the moat is thin and
switching costs are low. Building another one loses by default and inherits the defect: in every one
of them a node is green **because it exists**, since the flow document is the source of truth and the
code is an export.

The square nobody occupies is a graph over the user's own project, written back through a concrete
syntax tree, with a verdict that comes from running the project's own tests. LangGraph Studio draws a
graph from code but is read-only, framework-locked and cloud-tied; Nodezator, Ryven and the other
Python node editors keep their own graph file as the truth; Dagster and Prefect are the precedent
that code-first wins a category from a UI-first incumbent. **Evidence is the moat** — it requires the
code to be real and runnable, which is exactly what the flow-document architectures traded away.

What follows from that, day to day:

- **The architecture does not move to meet the surface.** I-1, I-3 and I-5 are not negotiable against
  a nicer gesture. A palette that added a node without writing code, a template that shipped its own
  verdict, an edge stored anywhere but in the code — each is the product becoming Flowise.
- **The surface is borrowed on purpose, and completely.** Legibility, a searchable library of what
  may be built, dense node cards showing their main knobs without being opened, one control cluster.
  Blueprints decides what a thing *is*; StackAI decides how it is *shown* (Q26). The existing layout
  is not defended — it grew a panel per phase.
- **The palette is the fast path, never the boundary.** `kinds.REGISTRY` is already the honest limit
  of what can be proven; showing it answers "what can I build" at no architectural cost, and a
  catalog entry carrying real annotated code makes the common case deterministic and free of tokens.
  The agent stays for everything the catalog does not have — a user reaches the edge of any palette
  in week one, and that is the reason to be code-first and open source.
- **The audience is the engineer.** StackAI sells to a non-technical buyer; "the same legibility with
  more technical detail" is a different person, and every trade-off resolves toward them.
- **The differentiator does not survive a screenshot.** "Green because `test_retrieval.py` entered
  it" belongs on the node card, not three clicks away, or the project is compared to Langflow on
  looks and found to be the same thing.

## Commands

```bash
uv sync                 # Python workspace (bp + core + dev tools)
npm install             # front-end and Tauri CLI

npm run dev             # full app: Vite + Tauri window + Python sidecar
npm run web:dev         # front-end alone in a browser (core absent, ping will fail)
npm run test:py         # all Python tests (pytest across packages/bp + packages/core)
npm run check           # scripts/check.sh: ruff lint + format, mypy --strict, pytest — what CI runs
npm run build           # freeze the sidecar (scripts/build-sidecar.sh), then bundle .app/.dmg
```

`scripts/check.sh` is the gate a phase must pass to count as done; CI
(`.github/workflows/ai-builder.yml`, at the **monorepo root**) runs that same script and nothing else,
plus a check that the built `bp` wheel has no `Requires-Dist`.

Single test / subset: `uv run pytest packages/core/tests/test_ping.py -q`, or
`uv run pytest -k inert -q`. Front-end typecheck: `npm run web:build` (`tsc --noEmit && vite build`).

Read the graph out of a project, or strip its markup (the mechanical form of I-2):

```bash
uv run python -m framestack_core graph examples/fastapi-service
uv run python -m framestack_core check examples/fastapi-service
uv run python -m framestack_core check examples/fastapi-service --observe   # runs the project
uv run python -m framestack_core snapshot examples/fastapi-service
uv run python -m framestack_core status examples/fastapi-service
uv run python -m framestack_core set-knob examples/fastapi-service api.settings page_size 50
uv run python -m framestack_core set-body examples/fastapi-service health app.api.health.health -
uv run python -m framestack_core repairs examples/fastapi-service
uv run python -m framestack_core blueprints
uv run python -m framestack_core brief examples/fastapi-service --request "add a users router"
uv run python -m framestack_core failures examples/fastapi-service
uv run python -m framestack_core work examples/service-with-worker
uv run python -m framestack_core inspect examples/mcp-agent agent.notes
uv run python -m framestack_core tool examples/mcp-agent agent.notes summarize '{"text": "One. Two."}'
uv run python -m framestack_core index examples/rag-pipeline rag
uv run python -m framestack_core commands .
uv run python -m framestack_core command . web:dev
uv run python -m framestack_core command-logs .
uv run python -m framestack_core command-stop .
```

The brief is the agent's whole input: the system prompt verbatim, the request (a sentence, a
blueprint's specification text, or both), and the project as it stands. **Both inputs carry the same
prompt, byte for byte** — §3's rule that the annotation rules live in the prompt and not in the
blueprints is a test, not a convention. **A blueprint catalog is never discovered** — its location is
passed in by the caller or set in `FRAMESTACK_BLUEPRINTS`, and with neither, input B is simply
unavailable. Nothing reads a directory because it happens to sit next to the project: what the agent
is told must not depend on the shape of someone's disk. When a catalog is given, only `blueprint.md`
is read from an entry, never the `architecture.mmd` beside it.

The system prompt is package data at
[packages/core/src/framestack_core/prompts/system-prompt-claude-code.md](packages/core/src/framestack_core/prompts/system-prompt-claude-code.md),
not documentation: the core reads it at runtime, a test asserts its `kind` table against the registry,
and the frozen sidecar bundles it. Never add a second copy anywhere — two files would mean two sets of
rules, and the one in force would be whichever was found first.

**Every family in the registry has a generation-rules section, and that is checked rather than
remembered.** A section belongs to a family because its *heading names it* — which is why the ones
that do not read as a family name carry the prefix in backticks (`` (`queue.*`) ``) — so
`test_every_family_the_registry_reports_has_generation_rules` can walk `kinds.families()` and demand
one per family. A `kind` row with no rules beside it tells an agent that a value exists and not what
shape the code around it takes. The same derivation splits stack-specific from universal for P22's
trigger: the prompt is composed per project only once it passes ~60KB or the stack half outweighs the
core, and `test_the_prompt_has_not_reached_the_size_that_triggers_composition` measures both on every
run. When it fails, do the phase — never raise the number.


```bash
uv run python -m framestack_core strip examples/fastapi-service /tmp/stripped
```

Talk to the core by hand, no app involved:

```bash
echo '{"id":1,"method":"ping"}' | uv run python -m framestack_core
```

A Rust toolchain (rustup) is required — Tauri will not build without it. `.app`/`.dmg` can only be
built on macOS; see the README's signing section before planning a release.

### The sidecar shim

`apps/desktop/src-tauri/binaries/framestack-core-<target-triple>` is a **tracked shell shim** that
execs `scripts/dev-sidecar.sh`, so dev mode runs the core from source with no PyInstaller step.
`npm run build` overwrites that file with the frozen binary; `git checkout -- apps/desktop/src-tauri/binaries`
restores the shim. Do not commit the frozen binary.

## Architecture

Four layers, and the boundaries between them are load-bearing:

| Layer | Where | Rule |
| --- | --- | --- |
| React 19 + React Flow | `apps/desktop/src/` | Renders the graph the core returns; never a second source of truth. |
| Tauri 2 / Rust shell | `apps/desktop/src-tauri/src/` | Transport only. Spawn the core, move JSON, match responses by `id`. |
| Python core | `packages/core/` (`framestack_core`) | Parser, gates, snapshot, writer, repair, orchestration. All decisions live here. |

Inside the core: `markup.py` (how `bp` is spelled — the one place that knows) and `paths.py` (what
counts as project source) are shared by everything; `kinds.py` is the node-kind registry; `ir.py` is
the graph IR; `parser.py` reads a project into it; `gate.py` judges it; `diagnostics.py` holds the
diagnostic record and the closed catalogue of codes; `verdict.py` is the single green verdict;
`api.py` assembles the versioned payload and declares its schema; `observe.py` runs the observable
checks and `probe.py` contains them; `snapshot.py` records the outline of the last valid state and
`reconcile.py` diffs against it; `writer.py` writes back through `libcst`; `repair.py` acts on
divergences; `converse.py` talks to a node in the project's own interpreter;
`shell.py` is the terminal the person types into; `environment.py` is the project's interpreter
and the services it declares; `artifacts.py` finds the
nodes carried by a file and `project.py` composes them with the parser's; `runner.py` checks them, runs
the application and holds the verbs that act on it — including the two that reach a consumed MCP
server, the one that hands a pipeline its documents, and the ones that list and run the project's own
commands; `agent.py` assembles the agent's brief and records its failure modes, `catalog.py`
reads the two blueprint catalogs and `blueprint.py` plans and inserts an entry that carries code;
`compose.py` is the table of what may be connected to what;
`strip.py` removes the markup.

`apply_repair` takes `resolution` as a required keyword with no default. That is not style: §9 case 2
has two non-equivalent answers and the toolchain is not entitled to either, so there must be no call
that resolves a generated-zone divergence while leaving the decision implicit. Never add a default,
an "auto" mode, or a convenience wrapper that picks one.

**There are two families of write, not one list** (Q31). Three verbs a *person* drives — `set_knob`,
`set_node_title`, `set_body` — and every one of them is **refused the generated zone**, because that
zone is assembly the graph owns. And `connect` (P21), which writes **only** into that zone and
nowhere else, which is what the zone is for. The two families do not overlap at any address, which is
what the original "three and no more" was actually protecting: not a count, but a person not editing
what the graph maintains. `connect` is addressed by **two** nodes, because a connection is a relation
— and **it draws no arrow**: an edge appears afterwards because a type now crosses a boundary or
because a run drew a flow (Q9), and a write that stands while no arrow appears is information rather
than a bug. What may be connected to what lives in `compose.py` and nowhere else; a composition it
does not describe is a refusal **naming both kinds**, never a guess at a call signature, because a
wrong write into a generated zone is a broken project and a refusal is a sentence with the agent
behind it. Inference is not on the table: a RAG stage into a pipeline needs a value threaded through
an assembly, so it is refused (Q32).

**An insert is not one of either family** (P20): those three edit code that is already there, through a syntax node, and an insert
writes whole files that were not there at all — which is why it cannot go through `libcst`, refuses a
collision instead of merging, and is judged afterwards by the gate rather than validated against a
knob's declaration. The third (Q15) is
what makes the node's code panel an editor rather than a viewer, and it loosens nothing — a generated
zone is refused, a locked signature is refused against `parser.signature_of` (module level so the lock
and the parser cannot drift), decorators are refused outright because a body edit that could move one
could reclassify its own zone, and the address is **node plus function** because I-6 says code is
edited through a node.

Every write addresses a **syntax node**, never a line or a span of text — that is what the markup
being real Python buys. A write validates against the knob's own declaration first, is undone if the
gate comes back worse than before, and updates the snapshot when it passes.

**Outside Python, ask rather than read** ([architecture §5.8](docs/architecture.md)). The parser
learns no library and no file format, ever. A compose file is asked of `docker compose config`, a
service of the port it publishes, a LangGraph flow of the compiled graph, a database of a connection.
Never add a YAML reader, a Dockerfile reader or a migration reader to this codebase: a parser for
someone else's format is a second opinion about a thing that already has a first one, and it is wrong
in ways that look right.

**Nothing is pushed over the wire** (P13). The protocol is one request and one answer with `id`
echoed; logs are polled with an offset the caller keeps, and `run.start` returns as soon as the
application answers. Adding a second message shape is a protocol version decision, available later
and additive — do not reach for it as a convenience. A process the core starts is recorded in
`.framestack/run.json` so `stop` works across a crash, and a session is the **sidecar's** lifetime, not
any process exit: the CLI's `run` deliberately leaves the application running.

**Nothing starts a service implicitly** (P11). Observing never brings a container up, never creates
a virtual environment and never installs anything — `env.up` / `env.down` exist so that nothing else
has to, and they run only because a person pressed the button on the compose file's node. Because
nothing is ever started implicitly there is nothing to leak; keep it that way, and note that the test
guarding it watches the docker commands, not the call sites. The compose file is never parsed by us —
`docker compose config` is asked what it says.

**A failing test in an environment the project asked for and did not get is `unproven`, not red**, and
a test that passed still counts. `Environment.incomplete` is the one place that judgement is made.

**The project's own tests are the run the graph observes** (Q7). `probe.py` runs the suite with the
carriers instrumented by code object — tracing, never wrapping, since FastAPI holds its own reference
to each endpoint — and a node is proven by a test that entered it and passed. Test evidence outranks a
direct call wherever both exist, and that rule lives in `probe.run_plan` and nowhere else. Never
count import-time execution as "exercised", and never let a suite that fails to collect redden the
nodes: a broken test suite is not a broken application.

**`probe.py` is handed to the project's own interpreter as a plain file**, which works only because
it imports nothing from this package — a project's virtual environment has never heard of
`framestack_core`. Never add an import from the toolchain to it, and never resolve it by importing it
here; `observe.probe_script()` finds it by path, and the frozen build ships it as data.

**`probe.py` is the only module that imports the user's project, and the toolchain never imports it**
— `observe.py` spawns it as a subprocess with a timeout. Keep it that way: everything else reads
statically so that drawing a graph never runs a stranger's code, and a project that hangs or crashes
must cost a subprocess rather than the core the UI is talking to. The parser and the
strip must never disagree about markup or file discovery — that is why both import the shared pair
rather than keeping their own copy.
| `bp` | `packages/bp/` | The inert markup primitives (`@node`, `@editable`, `@generated`, `group_node`, `Param`). Ships into generated user projects. |

Hierarchy is declared, never inferred: both `@node` and `group_node` take `members`, and a node has
at most one parent. The edges the parser draws are a different relation — a type crossing a boundary
— and a node referenced by two carriers still has one parent.

**The Rust shell exposes exactly one IPC command, `core_request`.** A new capability is a new
*method in the Python core* (registered in `HANDLERS` in [handlers.py](packages/core/src/framestack_core/handlers.py)),
never a new Tauri command. Anything in Rust that inspects a method name or interprets a result is
misplaced logic.

**The wire is NDJSON over the sidecar's stdio** — one JSON object per line, shape defined in
[protocol.py](packages/core/src/framestack_core/protocol.py). `id` is opaque to the core and echoed
verbatim. **stdout carries the wire and nothing else**; every log line goes to stderr, or the stream
is corrupted (there is a test asserting this). A handler that raises is turned into an error
response, never a crash.

`framestack_core` may import `bp`; **`bp` must never import `framestack_core`**, and `bp` must have zero
third-party dependencies — enforced by a test that AST-walks the package for non-stdlib imports.

### The invariants everything follows from

Full statements in [docs/architecture.md](docs/architecture.md) §2; the ones that constrain day-to-day
work:

- **Stay close to Unreal Engine Blueprints.** This is the tie-breaker for design questions, and it
  is what settled all five v0 open questions (see the settled log in open-questions.md): explicit
  marks over inference, a registry over free strings, one uniform shape at the top level, controls
  derived from types, defaults shown as defaults.
- **I-1 Code is the only source of truth.** No manifest, no graph file. Anything that starts to look
  like a second store of state is a design error. The snapshot is a diff reference, never a source
  the graph reads from.
- **I-2 The markup layer is inert.** `@node`, `@editable`, `group_node` return their carrier — *the
  same object*, not a wrapper (`test_inert.py` asserts identity, not equivalence). `Param` is
  metadata inside `Annotated`. Putting behavior into `bp` breaks the only thing separating this from
  Flowise/Langflow. Its mechanical form is `framestack-core strip`
  ([strip.py](packages/core/src/framestack_core/strip.py)), and the test that runs the example and its
  stripped copy in separate processes and demands identical answers.
- **I-3 Every visible node has a carrier object** — class, function, or module. Every top-level node
  is a `group_node`, even a one-member one; every function inside a carrier is explicitly `@editable`
  or `@generated`, never classified by absence.
- **I-4 Markup is real Python syntax.** Decorators and `Annotated`, never comments — the AST must see it.
- **I-5 A green node parses AND passes its observable checks.** `verdict_for` in
  [verdict.py](packages/core/src/framestack_core/verdict.py) is that one implementation. Never add a
  second path to a green verdict, never let an absent observation read as a passing one, and never
  report green from the static gate alone — that is the agent fitting to the parser, and it is the
  invariant most likely to be eroded by a convenience. A check that could not run reports `skipped`
  and leaves the node `unproven`; never turn "could not check" into "fine". And never synthesize
  input to manufacture a pass — evidence comes from a real run with real input, or it is not
  evidence.
- **I-6 Code is edited only through a node.** Everything else is detected, not prevented — by
  reconciliation against the snapshot, never by a file watcher. The snapshot is a diff reference and
  nothing may read a fact out of it to draw or decide with; it holds no editable bodies, so an edit
  inside one raises nothing.

### Reading order for docs

[docs/](docs/) is the source of truth for what gets built. **It is gitignored — local only, never
committed.** Anything the toolchain has to read at runtime therefore does not belong there; the
agent's system prompt used to and was moved into the package for exactly that reason. Nothing in
`docs/` may become a test input or a build input.

- [architecture.md](docs/architecture.md) — the v0 spec. Sections 2 (invariants) and 7 (the parser as
  a gate) carry everything load-bearing.
- [roadmap.md](docs/roadmap.md) — **P22 only**, plus a roll-call of what is done. P0–P21 are
  finished and their detailed record was cleared from the file deliberately, so what is left is the
  work in front of us; the reasoning behind the decisions those phases settled is in
  open-questions.md, which is where it belonged anyway. It opens with the direction the remaining
  phases serve (Q25), and P22 — the prompt composed from the registry — is the last of them.
- [design.md](docs/design.md) — the plan for the UI: what the design has to answer, which method sits
  behind each surface, and what it may not invent. Written before the design, so the design can be
  judged against it. **Its layout sections (§3, §5, §6, §8) were superseded by P18** and describe a
  workspace that no longer exists; its rules about colour, marks, wire geometry and controls derived
  from types stand (Q26).
- [open-questions.md](docs/open-questions.md) — nothing open; Q1–Q28 are settled, with the reasoning
  kept in the log.
  **Read before starting any phase**, and add an entry the moment two documents disagree — an
  unrecorded conflict is worse than an open one.
- [prompts/system-prompt-claude-code.md](packages/core/src/framestack_core/prompts/system-prompt-claude-code.md)
  — in the package, not in `docs/`. The prompt for the agent that generates user code. It **fixes the `bp` syntax** the toolchain parses; where it and the
  architecture doc disagree, the prompt wins and the disagreement is recorded in open-questions.

The product is **Framestack AI Builder**. The toolchain package is `framestack-core` /
`framestack_core` (the sidecar); the state directory it writes in a user's project is `.framestack/`;
the catalog variable is `FRAMESTACK_BLUEPRINTS`. **The `bp` name is fixed and must not change** — it
is the markup layer, and it is imported by every generated user file, so renaming it would rewrite
strangers' code.

A new node `kind` is a new entry in `kinds.REGISTRY` **and** a row in the system prompt's `kind`
table — a test holds the two together, because an agent told about a kind the checker cannot dispatch
on generates code nothing can prove (Q8).

If that kind's check **reads a library's internals**, the technology also needs an entry in
`kinds.TECHNOLOGIES` with the release the check was written against. A test asserts that number equals
what is installed, so upgrading the dependency is what updates it. It is a statement about our code,
never a claim that another version is broken: nothing warns about, gates, or refuses an upgrade, and
the note only ever appears attached to a result that is *not* a pass. A technology whose checks touch
no library gets no entry — RAG is the standing example.

A new diagnostic is a new entry in `diagnostics.CATALOGUE` with its rule and its repair text — never
an ad-hoc message at the call site, or repair prompts stop being writable from the diagnostic alone.
A new capability the UI can call is a new entry in `handlers.HANDLERS`, plus its schema in `api.py`.

## Conventions

Comments in this codebase explain *why a thing is the way it is* — which invariant it protects, what
breaks without it — rather than restating the code. Match that; a new module without that reasoning
reads as foreign here. UI/design is deliberately out of scope for v0; `assets/` holds references not
wired into the build, and — like `docs/` — is gitignored and local only.
