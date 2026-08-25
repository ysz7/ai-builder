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
      response.error ?? { code: "unknown", message: "core returned no error detail" },
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

import type { GraphRead, Layout, LayoutRead, WriteResult } from "./types";

/**
 * Read a project into a graph, with its diagnostics and verdicts.
 *
 * `observe` runs the project's own tests in a subprocess to find out what actually works,
 * so it is never automatic: a read must not execute a stranger's code because a window
 * happened to open. Without it every node is honestly `unproven` rather than falsely fine.
 */
export function graphRead(project: string, observe = false): Promise<GraphRead> {
  return coreRequest<GraphRead>("graph.read", { project, observe });
}

/** Where the person put things. An empty layout is the ordinary first answer. */
export function layoutRead(project: string): Promise<LayoutRead> {
  return coreRequest<LayoutRead>("layout.read", { project });
}

/** Store the whole layout. The client holds it; the core keeps it and reads nothing. */
export function layoutWrite(project: string, layout: Layout): Promise<WriteResult> {
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
  return coreRequest<AgentSession>("agent.start", { project, resume: resume ?? null, fork });
}

/** Send one turn. What comes back arrives through `agentPoll`, never from here. */
export function agentSay(project: string, text: string): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.say", { project, text });
}

/** What the agent has said since `offset`. Polled; nothing is ever pushed (P13). */
export function agentPoll(project: string, offset: number): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.poll", { project, offset });
}

export function agentStop(project: string): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.stop", { project });
}

/** Make an empty directory for a project. `detail` is the path when it worked. */
export function projectCreate(parent: string, name: string): Promise<WriteResult> {
  return coreRequest<WriteResult>("project.create", { parent, name });
}
