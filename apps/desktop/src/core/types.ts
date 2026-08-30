/**
 * The shapes the core returns, transcribed from the schemas it declares.
 *
 * Written out rather than inferred, for the reason `api.py` writes them out: a contract
 * is a decision. These are the *client's* copy of it, and the payload announces its
 * `api_version` so a mismatch can be seen rather than guessed at.
 *
 * Nothing here is a model of the graph. The graph is the core's answer; this is the type
 * of that answer, and the UI renders it without keeping a second opinion (I-1).
 */

export type Location = {
  file: string;
  object: string;
  start_line: number;
  end_line: number;
};

export type Parameter = {
  name: string;
  annotation: string | null;
  default: string | null;
};

export type Signature = {
  parameters: Parameter[];
  returns: string | null;
};

export type Knob = {
  name: string;
  type: string;
  default: string | null;
  widget: string | null;
  label: string | null;
  help: string | null;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[] | null;
  location: Location | null;
};

export type GraphNode = {
  id: string;
  kind: string;
  title: string | null;
  carrier: string;
  carrier_type: string;
  location: Location;
  zone: string | null;
  signature: Signature | null;
  knobs: Knob[];
  members: string[];
  unresolved_members: string[];
  /**
   * The first line of the carrier's docstring, or "" (Q29).
   *
   * What the node says about itself, in the author's own words. Drawn on the card's
   * description line and read by nothing that decides anything.
   */
  summary: string;
};

export type GraphFunction = {
  path: string;
  zone: string | null;
  signature: Signature;
  signature_locked: boolean;
  location: Location;
  body_digest: string | null;
  body_source: string | null;
};

/** A type crossing a boundary. Not the same relation as a flow arrow (Q9). */
export type ContractEdge = {
  source: string;
  target: string;
  contract: string;
};

/** One node having run, then another. `origin` is "observed" or "wiring". */
export type FlowEdge = {
  source: string;
  target: string;
  origin: string;
};

export type Diagnostic = {
  code: string;
  message: string;
  location: Location;
  rule: string;
  severity: string;
  repair: string;
  node: string | null;
};

export type Observation = {
  passed: boolean;
  check: string;
  detail: string | null;
  /**
   * What produced this, named rather than described — a test id, where a test entered the
   * node. `detail` says the same thing in a sentence, and the sentence is the right answer
   * wherever there is room for one; this is what the card's evidence chip is *drawn* from,
   * so nothing here has to parse the prose to find the name (P18.3). "" where the evidence
   * has no name beyond `check`.
   */
  by: string;
};

export type Service = {
  name: string;
  ports: number[];
  /** Something answers on the port it publishes — the question a caller cares about. */
  reachable: boolean;
  /**
   * Docker says its container is up.
   *
   * **A different claim from `reachable`**, and never a substitute for it: a container that
   * runs and a program inside it that answers are two facts, and the gap between them is
   * where "I started it and nothing works" lives.
   */
  running: boolean;
  dockerfile: string | null;
};

export type Environment = {
  interpreter: string;
  interpreter_origin: string;
  compose_file: string | null;
  /** Is anything running? What `env.up` started, and so what its button has to reflect. */
  up: boolean;
  services: Service[];
  missing: string[];
  docker_unavailable: string | null;
  incomplete: string | null;
};

/** Whether the graph is complete about what the code holds (Q12). */
export type Completeness = {
  state: string;
  detail: string;
  undeclared: Location[];
};

export type GraphRead = {
  api_version: number;
  root: string;
  graph: {
    root: string;
    nodes: GraphNode[];
    functions: GraphFunction[];
    edges: ContractEdge[];
    unparsed: Location[];
  };
  diagnostics: Diagnostic[];
  /** node id -> "green" | "broken" | "unproven". The only place green is decided (I-5). */
  verdicts: Record<string, string>;
  observations: Record<string, Observation>;
  /** node id -> why its check could not run. Never an absence of information. */
  skipped: Record<string, string>;
  environment: Environment | null;
  flow: FlowEdge[];
  completeness: Completeness;
  mode: string;
  accepted: boolean;
};

export type Verdict = "green" | "broken" | "unproven";

/**
 * Where the person put things. The core stores this and looks inside none of it (Q13),
 * so the shape is the canvas's own -- and it is the canvas that has to keep it honest.
 */
/**
 * A node carries a position; a **group carries only whether it is collapsed**. A frame is
 * the bounding box of its members and has no geometry of its own, so a stored position for
 * one would be a number nothing reads -- until something did, and then the frame and its
 * contents could disagree.
 */
/**
 * `expanded` joins them for the same reason they are here: whether a card is showing all of
 * its knobs or the first few is a fact about how this person is looking at the graph, not
 * about the project. The core stores it and refuses to understand it, exactly as it does a
 * coordinate.
 */
export type Placement = {
  x?: number;
  y?: number;
  collapsed?: boolean;
  expanded?: boolean;
  /**
   * Draw flow arrows. Only ever read off `VIEW_KEY`, never off a node's own entry.
   *
   * A view preference and a node's position are the same kind of fact -- something a person
   * arranged, which the core stores without understanding (Q13) -- so they share the file
   * rather than earning a sixth one in `.framestack/`.
   */
  flow?: boolean;
  /** Which view is showing -- `"graph"` or `"use"`. Read off `VIEW_KEY` only, like `flow`. */
  tab?: string;
};
export type Layout = Record<string, Placement>;

/**
 * Where a canvas-wide preference lives in the layout.
 *
 * A node id is a dotted Python-ish identifier, so `@` cannot collide with one, and an entry
 * matching no node is already an ordinary state the canvas ignores: layout entries are
 * never tidied on sight, because an agent rewriting a file makes a node vanish and come
 * back (Q13). The core stores this like every other key -- opaquely, and it stays that way.
 */
export const VIEW_KEY = "@view";

export type LayoutRead = { api_version: number; layout: Layout };

/**
 * `env.read_file`: the `.env` file as text.
 *
 * No key/value map, deliberately -- the core does not parse this file, so it has none to
 * report. `ignored` is git's answer about whether the file would be committed, and `null`
 * is "nobody could tell" (no git, or not a repository), which is not the same as `false`.
 */
export type DotenvRead = {
  api_version: number;
  text: string;
  exists: boolean;
  ignored: boolean | null;
};
/**
 * `layout.write` and `project.create`: did it happen, and what was said.
 *
 * **Not the shape a write into code comes back in** — see `NodeWrite`. These two answer
 * `ok`/`detail`; every verb that edits somebody's Python answers `written`/`refused`, and
 * reading one as the other is the mistake this comment exists to stop being made again.
 */
export type WriteResult = { api_version: number; ok: boolean; detail: string };

/**
 * What every write into code answers: `knob.set`, `node.set_title`, `node.set_body`,
 * `node.connect` — the core's `WRITE_SCHEMA`, transcribed.
 *
 * It has **no `ok` field**, and the three verbs above were typed as though it did:
 * `WriteResult & { file, refused }` type-checked, because `WriteResult` really does have an
 * `ok`, and it was simply never in the payload. So `result.ok` was `undefined` at runtime,
 * every successful write reported "the write was refused", and the graph was never re-read
 * — a knob landed on disk and the card went on showing the old value under an error.
 *
 * The lesson is the one the module header already states: this file is the *client's copy*
 * of a contract, and a copy that is never checked against the original drifts silently.
 * `written` is the field to read; `refused` is why, when it is false.
 */
export type NodeWrite = {
  api_version: number;
  written: boolean;
  file: string | null;
  refused: string | null;
  diagnostics: Diagnostic[];
};

/**
 * A divergence, and what may be done about it.
 *
 * `mechanical` is the subset of `resolutions` this toolchain can carry out; anything else
 * is handed to the agent as `request`. Nothing here has a default resolution -- §9's second
 * case has two non-equivalent answers, and the dialog is where a person picks one.
 */
export type Repair = {
  code: string;
  message: string;
  location: Location;
  rule: string;
  fault: string;
  resolutions: string[];
  mechanical: string[];
  repair: string;
  request: string;
  node: string | null;
  reference: string | null;
};

export type RepairList = { api_version: number; repairs: Repair[] };
export type RepairApply = {
  api_version: number;
  applied: boolean;
  snapshot_updated: boolean;
  file: string | null;
  refused: string | null;
  diagnostics: Diagnostic[];
  /** Nodes the repair left without evidence. Never quietly read as "fine" (I-5). */
  unproven: string[];
};

/** A process this toolchain started. `port` is 0 for a worker, which publishes nothing. */
export type RunState = {
  pid: number;
  port: number;
  target: string;
  command: string[];
  started_at: string;
} | null;

export type RunResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  state: RunState;
  logs: string;
  offset: number;
};

export type CallResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  status: number | null;
  body: string;
};

export type ServiceResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  services: string[];
};

/**
 * What one remote tool said when a person called it (P15).
 *
 * **Not `CallResult`** — that one is `run.call`, an HTTP request whose `status` is a number.
 * This `status` is the core's own word, and the two were nearly typed as one thing because
 * both are called "call".
 */
export type ToolCallResult = {
  api_version: number;
  ok: boolean;
  status: string;
  detail: string;
  result: string;
};

/** What a consumed MCP server offered when somebody pressed inspect. Never written down. */
export type InspectResult = {
  api_version: number;
  ok: boolean;
  status: string;
  detail: string;
  tools: { name: string; description: string }[];
  allowed: string[];
  missing: string[];
};

/**
 * One conversation with a node, in the project's own interpreter (P17.1).
 *
 * A conversation is an action **on a node**, never a node of its own (Q18) — so it is
 * addressed by one, and nothing new appears on the graph. The events are what the project
 * said, in the order it said it: no history is assembled on this side, because the project
 * is the one that remembers (Q19).
 */
export type TalkResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  node: string;
  running: boolean;
  events: TalkEvent[];
  offset: number;
  open: string[];
};

/** `type` is the project's own word for what happened: ready, asked, answer, failed. */
export type TalkEvent = {
  type: string;
  text: string;
  detail: string;
  trace: string;
};

/** What the store said after a pipeline was handed its documents (P17.5). Never stored. */
export type IndexResult = {
  api_version: number;
  ok: boolean;
  status: string;
  detail: string;
  /** What the store answered `len` with, or "" — never the documents that went in. */
  held: string;
};

/**
 * The commands the project already has (P17.6).
 *
 * Asked of npm, never read out of `package.json` (§5.8), and on the graph nowhere: a front
 * end is run, not modelled, and a node that cannot be red is decoration (Q20).
 */
export type CommandList = {
  api_version: number;
  ok: boolean;
  detail: string;
  commands: { name: string; command: string }[];
  directory: string;
};

/** One entry of the node-kind registry. What a client may show comes from here (§5.6). */
export type NodeKindInfo = {
  name: string;
  /**
   * The family this kind belongs to, from the registry's own naming rule.
   *
   * Sent rather than split off the name here: a client cutting a kind name at the dot would
   * be a second opinion about how kinds are named — small, right today, and wrong long
   * after the convention moved.
   */
  family: string;
  carriers: string[];
  /**
   * The paths that carry a file-carried kind, or [].
   *
   * For those kinds "what carries this" is a filename, and `file` on its own tells a reader
   * nothing about which file (§5.7).
   */
  artifact: string[];
  top_level: boolean;
  check: string;
  /** How a person talks to this kind, or "" for the ones nobody can talk to (P17.2). */
  converses: string;
  /** How documents are handed to it, or "" for the kinds that hold no index (P17.5). */
  indexes: string;
  /**
   * Which verb family starts and stops this kind — `run`, `work`, `env` — or "" for the
   * kinds nothing starts.
   *
   * This is what tells a node whether it can be *running*, which is the one piece of state
   * the graph itself cannot carry: the graph is a projection of code, and whether a process
   * is alive is not in the code.
   */
  starts: string;
  description: string;
};

/**
 * One connection this toolchain will write (P21).
 *
 * Asked of the core so a canvas can decline a gesture that would only ever be refused —
 * there is no second list of what may be dragged onto what, because there is one table and
 * it is the one that does the writing.
 */
export type Composition = {
  source: string;
  target: string;
  description: string;
};

export type GraphCompositions = {
  api_version: number;
  compositions: Composition[];
};

export type GraphKinds = {
  api_version: number;
  /**
   * Every family, in the order the registry declares them.
   *
   * The library groups by this and holds no list of its own: **a family exists because a
   * kind named it**, and a written-down list here is exactly what would let a new kind be
   * added and quietly appear nowhere (P19).
   */
  families: string[];
  kinds: NodeKindInfo[];
};

/** One entry of a blueprint catalog. */
export type BlueprintEntry = {
  id: string;
  title: string;
  summary: string;
  path: string;
  section: string;
  /**
   * "bundled" or "named" (Q28.1) — two sources and no third.
   *
   * It decides one thing: whether inserting shows the diff and waits. A bundled entry ships
   * inside the application, so its trust decision was made once, at install, and asking
   * again is ceremony that trains people to click through. A named one is a stranger's code
   * from a path this person passed in, and it shows everything first.
   */
  origin: string;
  /** How many files inserting it would write, or 0 for specification text only. */
  carries_code: number;
  /**
   * **A part, not a whole project** (Q36).
   *
   * It lands a node the top level cannot hold — an `mcp.server` belongs to the group that
   * consumes it — so inserting leaves exactly one gate error against that node, and
   * claiming it into a group is the next press. It decides where the entry is *offered*:
   * a part in the library beside four whole projects reads as a project that is broken.
   */
  part: boolean;
};

/** One file an insert would write, with its full contents — a diff, not a filename list. */
export type PlannedFile = {
  path: string;
  contents: string;
  /** Something is already here. A collision refuses the whole insert; it never merges. */
  collides: boolean;
};

/**
 * What inserting an entry would do, and nothing done (P20).
 *
 * `identity` is a digest over the entry and every byte it would write, and `blueprint.insert`
 * is handed it back: an entry edited between the plan and the press no longer matches, so
 * nothing can be written that was not the thing described.
 */
export type BlueprintPlan = {
  api_version: number;
  blueprint: string;
  title: string;
  origin: string;
  refused: string | null;
  files: PlannedFile[];
  collisions: string[];
  /** Third-party modules it imports, and the ones this interpreter cannot find. Facts, not
   *  a verdict: there is no allowlist and no scanner here, on purpose (Q28.4). */
  imports: string[];
  requires: string[];
  identity: string;
};

/** What an insert did. One that broke the gate is undone and says so. */
export type BlueprintInsert = {
  api_version: number;
  inserted: boolean;
  files: string[];
  refused: string | null;
  diagnostics: Diagnostic[];
};

/**
 * What input B can be given (§3).
 *
 * `catalog` is null when there is none, and that is an answer rather than an error: a
 * catalog is **never discovered**, only named — by the caller or by `FRAMESTACK_BLUEPRINTS`
 * — because what this tool offers must not depend on the shape of somebody's disk.
 */
export type Blueprints = {
  api_version: number;
  catalog: string | null;
  blueprints: BlueprintEntry[];
};

/** `node.set_body`'s answer. The same shape as every other write into code. */
export type BodyWrite = NodeWrite;

/** One function of a node's carrier, as text. Read from disk, never from the graph (I-1). */
export type FunctionSource = {
  path: string;
  zone: string | null;
  signature: string;
  signature_locked: boolean;
  location: Location;
  source: string;
};

export type NodeSource = {
  api_version: number;
  node: string;
  file: string;
  source: string;
  functions: FunctionSource[];
  refused: string | null;
};
