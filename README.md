# Awesome AI Builder

A visual builder for Python applications where **the code is the source of truth** and the graph is a
two-way projection of it.

A chat agent writes ordinary Python under fixed rules, adding an inert, AST-addressable annotation
layer. A parser reads that layer and projects a node graph; edits made in a node are written back into
the code through the syntax tree. The application that comes out runs locally and deploys anywhere as
a plain Python project — with no runtime dependency on the builder.

The mental model is Unreal Engine Blueprints, moved into backend development: a node is an editable
surface over real code, not a wrapper that changes how it behaves.

## Why it is not Flowise / Langflow / LangGraph Studio

Those generate the graph as the source of truth and export code as an artifact. Here the direction is
reversed: code first, graph derived. The annotation layer is inert — no-op decorators and `Annotated`
metadata — so an assembled application never needs the builder at runtime. That property is the whole
differentiator, and it is enforced mechanically in CI, not by convention.

## Documents

- [packages/core/src/aibuilder_core/prompts/system-prompt-claude-code.md](packages/core/src/aibuilder_core/prompts/system-prompt-claude-code.md)
  — the system prompt for the coding agent working inside the builder; it fixes the `bp` markup syntax
  the toolchain parses. It sits with the code because the core reads it at runtime and tests assert
  against it: it is an input, not a description.
- `docs/` — the v0 specification, the phase roadmap and the log of settled questions. Kept out of the
  repository deliberately; ask for it if you are working on the design rather than on the code.

## Assets

`assets/` holds design references for later — a graph-canvas template and a website design whose
visual language may become the app's. Kept locally and out of the repository, like `docs/`: nothing
there is wired into the build, and the UI is out of scope for v0 and delivered separately.

## Stack

| Layer | What it is | Rule |
| --- | --- | --- |
| Shell | Tauri 2 (Rust) | Window, filesystem access, spawning the core, ferrying JSON. **No business logic.** |
| Front-end | React 19 + React Flow (`@xyflow/react`) | The graph canvas, inside the Tauri window. |
| Core | Python 3.10+ (`libcst`, `ast`) | Parser, writer, gates, orchestration. Runs as a Tauri sidecar process. |
| `bp` | Standalone Python package | The four inert markup primitives. Installs into the projects the builder generates. |

The Rust shell is three files and one IPC command (`core_request`). A new capability is a new
*method in the Python core*, never a new command in Rust.

## Layout

```
apps/desktop/          Tauri app
  src/                 React front-end (graph canvas, core client)
  src-tauri/           thin Rust shell + sidecar bridge
packages/bp/           inert markup primitives (ships to user projects)
packages/core/         Python core, runs as the sidecar
scripts/               sidecar dev shim and PyInstaller build
docs/                  specification and roadmap — local only, not committed
assets/                design references — local only, not committed
```

## Requirements

| | Needed for | Status on a fresh machine |
| --- | --- | --- |
| Node 20+ / npm | front-end, Tauri CLI | |
| Python 3.10+ and [uv](https://docs.astral.sh/uv/) | the core, the workspace | |
| Rust toolchain ([rustup](https://rustup.rs)) | **required — Tauri will not build without it** | usually absent, install first |
| Xcode Command Line Tools | linking on macOS | `xcode-select --install` |

## Commands

```bash
uv sync                 # Python workspace (bp + core + dev tools)
npm install             # front-end and Tauri CLI

npm run dev             # full app: Vite + Tauri window + Python sidecar
npm run web:dev         # front-end alone in a browser (no core, ping will fail)
npm run test:py         # bp inertness + core protocol + strip tests
npm run check           # the full suite: lint, types, tests (what CI runs)
npm run build           # freeze the sidecar, then bundle .app and .dmg
```

`npm run dev` starts the sidecar from source through a shim at
`apps/desktop/src-tauri/binaries/aibuilder-core-<target-triple>` — no PyInstaller step in the loop, so
the core stays editable. `npm run build` runs `scripts/build-sidecar.sh` first, which freezes the core
and overwrites that shim with the real binary; `git checkout -- apps/desktop/src-tauri/binaries`
brings the shim back.

To talk to the core by hand, without the app:

```bash
echo '{"id":1,"method":"ping"}' | uv run python -m aibuilder_core
```

To see the graph the parser reads out of a project, or to prove the markup is inert by stripping it
and running what comes out:

```bash
uv run python -m aibuilder_core graph examples/fastapi-service
uv run python -m aibuilder_core check examples/fastapi-service --observe
uv run python -m aibuilder_core snapshot examples/fastapi-service   # record the reference
uv run python -m aibuilder_core status examples/fastapi-service     # what diverged since
uv run python -m aibuilder_core set-knob examples/fastapi-service api.settings page_size 50
uv run python -m aibuilder_core repairs examples/fastapi-service   # divergences and their options
uv run python -m aibuilder_core strip examples/fastapi-service /tmp/stripped
```

To see what the code-generation agent is handed — the system prompt, the request, and the project as
it stands — for a chat request or for a blueprint out of the sibling MIT catalog:

```bash
uv run python -m aibuilder_core blueprints                          # what input B can be given
uv run python -m aibuilder_core brief examples/fastapi-service --request "add a users router"
uv run python -m aibuilder_core brief examples/fastapi-service --blueprint fastapi-routing
uv run python -m aibuilder_core failures examples/fastapi-service   # what the agent gets wrong
```

## Building for macOS — read before planning a release

- **`.app` and `.dmg` can only be built on a macOS machine.** Cross-compiling to Mac from Linux or
  Windows does not work: the Apple SDK and the signing chain are not available off-platform. Without a
  Mac, the only route is CI with a macOS runner (GitHub Actions `macos-14` or later).
- **Distribution requires Apple signing and notarization** — an Apple Developer account ($99/yr), a
  Developer ID Application certificate, and a notarization pass. Unsigned builds are refused by
  Gatekeeper on other people's machines; they run only locally, and only after a right-click → Open.
- Space is reserved for this in `apps/desktop/src-tauri/tauri.conf.json` under `bundle.macOS`
  (`signingIdentity`, `entitlements`, both `null` for now). Tauri reads the rest from the environment
  at build time: `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`. None are needed for local development.
- The frozen Python sidecar is signed as part of the bundle, so it needs no separate treatment — but
  it does mean an ad-hoc-signed sidecar cannot be swapped into a signed `.app` after the fact.

## Status

P0 through P9 are done: the window opens, React Flow renders a canvas, the Rust shell reaches the Python
core over NDJSON, the markup layer exists and is provably inert, and
[examples/fastapi-service/](examples/fastapi-service/) is the annotated reference project the rest is
tested against. `npm run check` is the gate.

The parser reads that project into a graph IR — nodes with their carriers, editable and generated
zones, knobs with their metadata, group membership, and contract edges taken from real signatures.

The static gate turns that graph into addressed diagnostics — what, where, which rule, and what a
repair must do — and hands both to the UI over a versioned graph API. The observable checks then run
the project in a subprocess to prove each node actually works: a node is green only when it both
parses and answers, and a check that could not run leaves the node unproven rather than fine.

Reconciliation then answers the `git status` question — not "did something change", which a file
watcher would drown in formatters and branch switches, but "is it still valid": what no longer
matches the last state that passed the gates, addressed, and classified by whose fault it is.

Edits made in a node are written back through the syntax tree: a knob addresses its literal default,
a rename addresses the keyword on the carrier's own declaration, and everything the edit was not
about comes out of the file byte for byte as it went in.

When something diverges, the repair system says what can be done about it. A broken contract is
restored from the reference without discarding the body the user wrote. A hand edit in generated code
is not resolved at all until someone chooses between reverting and accepting it — the tool offers
both and waits, because one that always reverts would eventually delete work someone needed, and one
that always accepts would eventually bless a breakage inside a green node.

Code generation enters through the same gates as everything else. The agent gets one brief, assembled
the same way whether the request is a sentence or a blueprint from the sibling MIT catalog: the system
prompt verbatim, the request, and the project as it stands. The prompt is the same text in both cases
— the annotation rules live there and never in a blueprint, which is why a blueprint stays plain
documentation that works in bare Claude Code. What the agent then gets wrong is written down rather
than refused: the soft gate flags it, and the log of those flags is the list the next phase works
from.

The slice closes the loop on a real service: a brief, the graph, a knob written back through the
syntax tree, a deliberate hand edit in generated code, reconciliation that names it, a repair the
caller chooses, and green again — where green means proven by a run, not accepted by the parser. The
evidence comes from the project's own test suite, with the carriers instrumented so each node reports
whether a test actually entered it; the direct calls prove whatever no test reached. On the reference
service every node is proven, including the POST route no tool may prove by inventing a request body.
The stripped copy is then put through the same checks and answers identically.

Next is P10 — LangGraph and RAG, each a repeat of that loop against a new topology, in the order set
out in the roadmap.

Python only; the first supported technology is FastAPI.
