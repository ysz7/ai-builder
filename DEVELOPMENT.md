# Development

Everything the [README](README.md) leaves out: how the pieces fit, how to run them, and what a change
is allowed to do.

## The four layers, and the boundaries between them

| Layer | What it is | Rule |
| --- | --- | --- |
| Shell | Tauri 2 (Rust) | Window, filesystem access, spawning the core, ferrying JSON. **No business logic.** |
| Front-end | React 19 + React Flow (`@xyflow/react`) | Renders the graph the core returns. Never a second source of truth. |
| Core | Python 3.10+ (`libcst`, `ast`) | Parser, gates, writer, repair, orchestration. Runs as a Tauri sidecar. |
| `bp` | Standalone Python package | The five inert markup primitives. Ships into generated user projects. |

**The Rust shell exposes exactly one IPC command, `core_request`.** A new capability is a new *method
in the Python core*, never a new Tauri command. Anything in Rust that inspects a method name or
interprets a result is misplaced logic.

**The wire is NDJSON over the sidecar's stdio** — one JSON object per line, `id` echoed verbatim.
stdout carries the wire and nothing else; every log line goes to stderr, or the stream is corrupted.
There is a test asserting this.

**Nothing is pushed.** One request, one answer. Logs are polled with an offset the caller keeps.
**Nothing starts implicitly** — no service is brought up, no environment created, no dependency
installed, except because somebody pressed a button.

`framestack_core` may import `bp`; **`bp` must never import `framestack_core`**, and `bp` must have
zero third-party dependencies — enforced by a test that AST-walks the package for non-stdlib imports.

## Repository layout

```
apps/desktop/          Tauri app
  src/                 React front-end (graph canvas, core client)
  src-tauri/           thin Rust shell + sidecar bridge
packages/bp/           inert markup primitives (ships to user projects)
packages/core/         Python core, runs as the sidecar
scripts/               sidecar dev shim, PyInstaller build, the check gate
examples/              annotated reference projects, each with its own tests
docs/                  specification, roadmap, settled questions — local only, not committed
assets/                design references — local only, not committed
```

`docs/` and `assets/` are gitignored deliberately. Nothing the toolchain reads at runtime may live
there — which is why the agent's system prompt sits in the package, at
[packages/core/src/framestack_core/prompts/system-prompt-claude-code.md](packages/core/src/framestack_core/prompts/system-prompt-claude-code.md).
The core reads it at runtime and tests assert against it: it is an input, not documentation.

## Requirements

| | Needed for | Note |
| --- | --- | --- |
| Node 20+ / npm | front-end, Tauri CLI | |
| Python 3.10+ and [uv](https://docs.astral.sh/uv/) | the core, the workspace | |
| Rust toolchain ([rustup](https://rustup.rs)) | **required — Tauri will not build without it** | usually absent on a fresh machine |
| Xcode Command Line Tools | linking on macOS | `xcode-select --install` |

## Commands

```bash
uv sync                 # Python workspace (bp + core + dev tools)
npm install             # front-end and Tauri CLI

npm run dev             # full app: Vite + Tauri window + Python sidecar
npm run web:dev         # front-end alone in a browser (no core, ping will fail)
npm run test:py         # all Python tests
npm run check           # scripts/check.sh: ruff lint + format, mypy --strict, pytest
npm run build           # freeze the sidecar, then bundle .app and .dmg
```

`scripts/check.sh` is the gate a change must pass; CI runs that script and nothing else, plus a check
that the built `bp` wheel has no `Requires-Dist`.

Single test or subset: `uv run pytest packages/core/tests/test_ping.py -q`, or
`uv run pytest -k inert -q`. Front-end typecheck: `npm run web:build`.

### The sidecar shim

`apps/desktop/src-tauri/binaries/framestack-core-<target-triple>` is a **tracked shell shim** that
execs `scripts/dev-sidecar.sh`, so `npm run dev` runs the core from source with no PyInstaller step.
`npm run build` overwrites that file with the frozen binary;
`git checkout -- apps/desktop/src-tauri/binaries` restores the shim. **Do not commit the frozen
binary.**

## Talking to the core by hand

```bash
echo '{"id":1,"method":"ping"}' | uv run python -m framestack_core
```

Read a project, judge it, observe it, and record what a valid state looked like:

```bash
uv run python -m framestack_core graph examples/fastapi-service
uv run python -m framestack_core check examples/fastapi-service
uv run python -m framestack_core check examples/fastapi-service --observe   # runs the project
uv run python -m framestack_core snapshot examples/fastapi-service
uv run python -m framestack_core status examples/fastapi-service
uv run python -m framestack_core strip examples/fastapi-service /tmp/stripped
```

Write back through the syntax tree, and act on what diverged:

```bash
uv run python -m framestack_core set-knob examples/fastapi-service api.settings page_size 50
uv run python -m framestack_core set-body examples/fastapi-service health app.api.health.health -
uv run python -m framestack_core repairs examples/fastapi-service
```

What the code-generation agent is handed — the system prompt verbatim, the request, and the project
as it stands. A blueprint catalog is **never discovered**: pass it in or set `FRAMESTACK_BLUEPRINTS`.

```bash
uv run python -m framestack_core blueprints --catalog <path>
uv run python -m framestack_core brief examples/fastapi-service --request "add a users router"
uv run python -m framestack_core brief examples/fastapi-service --blueprint <id> --catalog <path>
uv run python -m framestack_core failures examples/fastapi-service
```

The environment a project runs in, read on demand and changed only when asked:

```bash
uv run python -m framestack_core env examples/service-with-db
uv run python -m framestack_core env-up examples/service-with-db
uv run python -m framestack_core env-down examples/service-with-db
```

Running the application, and background work as its own subsystem:

```bash
uv run python -m framestack_core run examples/fastapi-service        # starts, says which port
uv run python -m framestack_core call examples/fastapi-service /users
uv run python -m framestack_core logs examples/fastapi-service
uv run python -m framestack_core stop examples/fastapi-service

uv run python -m framestack_core work examples/service-with-worker
uv run python -m framestack_core work-status examples/service-with-worker
uv run python -m framestack_core work-logs examples/service-with-worker
uv run python -m framestack_core work-stop examples/service-with-worker
```

Using what was built — MCP, indexing, the project's own commands:

```bash
uv run python -m framestack_core inspect examples/mcp-agent agent.notes
uv run python -m framestack_core tool examples/mcp-agent agent.notes summarize '{"text": "One."}'
uv run python -m framestack_core index examples/rag-pipeline rag
uv run python -m framestack_core commands .
uv run python -m framestack_core command . web:dev
uv run python -m framestack_core command-logs .
uv run python -m framestack_core command-stop .
```

## Rules a change has to respect

- **A new node `kind`** is a new entry in `kinds.REGISTRY` **and** a row in the system prompt's `kind`
  table. A test holds the two together: an agent told about a kind the checker cannot dispatch on
  generates code nothing can prove.
- **A new diagnostic** is a new entry in `diagnostics.CATALOGUE` with its rule and its repair text —
  never an ad-hoc message at the call site.
- **A new capability the UI can call** is a new entry in `handlers.HANDLERS`, plus its schema in
  `api.py`.
- **Outside Python, ask rather than read.** A compose file is asked of `docker compose config`, a
  LangGraph flow of the compiled graph, a service of the port it publishes. Never add a YAML,
  Dockerfile or migration parser: a parser for somebody else's format is a second opinion about a
  thing that already has a first one, and it is wrong in ways that look right.
- **`probe.py` is the only module that imports the user's project**, and the toolchain never imports
  it — `observe.py` spawns it as a subprocess with a timeout. It imports nothing from this package,
  because a project's virtual environment has never heard of `framestack_core`.
- **Comments explain why a thing is the way it is** — which invariant it protects, what breaks
  without it — rather than restating the code.

## Building for macOS — read before planning a release

- **`.app` and `.dmg` can only be built on macOS.** Cross-compiling from Linux or Windows does not
  work: the Apple SDK and the signing chain are not available off-platform. Without a Mac, the only
  route is CI with a macOS runner (GitHub Actions `macos-14` or later).
- **Distribution requires Apple signing and notarization** — an Apple Developer account ($99/yr), a
  Developer ID Application certificate, and a notarization pass. Unsigned builds are refused by
  Gatekeeper on other people's machines.
- Space is reserved in `apps/desktop/src-tauri/tauri.conf.json` under `bundle.macOS`
  (`signingIdentity`, `entitlements`, both `null` for now). Tauri reads the rest from the environment
  at build time: `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`. None are needed for local development.
- The frozen Python sidecar is signed as part of the bundle, so it needs no separate treatment — but
  an ad-hoc-signed sidecar cannot be swapped into a signed `.app` after the fact.
