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
  /** One of the four kinds, or `"file"`. Never a framework. */
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
  /** An MCP server's name. `""` on an import edge. */
  label: string;
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

/** `editor.open`: which program was started, so the answer says what happened. */
export type Opened = {
  api_version: number;
  ok: boolean;
  detail: string;
  editor: string;
};
