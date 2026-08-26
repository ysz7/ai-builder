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
  CommandList,
  GraphKinds,
  GraphRead,
  IndexResult,
  InspectResult,
  Layout,
  LayoutRead,
  NodeSource,
  RepairApply,
  RepairList,
  RunResult,
  ServiceResult,
  TalkResult,
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

/**
 * One step of a turn.
 *
 * `detail` is what a tool was called with, or what it answered; `id` is the agent's own
 * `tool_use_id`, which is what lets a result be shown against the call it answers rather
 * than merely after it.
 */
export type AgentEvent = {
  kind: string;
  text: string;
  file: string;
  detail: string;
  id: string;
  /** The agent's own name for the tool it called — `Bash`, `Read`. Empty where none applies. */
  tool: string;
};
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
  /**
   * The agent's own running estimate of what this turn has cost.
   *
   * Usage proper is reported exactly twice in a turn — at the start of a message and at its
   * end — so a number that *moves* while it works is the agent's estimate or it is nobody's.
   * This one is the agent's, and it says so by being called an estimate.
   */
  spending: number;
  /**
   * What the agent says it can be asked to do — **names only**, because names only is what it
   * sends. It is read rather than listed here: the set changes with the agent's plugins and
   * its version, and a copy of ours would go stale without ever looking wrong.
   *
   * Empty from a poll that carried no `init`, which is most of them. The panel keeps the last
   * list it was handed rather than clearing on every quiet answer.
   */
  commands: string[];
  /**
   * How this project's sessions are started, or `null` where the verb was not asked.
   *
   * All three are **flags at spawn** — the agent offers no way to change a running session's
   * model or its permission mode — so setting one restarts the process under `--resume`,
   * which keeps the conversation and not the process it was being had in. The interface has
   * to say that rather than let a person believe the switch is free mid-answer.
   */
  settings: {
    model: string;
    effort: string;
    mode: string;
    /**
     * Whether the agent may run commands — `""` (no) or `"bash"`.
     *
     * **Not the permission mode**, which was measured and does not grant it: `acceptEdits`
     * asks for an approval this transport cannot carry, and `dontAsk` refuses outright.
     */
    commands: string;
  } | null;
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

/**
 * A picture pasted into a turn.
 *
 * Base64 and a media type, because what is on a clipboard is bytes — there is no file on
 * disk to point the agent at, and writing one to invent a path would leave it there.
 */
export type Pasted = { media_type: string; data: string };

/** Send one turn. What comes back arrives through `agentPoll`, never from here. */
export function agentSay(
  project: string,
  text: string,
  images: Pasted[] = [],
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.say", { project, text, images });
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

/**
 * The node-kind registry.
 *
 * Which buttons a node gets is the **registry's** answer, not a list of kind names kept in
 * the front end: a kind opts in by naming a way in, and a kind that has not opted in shows
 * no button at all rather than one that does nothing (P17.2).
 */
export function graphKinds(): Promise<GraphKinds> {
  return coreRequest<GraphKinds>("graph.kinds", {});
}

// -- talking to what the project built (P17) ---------------------------------
//
// The same shape as `run.*`, `work.*` and `agent.*`: nothing is pushed, the answer is polled
// with an offset this side keeps, and nothing starts implicitly (P11, P13).

/** Open a conversation with one node. Never implicit — somebody pressed a button. */
export function talkOpen(project: string, node: string): Promise<TalkResult> {
  return coreRequest<TalkResult>("talk.open", { project, node });
}

/** Ask one thing. What comes back arrives through `talkPoll`, never from here. */
export function talkSay(
  project: string,
  node: string,
  text: string,
): Promise<TalkResult> {
  return coreRequest<TalkResult>("talk.say", { project, node, text });
}

export function talkPoll(
  project: string,
  node: string,
  offset: number,
): Promise<TalkResult> {
  return coreRequest<TalkResult>("talk.poll", { project, node, offset });
}

export function talkState(project: string): Promise<TalkResult> {
  return coreRequest<TalkResult>("talk.state", { project });
}

export function talkClose(project: string, node: string): Promise<TalkResult> {
  return coreRequest<TalkResult>("talk.close", { project, node });
}

/**
 * Hand a pipeline its documents (P17.5).
 *
 * A write into somebody's store, so it happens because a person pressed it and never as a
 * consequence of drawing the graph. What comes back is what the store said afterwards.
 */
export function ragIndex(project: string, node: string): Promise<IndexResult> {
  return coreRequest<IndexResult>("rag.index", { project, node });
}

// -- the commands the project already has, and running one (P17.6, P17.7) ----

export function commandList(
  project: string,
  directory = "",
): Promise<CommandList> {
  return coreRequest<CommandList>("command.list", { project, directory });
}

export function commandStart(
  project: string,
  command: string,
  directory = "",
): Promise<RunResult> {
  return coreRequest<RunResult>("command.start", {
    project,
    command,
    directory,
  });
}

export function commandState(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("command.state", { project });
}

export function commandLogs(
  project: string,
  offset: number,
): Promise<RunResult> {
  return coreRequest<RunResult>("command.logs", { project, offset });
}

export function commandStop(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("command.stop", { project });
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

/**
 * Name one conversation.
 *
 * The label is the only field of a conversation that belongs to the person: its id is the
 * agent's, its transcript is the agent's, when it happened is a fact. An empty name puts the
 * default back rather than leaving a chip with nothing on it.
 */
export function agentRename(
  project: string,
  session: string,
  label: string,
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.rename", { project, session, label });
}

/**
 * Who the agent is signed in as.
 *
 * **Read, never held.** The credential belongs to the CLI, which put it on this machine
 * through its own browser flow; this application stores nothing and has nothing to leak. What
 * it answers is the question a bare "Connect" button could not: whose account is about to be
 * spent.
 */
export type Account = {
  api_version: number;
  signed_in: boolean;
  method: string;
  email: string;
  plan: string;
  organisation: string;
  detail: string;
};

export function agentAccount(): Promise<Account> {
  return coreRequest<Account>("agent.account", {});
}

/** Opens the agent's own browser flow and waits for it. Never implicit (P11). */
export function agentSignIn(console = false): Promise<Account> {
  return coreRequest<Account>("agent.sign_in", { console });
}

export function agentSignOut(): Promise<Account> {
  return coreRequest<Account>("agent.sign_out", {});
}

/**
 * Stop the turn that is running. **Not the session.**
 *
 * The agent takes a control message on the same pipe a turn is sent on and ends the turn;
 * killing the process would throw away the conversation to cancel one answer.
 */
export function agentInterrupt(project: string): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.interrupt", { project });
}

/**
 * What a session may be set to.
 *
 * **Asked, never listed here.** The offered set is a fact about which flags this agent
 * honours, and one of them — `manual` — is accepted and then ignored, which is exactly what a
 * menu written from documentation gets wrong. The core refuses that one by name; this only
 * draws what it is handed.
 */
export type AgentChoices = {
  api_version: number;
  models: string[];
  efforts: string[];
  modes: string[];
  commands: string[];
};

export function agentChoices(): Promise<AgentChoices> {
  return coreRequest<AgentChoices>("agent.choices", {});
}

/**
 * Set the model, the effort or the permission mode.
 *
 * A key left out means "leave it", which is not the same as `""` — the deliberate choice of
 * the agent's own default. When a conversation is open it is restarted onto the new setting
 * and the answer says so.
 */
export function agentConfigure(
  project: string,
  change: {
    model?: string;
    effort?: string;
    mode?: string;
    commands?: string;
  },
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.configure", { project, ...change });
}
