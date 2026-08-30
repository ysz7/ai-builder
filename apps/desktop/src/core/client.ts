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
  BlueprintInsert,
  GraphCompositions,
  BlueprintPlan,
  Blueprints,
  BodyWrite,
  CallResult,
  CommandList,
  DotenvRead,
  Environment,
  GraphKinds,
  GraphRead,
  IndexResult,
  InspectResult,
  Layout,
  LayoutRead,
  Provider,
  ProvidersRead,
  NodeSource,
  NodeWrite,
  RepairApply,
  RepairList,
  RunResult,
  ServiceResult,
  TalkResult,
  ToolCallResult,
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

/**
 * The project's `.env`, as text.
 *
 * **There is no path parameter and there will not be one**: the core answers for exactly
 * `<project>/.env`, so this is not a general file reader wearing an environment's name.
 */
export function envReadFile(project: string): Promise<DotenvRead> {
  return coreRequest<DotenvRead>("env.read_file", { project });
}

/** Store `.env` verbatim. Nothing is normalised, and nothing is restarted afterwards. */
export function envWriteFile(
  project: string,
  text: string,
): Promise<WriteResult> {
  return coreRequest<WriteResult>("env.write_file", { project, text });
}

/**
 * Places a model can be reached from. Options, never facts about the graph.
 *
 * What a node actually uses is in its knobs, in code (I-1). Deleting this store changes
 * nothing about the project, which is the test that keeps it a convenience.
 */
export function providersRead(project: string): Promise<ProvidersRead> {
  return coreRequest<ProvidersRead>("providers.read", { project });
}

/** Store the whole list. An entry carrying a key is refused, never sanitised. */
export function providersWrite(
  project: string,
  providers: Provider[],
): Promise<WriteResult> {
  return coreRequest<WriteResult>("providers.write", { project, providers });
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
): Promise<NodeWrite> {
  return coreRequest<NodeWrite>("knob.set", { project, node, knob, value });
}

/**
 * Rename a node -- the second of the three write verbs.
 *
 * Reachable from the card's `\u22ee` menu (P18.3). Like every write here it addresses a
 * syntax node rather than a line, is validated before it lands, and comes back as a result
 * when it is refused rather than as an error.
 */
export function nodeSetTitle(
  project: string,
  node: string,
  title: string,
): Promise<NodeWrite> {
  return coreRequest<NodeWrite>("node.set_title", { project, node, title });
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
  /**
   * What was decided about an `asking`, and only about one: `""`, `"allowed"` or `"denied"`.
   *
   * `""` is a request **still waiting** — the turn is stopped on it — and that is a different
   * state from denied, which is why it is a word rather than a boolean.
   */
  answer: string;
  /**
   * The questions on an `AskUserQuestion`, as the agent wrote them (Q37).
   *
   * Empty on everything else. Typed loosely on purpose: the fields belong to the agent's
   * own tool, and a contract here would go stale the first time that tool gained one — so
   * the panel reads what it needs and ignores the rest.
   */
  questions: AgentQuestion[];
};

/** One question and its options. `multiSelect` is the tool's own spelling. */
export type AgentQuestion = {
  question?: string;
  header?: string;
  multiSelect?: boolean;
  options?: { label?: string; description?: string }[];
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
     * Whether commands run **without being asked about** — `""` (ask) or `"bash"`.
     *
     * Not the permission mode, and not what makes commands possible: pressing "Allow" on the
     * request does that (Q21). This is the standing answer of somebody who does not want to
     * be asked about commands in this project.
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

/** What the project runs in, and what is up. A read: describing an environment changes it not. */
export function envStatus(project: string): Promise<{
  api_version: number;
  environment: Environment;
}> {
  return coreRequest("env.status", { project });
}

/**
 * Call a declared service on the port it publishes.
 *
 * **The port is asked of docker, never assumed** — which host port a service publishes is
 * the compose file's business, and guessing 8000 because it is usually 8000 would be
 * inventing the address of somebody else's program.
 */
export function envCall(
  project: string,
  service: string,
  path: string,
  method: string,
  port = 0,
): Promise<CallResult> {
  return coreRequest<CallResult>("env.call", {
    project,
    service,
    path,
    method,
    port,
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
/**
 * The blueprint catalog, when one is configured.
 *
 * No catalog is a normal answer with `catalog: null`, never an error. Nothing is passed
 * from here, so the core answers from `FRAMESTACK_BLUEPRINTS` or not at all -- a catalog is
 * named, never found lying next to something.
 */
export function agentBlueprints(): Promise<Blueprints> {
  return coreRequest<Blueprints>("agent.blueprints", {});
}

/**
 * What inserting an entry would do. A read: it writes nothing and runs nothing.
 *
 * Always called before an insert, whichever origin the entry has -- what differs between a
 * bundled entry and a third-party one is whether a person is shown the answer, not whether
 * it is asked for.
 */
export function blueprintPlan(
  project: string,
  blueprint: string,
): Promise<BlueprintPlan> {
  return coreRequest<BlueprintPlan>("blueprint.plan", { project, blueprint });
}

/**
 * Write the entry's files into the project.
 *
 * `plan` is the identity the plan returned and it has no default anywhere in this stack --
 * there must be no way to insert a stranger's code without having been handed the
 * description of what was going to be inserted (Q28.2). Copying executes nothing: no
 * import, no install, no post-insert hook.
 */
export function blueprintInsert(
  project: string,
  blueprint: string,
  plan: string,
): Promise<BlueprintInsert> {
  return coreRequest<BlueprintInsert>("blueprint.insert", {
    project,
    blueprint,
    plan,
  });
}

/**
 * Connect two nodes by writing the call into the generated zone (P21).
 *
 * **No arrow comes back from this.** An edge appears in the next read because a type now
 * crosses a boundary, or in the next observed run because a flow was drawn (Q9) — never
 * because a gesture was made. A write that stands while no arrow appears is information.
 */
export function nodeConnect(
  project: string,
  source: string,
  target: string,
): Promise<NodeWrite> {
  return coreRequest<NodeWrite>("node.connect", { project, source, target });
}

/**
 * Claim a node as a member of a group (Q35).
 *
 * Two ids, because membership is a relation. It refuses rather than guesses: a node some
 * other group already claims comes back naming that group, since I-3 gives a node one
 * parent and moving one is a different intention from claiming an unclaimed one.
 */
export function nodeClaim(
  project: string,
  group: string,
  member: string,
): Promise<NodeWrite> {
  return coreRequest<NodeWrite>("node.claim", { project, group, member });
}


/** What may be connected to what. Asked once; the canvas keeps no list of its own. */
export function graphCompositions(): Promise<GraphCompositions> {
  return coreRequest<GraphCompositions>("graph.compositions", {});
}

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
/**
 * Hand a pipeline its documents, or rebuild from the ones the project already has.
 *
 * `documents` are paths on this machine, passed through and copied nowhere. Omitted, this
 * is the verb it always was. A pipeline whose `build_index` cannot take them **refuses**
 * rather than indexing without them -- see the core, where that decision is made.
 */
export function ragIndex(
  project: string,
  node: string,
  documents?: string[],
): Promise<IndexResult> {
  return coreRequest<IndexResult>("rag.index", {
    project,
    node,
    ...(documents && documents.length > 0 ? { documents } : {}),
  });
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

/**
 * Call one tool on a consumed server, with arguments a person typed (P15).
 *
 * It runs in the project's interpreter through the project's own `connect()`, never
 * straight into the SDK -- which is what leaves a frame the graph can see. Arguments are
 * never invented here: input is typed or there is no call (I-5).
 */
export function mcpCall(
  project: string,
  node: string,
  tool: string,
  args: Record<string, unknown>,
): Promise<ToolCallResult> {
  return coreRequest<ToolCallResult>("mcp.call", {
    project,
    node,
    tool,
    arguments: args,
  });
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

/** Is a worker running? A read: it starts nothing (P11). */
export function workStatus(project: string): Promise<RunResult> {
  return coreRequest<RunResult>("work.status", { project });
}

// -- terminals ---------------------------------------------------------------

/**
 * One terminal the person types into.
 *
 * **Not a verb on a node** — which is exactly why it may run what `command.start` refuses.
 * A shell colours nothing, proves nothing and is read by nothing; it is somebody's own shell,
 * opened on purpose, in the project's directory. See `shell.py`.
 */
export type ShellRef = {
  id: string;
  name: string;
  running: boolean;
  pid: number;
};

export type ShellResult = {
  api_version: number;
  ok: boolean;
  detail: string;
  shell: string;
  running: boolean;
  output: string;
  offset: number;
  shells: ShellRef[];
};

export function shellOpen(project: string, name = ""): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.open", { project, name });
}

/** Type into one. **Verbatim** — the newline is the caller's to send, and so is `\x03`. */
export function shellWrite(
  project: string,
  shell: string,
  text: string,
): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.write", { project, shell, text });
}

/** What it printed since `offset`. Polled, never pushed (P13). */
export function shellRead(
  project: string,
  shell: string,
  offset: number,
): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.read", { project, shell, offset });
}

/** How wide its window is — the one thing wrapping programs read. */
export function shellResize(
  project: string,
  shell: string,
  columns: number,
  rows: number,
): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.resize", {
    project,
    shell,
    columns,
    rows,
  });
}

/** Close it, and the process group it started with it. */
export function shellClose(project: string, shell: string): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.close", { project, shell });
}

/** Which terminals are open here. A read: it opens nothing. */
export function shellList(project: string): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.list", { project });
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
 * Answer one standing request for permission.
 *
 * **The turn is blocked on this call.** The agent asked with a control request and stopped
 * where it stood; the answer resumes it from that point rather than starting the work again,
 * which is what makes this a dialogue instead of a setting change followed by a retry.
 *
 * `always` sends back the rule the agent itself suggested, and the agent writes it into the
 * project's own `.claude/settings.local.json` — the same store its terminal reads. Nothing
 * about somebody's policy is kept on this side.
 */
/**
 * Answer one standing request. The turn is blocked on this and resumes from where it is.
 *
 * `answers` belongs to `AskUserQuestion` and is refused on anything else (Q37): that tool
 * is the agent asking a person to **decide** rather than to permit, and allowing it without
 * saying what was decided lets the turn carry on as though nobody had been asked.
 */
export function agentPermission(
  project: string,
  request: string,
  allow: boolean,
  always = false,
  answers?: Record<string, string>,
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.permission", {
    project,
    request,
    allow,
    always,
    ...(answers ? { answers } : {}),
  });
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
