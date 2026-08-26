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
};

export type Service = {
  name: string;
  ports: number[];
  reachable: boolean;
  dockerfile: string | null;
};

export type Environment = {
  interpreter: string;
  interpreter_origin: string;
  compose_file: string | null;
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
export type Placement = { x?: number; y?: number; collapsed?: boolean };
export type Layout = Record<string, Placement>;

export type LayoutRead = { api_version: number; layout: Layout };
export type WriteResult = { api_version: number; ok: boolean; detail: string };

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
  carriers: string[];
  top_level: boolean;
  check: string;
  /** How a person talks to this kind, or "" for the ones nobody can talk to (P17.2). */
  converses: string;
  /** How documents are handed to it, or "" for the kinds that hold no index (P17.5). */
  indexes: string;
  description: string;
};

export type GraphKinds = { api_version: number; kinds: NodeKindInfo[] };

export type BodyWrite = {
  api_version: number;
  written: boolean;
  file: string | null;
  refused: string | null;
  diagnostics: Diagnostic[];
};

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
