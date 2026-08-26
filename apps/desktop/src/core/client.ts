/**
 * Thin client for the Python core.
 *
 * Everything the UI asks of the system goes through here: one Tauri command,
 * `core_request`, which the Rust shell forwards to the sidecar over NDJSON and
 * routes the answer back. The shell adds no meaning of its own -- if a behavior
 * feels like it belongs in Rust, it belongs in the core instead.
 */

import { invoke } from "@tauri-apps/api/core";

export type CoreError = {
  code: string;
  message: string;
};

export class CoreRequestError extends Error {
  readonly code: string;

  constructor(error: CoreError) {
    super(error.message);
    this.name = "CoreRequestError";
    this.code = error.code;
  }
}

/** Send one request to the core and await its response. */
export async function coreRequest<T>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  const response = await invoke<{ ok: boolean; result?: T; error?: CoreError }>(
    "core_request",
    { method, params },
  );

  if (!response.ok) {
    throw new CoreRequestError(
      response.error ?? {
        code: "unknown",
        message: "core returned no error detail",
      },
    );
  }

  return response.result as T;
}

export type PingResult = {
  pong: boolean;
  echo: string | null;
  protocol_version: number;
  python: string;
  libcst: string;
  frozen: boolean;
};

export function ping(echo?: string): Promise<PingResult> {
  return coreRequest<PingResult>("ping", { echo: echo ?? null });
}

// -- the graph ---------------------------------------------------------------

import type {
  BodyWrite,
  CallResult,
  GraphRead,
  InspectResult,
  Layout,
  LayoutRead,
  NodeSource,
  RepairApply,
  RepairList,
  RunResult,
  ServiceResult,
  WriteResult,
} from "./types";

/**
 * Read a project into a graph, with its diagnostics and verdicts.
 *
 * `observe` runs the project's own tests in a subprocess to find out what actually works,
 * so it is never automatic: a read must not execute a stranger's code because a window
 * happened to open. Without it every node is honestly `unproven` rather than falsely fine.
 */
export function graphRead(
  project: string,
  observe = false,
): Promise<GraphRead> {
  return coreRequest<GraphRead>("graph.read", { project, observe });
}

/** Where the person put things. An empty layout is the ordinary first answer. */
export function layoutRead(project: string): Promise<LayoutRead> {
  return coreRequest<LayoutRead>("layout.read", { project });
}

/** Store the whole layout. The client holds it; the core keeps it and reads nothing. */
export function layoutWrite(
  project: string,
  layout: Layout,
): Promise<WriteResult> {
  return coreRequest<WriteResult>("layout.write", { project, layout });
}

/** Set a knob's value. A refusal comes back as a result, not as an error. */
export function knobSet(
  project: string,
  node: string,
  knob: string,
  value: unknown,
): Promise<WriteResult & { file: string | null; refused: string | null }> {
  return coreRequest("knob.set", { project, node, knob, value });
}

// -- the agent ---------------------------------------------------------------

export type AgentEvent = { kind: string; text: string; file: string };
export type AgentSessionRef = { id: string; label: string; at: string };
export type AgentSession = {
  api_version: number;
  ok: boolean;
  detail: string;
  session: string | null;
  running: boolean;
  available: boolean;
  version: string;
  events: AgentEvent[];
  offset: number;
  sessions: AgentSessionRef[];
  /** Tokens the last turn carried. A number, never a percentage -- see the ring. */
  context: number;
  /** Which model is answering, as the agent named it. The ring's denominator comes from it. */
  model: string;
};

/** Is there an agent on this machine, and is a session open? Starts nothing. */
export function agentSession(project: string): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.session", { project });
}

/**
 * Open a session: a new one, one continued by id, or one forked from it.
 *
 * Only ever because a person pressed the button (P11). A fork keeps the original branch --
 * "do that again differently" must not mean "lose the first attempt".
 */
export function agentStart(
  project: string,
  resume?: string,
  fork = false,
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.start", {
    project,
    resume: resume ?? null,
    fork,
  });
}

/** Send one turn. What comes back arrives through `agentPoll`, never from here. */
export function agentSay(project: string, text: string): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.say", { project, text });
}

/** What the agent has said since `offset`. Polled; nothing is ever pushed (P13). */
export function agentPoll(
  project: string,
  offset: number,
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.poll", { project, offset });
}

export function agentStop(project: string): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.stop", { project });
}

/** Make an empty directory for a project. `detail` is the path when it worked. */
export function projectCreate(
  parent: string,
  name: string,
): Promise<WriteResult> {
  return coreRequest<WriteResult>("project.create", { parent, name });
}

/**
 * The verbs that act, rather than ask.
 *
 * Each one is a button somebody presses, and none of them is reachable from a read: P11 is
 * that nothing starts implicitly, and the shape of the client is where that stops being a
 * convention. They are also all `core_request` -- a new capability is a method in the core,
 * never a command in the shell.
 */

export function repairList(project: string): Promise<RepairList> {
  return coreRequest<RepairList>("repair.list", { project });
}

/** `resolution` has no default here either. The core refuses to choose; so does this. */
export function repairApply(
  project: string,
  code: string,
  target: string,
  resolution: string,
  observe = true,
): Promise<RepairApply> {
  return coreRequest<RepairApply>("repair.apply", {
    project,
    code,
    target,
    resolution,
    observe,
  });
}

export function envUp(project: string): Promise<ServiceResult> {
  return coreRequest<ServiceResult>("env.up", { project });
}

export function envDown(project: string): Promise<ServiceResult> {
  return coreRequest<ServiceResult>("env.down", { project });
}

export function runStart(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("run.start", { project });
}

export function runStop(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("run.stop", { project });
}

export function runStatus(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("run.status", { project });
}

export function runCall(
  project: string,
  path: string,
  method: string,
): Promise<CallResult> {
  return coreRequest<CallResult>("run.call", { project, path, method });
}

export function workStart(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("work.start", { project });
}

export function workStop(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("work.stop", { project });
}

export function mcpInspect(
  project: string,
  node: string,
): Promise<InspectResult> {
  return coreRequest<InspectResult>("mcp.inspect", { project, node });
}

/** Addressed by node **and** function: code is edited through a node, never a bare path (I-6). */
export function bodySet(
  project: string,
  node: string,
  fn: string,
  source: string,
): Promise<BodyWrite> {
  return coreRequest<BodyWrite>("node.set_body", {
    project,
    node,
    function: fn,
    source,
  });
}

/** The code one node carries. A read: it opens a file and runs nothing. */
export function nodeSource(project: string, node: string): Promise<NodeSource> {
  return coreRequest<NodeSource>("node.source", { project, node });
}

/**
 * What a process this toolchain started has printed since `offset`.
 *
 * **Polled, never pushed** (P13): the wire carries one answer per request, and the caller
 * keeps the offset. That is why the terminal asks again rather than being told.
 */
export function runLogs(project: string, offset: number): Promise<RunResult> {
  return coreRequest<RunResult>("run.logs", { project, offset });
}

export function workLogs(project: string, offset: number): Promise<RunResult> {
  return coreRequest<RunResult>("work.logs", { project, offset });
}

/**
 * Drop one conversation from this project's list.
 *
 * Forgets **our reference and nothing else**: the transcript is the agent's, and this
 * toolchain has no reach into where it keeps it. The one running is closed first, because a
 * list entry is the only way back to a session.
 */
export function agentForget(
  project: string,
  session: string,
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.forget", { project, session });
}
