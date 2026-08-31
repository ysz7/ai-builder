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
  Graph,
  Layout,
  LayoutRead,
  Opened,
  ObserveResult,
  SettingsResult,
  WriteResult,
} from "./types";

/**
 * Read a project into a graph.
 *
 * The one question the canvas asks, and it is a **read**: the core walks the directories
 * and parses the imports, and imports nothing and runs nothing. That is why it is safe to
 * call because a window happened to open — and why it comes back with no colour in it.
 * Whether any of this works is Observe's answer, and Observe is a thing somebody presses.
 */
export function graphRead(project: string): Promise<Graph> {
  return coreRequest<Graph>("graph.read", { project });
}


/**
 * Run the project's own tests and colour the graph from what happened.
 *
 * The one call in this file that executes a stranger's code, which is why it is a verb
 * somebody presses and never something a window does on opening. It returns as soon as the
 * suite is running; what it decided arrives through `observeRead`.
 */
export function observeStart(project: string): Promise<ObserveResult> {
  return coreRequest<ObserveResult>("observe.start", { project });
}

/** Poll the run. The caller keeps the offset it was last given (P13). */
export function observeRead(
  project: string,
  offset = 0,
): Promise<ObserveResult> {
  return coreRequest<ObserveResult>("observe.read", { project, offset });
}

/** The last verdict set. A read: it starts no suite and changes no colour. */
export function observeLast(project: string): Promise<ObserveResult> {
  return coreRequest<ObserveResult>("observe.last", { project });
}

/** One system's knobs, read from its own `settings.py`. Imports nothing, creates nothing. */
export function settingsRead(
  project: string,
  node: string,
): Promise<SettingsResult> {
  return coreRequest<SettingsResult>("settings.read", { project, node });
}

/**
 * Set one field's default.
 *
 * The whole write path of this phase, and it is deliberately this small: one field, in one
 * class, in one file, through libcst. What comes back is the file re-read — never what the
 * panel believes it just wrote.
 */
export function settingsWrite(
  project: string,
  node: string,
  field: string,
  value: number | string | boolean,
): Promise<SettingsResult> {
  return coreRequest<SettingsResult>("settings.write", {
    project,
    node,
    field,
    value,
  });
}

/**
 * Open one of the project's files in the person's own editor, at the line.
 *
 * Not a convenience. The claim of the product is that the code is the source of truth, and a
 * panel with no way through to the file would be asking somebody to take that on faith.
 */
export function editorOpen(
  project: string,
  path: string,
  line = 0,
): Promise<Opened> {
  return coreRequest<Opened>("editor.open", { project, path, line });
}

/** Where the person put things. An empty layout is the ordinary first answer. */
export function layoutRead(project: string): Promise<LayoutRead> {
  return coreRequest<LayoutRead>("layout.read", { project });
}

/** Store the whole layout. The client holds it; the core keeps it and reads nothing. */


/** Store the whole layout. The client holds it; the core keeps it and reads nothing. */
export function layoutWrite(
  project: string,
  layout: Layout,
): Promise<WriteResult> {
  return coreRequest<WriteResult>("layout.write", { project, layout });
}

/** Set a knob's value. A refusal comes back as a result, not as an error. */


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


/**
 * A picture pasted into a turn.
 *
 * Base64 and a media type, because what is on a clipboard is bytes — there is no file on
 * disk to point the agent at, and writing one to invent a path would leave it there.
 */
export type Pasted = { media_type: string; data: string };

/** Send one turn. What comes back arrives through `agentPoll`, never from here. */


/** Send one turn. What comes back arrives through `agentPoll`, never from here. */
export function agentSay(
  project: string,
  text: string,
  images: Pasted[] = [],
): Promise<AgentSession> {
  return coreRequest<AgentSession>("agent.say", { project, text, images });
}

/** What the agent has said since `offset`. Polled; nothing is ever pushed (P13). */


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


/** Type into one. **Verbatim** — the newline is the caller's to send, and so is `\x03`. */
export function shellWrite(
  project: string,
  shell: string,
  text: string,
): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.write", { project, shell, text });
}

/** What it printed since `offset`. Polled, never pushed (P13). */


/** What it printed since `offset`. Polled, never pushed (P13). */
export function shellRead(
  project: string,
  shell: string,
  offset: number,
): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.read", { project, shell, offset });
}

/** How wide its window is — the one thing wrapping programs read. */


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


/** Close it, and the process group it started with it. */
export function shellClose(project: string, shell: string): Promise<ShellResult> {
  return coreRequest<ShellResult>("shell.close", { project, shell });
}

/** Which terminals are open here. A read: it opens nothing. */


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
