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
