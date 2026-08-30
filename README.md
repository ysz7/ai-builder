<h1 align="center">Framestack AI Builder</h1>

<p align="center">
  <b>A visual builder for Python where the code is the source of truth.</b><br>
  Your project stays ordinary Python. The graph is a view of it — and a node is green
  only when a real run proved it works.
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#what-you-can-build">What you can build</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#status">Status</a>
</p>

<!-- A screenshot of the workspace belongs here. -->

---

## The difference, in one line

In every other visual builder, a node is green **because it exists**.

Here it is green because `test_retrieval.py` entered it and passed.

That is not a feature bolted on top — it is the reason the architecture is what it is. Proving a
node requires the code to be real, runnable and yours, which is exactly what flow-document builders
gave away when they made a JSON canvas the source of truth.

## Why this and not Langflow, Flowise, n8n

|  | Them | Framestack |
| --- | --- | --- |
| Source of truth | a flow document; code is an export | **your Python files** |
| Adding a node | writes an entry into the document | writes real, annotated code |
| Editing in the UI | edits the document | rewrites the syntax tree with `libcst`, byte-for-byte everywhere else |
| A green node means | it exists | **a test entered it and passed** |
| If you delete the builder | the app stops being buildable | the project runs, unchanged |
| Lock-in | the runtime interprets your flow | none — strip the annotations and it is plain Python |

The mental model is **Unreal Engine Blueprints for backend work**: a node is an editable surface over
real code, never a wrapper that changes how it behaves.

## How it works

1. **You describe what you want.** A coding agent writes ordinary, production-quality Python — the
   way the official docs would — and adds an inert annotation layer on top (`@node`, `@editable`,
   `@generated`, `group_node`, `Param`).
2. **A parser projects that into a graph.** Nodes come from real classes, functions and modules.
   Edges are types crossing a boundary, read from the signatures you already wrote.
3. **You tune it from the canvas.** Change a knob, rename a node, edit a body — every write goes
   through the concrete syntax tree, so everything the edit was not about comes out identical.
4. **You press Observe.** Your project's own test suite runs with the nodes instrumented. What a
   passing test entered turns green. What nothing reached stays grey — never green by default, and
   never green because a parser was satisfied.

The annotation layer is **inert**: no-op decorators and `Annotated` metadata. Strip it and the
application behaves identically — there is a test that runs both copies in separate processes and
demands the same answers.

## What you can build

The builder can prove **27 kinds of node** across seven families. That list is the honest boundary of
what it can make a claim about — anything outside it is still ordinary Python you can write, it just
gets no verdict.

| Family | Nodes |
| --- | --- |
| **FastAPI** | service, router, route, dependency, settings |
| **LangGraph** | agent, state, node, router, tool, settings |
| **RAG** | pipeline, chunking, embedding, retrieval, generation |
| **MCP** | the server you expose, its tools, the servers you consume |
| **Background work** | queue app, tasks, schedule, workers |
| **Persistence** | database session, vector store |
| **Infrastructure** | `Dockerfile`, `compose.yaml` — carried by the file itself |

And you can *use* what you built without leaving the window: talk to an agent from its own node, hand
a pipeline its documents, call a route, inspect an MCP server, run the project's own npm commands,
open a real terminal.

Working annotated projects to read: [fastapi-service](examples/fastapi-service/),
[langgraph-agent](examples/langgraph-agent/), [rag-pipeline](examples/rag-pipeline/),
[mcp-agent](examples/mcp-agent/) — each with its own test suite, because that suite is the evidence
its graph is judged by.

## Quickstart

You need **Node 20+**, **Python 3.10+** with [uv](https://docs.astral.sh/uv/), and a
[Rust toolchain](https://rustup.rs) — Tauri will not build without it.

```bash
git clone <this repo> && cd framestack-ai-builder
uv sync          # Python workspace
npm install      # front-end and Tauri CLI
npm run dev      # the app
```

Then open one of the `examples/` projects and press **Observe**.

### Or try it without the app

The whole core is a CLI. Read the graph out of a project, run its checks, or prove the annotations
are inert by stripping them:

```bash
uv run python -m framestack_core graph examples/fastapi-service
uv run python -m framestack_core check examples/fastapi-service --observe
uv run python -m framestack_core strip examples/fastapi-service /tmp/stripped
```

## Status

**Working today:** the parser, the gates, the writer, repair, the observable checks and the evidence
they produce, the agent integration, the environment and its services, running and stopping things,
background work, MCP, the rebuilt workspace, the blueprint library and inserting from it, and using
what you built — talking to an agent or a pipeline, handing it documents, running the project's own
commands. Seven reference projects, 578 tests, one gate (`npm run check`) that CI runs and nothing
else.

**Next:** composing the agent's system prompt per project, so a stack you are not using costs you
no tokens.

**Honest caveats:** this is version 0.1.0. What can be *proven* is what the kind registry knows —
FastAPI, LangGraph, RAG, MCP, queues, Docker, databases and vector stores — and a kind outside it
has no observable check, so a node of it stays unproven. The agent half needs Claude Code installed
and signed in. Building the desktop app needs a Rust toolchain, and `.app`/`.dmg` can only be built
on macOS.

## Contributing

Development setup, the architecture rules, the protocol and the release process are in
[DEVELOPMENT.md](DEVELOPMENT.md). The short version of the rules that matter:

- **Code is the only source of truth.** No manifest, no graph file.
- **The annotation layer is inert.** Behaviour never depends on it.
- **Every node has a carrier** — a class, a function, a module, or a file.
- **Green is earned by a run**, and a check that could not run reports *skipped*, never *fine*.

## License

MIT — see [LICENSE](LICENSE).
