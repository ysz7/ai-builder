/**
 * The shapes the core returns, transcribed from the schemas it declares.
 *
 * Written out rather than inferred, for the reason `api.py` writes them out: a contract
 * is a decision. These are the *client's* copy of it, and the payload announces its
 * `api_version` so a mismatch can be seen rather than guessed at.
 *
 * Nothing here is a model of the graph. The rebuild deleted the graph payload along with
 * the annotation layer it described; what comes back in Phase 1 is derived from the
 * convention -- a directory that exports what its kind requires -- and its types land here
 * beside the layout when the core can answer for them.
 */

/**
 * Where a person put a node, and how they are looking at it.
 *
 * The core stores this and refuses to understand it (Q13). Whether a card is unfolded and
 * whether a system with children is expanded are the same kind of fact as a coordinate:
 * something a person arranged, which changes nothing about the project.
 */
export type Placement = {
  x?: number;
  y?: number;
  /** A system with children, showing them or showing a count. View state, never a write. */
  expanded?: boolean;
};

export type Layout = Record<string, Placement>;

export type LayoutRead = { api_version: number; layout: Layout };

/** `layout.write`, `project.create`: a refusal is a result, as everywhere else. */
export type WriteResult = { api_version: number; ok: boolean; detail: string };

/**
 * One node of the graph, exactly as the parser reports it.
 *
 * There is **no verdict field here, and its absence is the contract**. Colour is earned by
 * a run (I-3), Phase 1 runs nothing, and a client that invented a default would be deciding
 * for the core what an unobserved project looks like. Observe adds the field in Phase 2.
 */
export type GraphNode = {
  /** `agent`, `agent.researcher`, `.env`. A path, never a position. */
  id: string;
  /** The directory's or file's own name. What the card is titled. */
  name: string;
  /**
   * One of the four kinds, `"file"`, or `"mcp"`. Never a framework.
   *
   * `file` and `mcp` are **not kinds**: they have no required export and nothing that could
   * prove them. To ask whether a node is a package, ask `isSystem(kind)` — never `kind !==
   * "file"`, which meant the right thing only while `file` was the sole exception.
   */
  kind: string;
  /** Project-relative, POSIX separators. */
  path: string;
  complete: boolean;
  /** What this kind requires. Sent even when satisfied: the panel says what the contract is. */
  exports: string[];
  /** The required exports the package does not bind. Empty when it is complete. */
  missing: string[];
  /** Why it is incomplete, in a sentence. `""` when it is not. */
  reason: string;
  parent: string;
  children: string[];
  files: string[];
  /**
   * The entry points an edge may land on, in the order the package states them.
   *
   * `index` and `search` for a rag, one per `HANDLERS` key for a worker, `run` for an
   * agent, none for an api — its export is an ASGI application, served rather than called,
   * and its routes belong in the panel. **What the package binds, never what its kind
   * requires:** a missing export is reported in `missing`, and a port for a name nothing
   * binds would be an attachment point for an import that cannot be written.
   */
  ports: string[];
};

/**
 * A relation the project already states.
 *
 * `import` because one system package imports from another, `mcp` because `mcp.json`
 * configures a server. Nothing in the UI creates one — connecting two nodes means writing
 * an import, which is a code edit made through the chat.
 */
export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  /** `"import"` or `"mcp"`. */
  kind: string;
  /** An MCP server's name. `""` on an import edge. The node it lands on carries it too. */
  label: string;
  /**
   * Which of the target's ports this lands on, or `""` for the package itself.
   *
   * `api → rag` says nothing. `worker → rag.index` and `agent → rag.search` say that
   * uploads index and questions retrieve. Read from the import — `from rag import search`
   * — and never from anything a person drew.
   */
  port: string;
};

/**
 * One request a service answers, and where it goes next.
 *
 * **A route is not a node.** Forty routes on a canvas would be forty boxes; they are contents
 * of the api node, read when its panel opens and held nowhere else.
 */
export type Route = {
  /** `GET`, `POST`, … `WEBSOCKET`. The decorator's own verb and nothing else. */
  method: string;
  /** The path literal exactly as written, placeholders included: `/documents/{id}`. */
  path: string;
  handler: string;
  /** Project-relative. Five route modules need to say which one this row is from. */
  file: string;
  /** Node ids, or `postgres` where the handler's calls go through `repositories/`. */
  targets: string[];
  /**
   * The handler called something and none of it resolved. Drawn as `?`.
   *
   * **Empty targets with this false is a different claim**: the handler calls nothing, so it
   * has no downstream rather than an unknown one. Merging the two would manufacture doubt
   * about a function that plainly does none.
   */
  unsure: boolean;
};

/** `routes.read`: what one service serves. A refusal is a result, as everywhere else. */
export type RoutesResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  node: string;
  routes: Route[];
};

/**
 * `status.read`: whether one dependency can be reached, and when it was asked.
 *
 * **A status is not a verdict, and they never share a colour scale.** A verdict comes from a
 * test and belongs to code you own; this comes from a connection and belongs to something
 * outside the project. `reachable` is not `green`: reached is not proven.
 *
 * Five states and each is a different claim. `unknown` is not `unreachable` — "never checked,
 * or not checkable from here" is a different sentence from "it refused" — and `configured` /
 * `unconfigured` belong to the nodes where a check would cost money and so is never made.
 */
export type StatusResult = {
  api_version: number;
  ok: boolean;
  node: string;
  /** `reachable`, `unreachable`, `unknown`, `configured`, `unconfigured`. */
  status: string;
  /** Why. A colour nobody can act on is decoration, so a refusal carries its reason. */
  detail: string;
  at: string;
};

/** One model this machine has pulled. Bytes, as the daemon reports them. */
export type Model = { name: string; size: number };

/**
 * `ollama.*`: what is on this machine, and how a pull is going.
 *
 * One shape for all four verbs, as `shell.*` has. **The list is not a catalogue** — it is
 * whatever this machine has pulled, asked at the moment somebody looks. A registry of model
 * names shipped with the toolchain would be stale the week after it shipped.
 *
 * A pull takes minutes, so its output is polled with an offset the caller keeps. Nothing is
 * pushed, and the log is on disk — which is why a panel opened mid-pull can still watch one.
 */
export type OllamaResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  models: Model[];
  /** Which model is being fetched, or `""`. */
  pulling: string;
  running: boolean;
  output: string;
  offset: number;
};

/** One table the project declares, and the file that declares it. */
export type Table = {
  name: string;
  /** Project-relative. "Who touches it", which is where it is written down. */
  file: string;
  /** A vector column. What makes the backend `postgres + pgvector`. */
  vector: boolean;
};

/**
 * `database.read`: what the project's storage is, never whether it is running.
 *
 * **Beside the graph, as the verdict set is.** The graph holds the node — one per backend,
 * never one per table — and this holds the reading of it. There is no status field, and the
 * absence is the contract: a status comes from a connection check, and that arrives with the
 * thing that can make one.
 */
export type DatabaseResult = {
  api_version: number;
  present: boolean;
  /** A literal out of the project's own settings. Never an environment, never a connection. */
  target: string;
  vector: boolean;
  /** `postgres`, or `postgres + pgvector` where a model declares a vector column. */
  label: string;
  tables: Table[];
};

/** `graph.read`: the project as it is on disk. A refusal is a result, as everywhere else. */
export type Graph = {
  api_version: number;
  ok: boolean;
  detail: string;
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

/**
 * What was proven about one node, and by what.
 *
 * `verdict` is one of `green`, `red`, `amber`, `grey`, `skipped`, and each is a different
 * claim. **`grey` and `skipped` are not the same**: the first says no test reached this code,
 * the second says the run did not happen. Collapsing them would let a broken environment read
 * as untested code, which is how a person ends up fixing the wrong thing.
 */
export type Verdict = {
  node: string;
  verdict: string;
  /** Why, in a sentence. Empty on green: there is nothing on the other side of it. */
  reason: string;
  /** The tests that executed this node's own code, as pytest names them. The evidence itself. */
  tests: string[];
};

/**
 * One run, kept whole.
 *
 * The commit is what makes it a claim about a state of the code rather than a floating fact:
 * a verdict set nobody can tell is stale is one that will be read as current.
 */
export type Observation = {
  at: string;
  commit: string;
  ok: boolean;
  detail: string;
  verdicts: Verdict[];
};

/** `observe.start`, `observe.read`, `observe.last` — one shape, as `shell.*` is. */
export type ObserveResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  running: boolean;
  output: string;
  offset: number;
  /** Null where this project has never been observed. Not the same as observed and found wanting. */
  observation: Observation | null;
};

/**
 * One knob, as a system's own `settings.py` declares it.
 *
 * `value` is the field's **own type** — a number, a boolean or a string — rather than text
 * the panel would have to parse back. `control` is what a caller branches on: `none` means
 * the field is shown and not editable, with `reason` saying why, because a knob nobody can
 * see is one nobody knows they have and a knob edited by guesswork deletes somebody's code.
 */
export type SettingField = {
  name: string;
  /** The annotation exactly as the author wrote it. Their words for the type, not ours. */
  annotation: string;
  /** `integer`, `number`, `toggle`, `text`, `select`, or `none`. */
  control: string;
  value: number | string | boolean | null;
  /** What a `Literal` allows. Empty for every other control. */
  choices: string[];
  /** Where it is written. What "open" points at. */
  line: number;
  /** Why there is no control, when there is none. */
  reason: string;
};

/**
 * `settings.read` and `settings.write` — one shape, because the write answers by re-reading
 * the file rather than by describing what it believes it did.
 *
 * `path` is `""` where the system has no `settings.py`, and that is `ok: true`: a system with
 * no knobs is the ordinary case, not a fault.
 */
export type SettingsResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  node: string;
  path: string;
  class_name: string;
  fields: SettingField[];
};

/**
 * `mcp.read` and `mcp.connect`: what `mcp.json` declares about one server.
 *
 * **`env` is names and never values.** An entry may hold a secret inline, and this payload
 * crosses into the webview — one console log away from somewhere permanent. The names are
 * what a person needs to see; the values stay in the file they are already in.
 *
 * **There is no `connected` field, and its absence is the contract.** Only the server knows
 * whether it is authorised, and finding out means speaking the protocol to it. What comes
 * back says what the application *did* — a command was run, in a terminal — never a claim
 * about the far side. A tick nobody verified is the same defect as a green node nobody ran
 * a test for.
 */
export type McpServer = {
  api_version: number;
  ok: boolean;
  detail: string;
  node: string;
  name: string;
  /** Exactly as the file gives them. `""` where the entry declares no command to run. */
  command: string;
  args: string[];
  env: string[];
  /** Which terminal `Connect` started it in. `""` from a read. */
  shell: string;
};

/** `editor.open`: which program was started, so the answer says what happened. */
export type Opened = {
  api_version: number;
  ok: boolean;
  detail: string;
  editor: string;
};

/**
 * What a message was dispatched as, or what has to be answered before anything can be.
 *
 * `asking` is the field that matters. A dispatcher that always dispatched would be one that
 * guessed, and a wrong command writes the wrong files into somebody's project — so when it
 * cannot tell which command a message is, or which stack a system should be written on, it
 * asks. The answer comes back as the `command` or `stack` argument of the next send.
 *
 * There is no shape here for "sent without a command", and its absence is the contract.
 */
export type Dispatch = {
  api_version: number;
  ok: boolean;
  detail: string;
  command: string;
  /** `"command"`, `"stack"`, or `""` when nothing needs answering. */
  asking: string;
  question: string;
  choices: string[];
  sent: boolean;
};

/** `chat.changes`: what the working tree looks like now, asked of `git`. */
export type Changes = {
  api_version: number;
  ok: boolean;
  detail: string;
  diff: string;
  files: string[];
};

/**
 * One thing a person can press to have written.
 *
 * Declared by the **core**, from the commands this build ships, so the palette cannot offer
 * something the prompts have never heard of. There is no code in here and no catalogue: a
 * block carries a command and what the person supplies before pressing it, and what gets
 * written is whatever the agent writes from that command's prompt.
 */
export type Block = {
  command: string;
  /** What is appended to it, where the command takes a fixed argument. `""` otherwise. */
  argument: string;
  /** The kind whose colour and glyph draws it. `""` where it becomes no node at all. */
  kind: string;
  label: string;
  hint: string;
  /** `""`, `"stack"` (one of `choices`), or `"name"` (free text — a list would be a gallery). */
  takes: string;
  choices: string[];
  /** Whether the convention allows only one at the root, and what must exist first. */
  once: boolean;
  requires: string;
};

/** `chat.choices`: the commands, the stacks each kind may be generated on, and the blocks. */
export type ChatChoices = {
  api_version: number;
  commands: string[];
  stacks: Record<string, string[]>;
  blocks: Block[];
};

/**
 * What one call returned, or the traceback it raised. **Never a verdict.**
 *
 * A run is a person typing a query and pressing a button; a colour is earned by a passing
 * test that executed the code (I-3). There is no `verdict` field here and there must never
 * be one — a node that went green because somebody used it is the flow-document defect
 * arriving through a side door.
 *
 * `value` is `unknown` because the shape is genuinely the user's: it is whatever their
 * `search` returns, and a type for it here would be this application having an opinion
 * about their code.
 */
export type RunOutcome = {
  node: string;
  action: string;
  at: string;
  ok: boolean;
  value: unknown;
  /** The child's traceback, verbatim. `""` when it returned. */
  error: string;
};

/** `run.start`, `run.read`, `run.last`, `run.stop` — one shape, as `observe.*` is. */
export type RunResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  node: string;
  /** `search`, `index`, `run`, `request`, `handle`, `handlers`. Each is a required export. */
  action: string;
  running: boolean;
  /** What the project's own code printed. Polled with an offset we keep (P13). */
  output: string;
  offset: number;
  /** Null where this node has never been run. Not the same as run and found wanting. */
  outcome: RunOutcome | null;
  /**
   * What was handed to `index` from this window. A memory of uploads, never a claim about
   * what the index holds: the convention gives RAG two exports and neither lists anything.
   */
  documents: string[];
};

/**
 * `deploy.*`: the compose stack, up or down.
 *
 * `services` is asked of `docker compose config` and never read out of the file — the same
 * rule that keeps the parser out of `Dockerfile`. It is empty from a poll, which does not
 * ask: the answer costs a process and does not change while the stack runs.
 */
export type DeployResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  running: boolean;
  output: string;
  offset: number;
  /** Whether there is a docker to use. Sent so a button that cannot work can say why. */
  available: boolean;
  version: string;
  services: string[];
};
