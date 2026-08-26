/**
 * The agent, docked bottom right.
 *
 * **The transcript is not the point and stays folded.** What the agent does to the code shows
 * up on the canvas -- that is the whole idea of this product -- so at rest the dock is an
 * input, a send button, a way to attach files and a ring showing how full the conversation
 * is. One line of status appears above it while a turn is running; the transcript and the
 * conversations are behind the toggle, and it opens to full height because reading a
 * transcript through a letterbox is not reading.
 *
 * Nothing is pushed (P13): a turn in flight is polled with an offset the client keeps, and
 * the polling stops when the turn is done. A quiet session costs nothing.
 *
 * A blocked tool is the entire permission surface there is (Q17) -- the stream carries no
 * "may I?" to answer -- so it is surfaced rather than swallowed.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import {
  agentForget,
  agentPoll,
  agentSay,
  agentSession,
  agentStart,
} from "../core/client";
import { Notice } from "./Notice";
import type { AgentEvent, AgentSessionRef } from "../core/client";

const POLL_MS = 700;

/**
 * How big each model's context window is.
 *
 * A fraction needs a denominator, and the denominator is a property of the model rather than
 * of the session -- it differs by a factor of five across models the agent may pick. So the
 * model is read from the stream (`poll.model`) and looked up here, rather than assumed: an
 * assumed 200k against a 1M model draws a ring five times too full, which is worse than no
 * ring, because it reads as a reason to compact when there is none.
 *
 * A model that is not in this table gets **no ring at all** -- the raw count is shown alone.
 * Not knowing the window is a fact about us, and inventing one would hide it.
 */
const WINDOWS: Record<string, number> = {
  "claude-opus-5": 1_000_000,
  "claude-sonnet-5": 1_000_000,
  "claude-fable-5": 1_000_000,
  "claude-haiku-4-5": 200_000,
};

function windowFor(model: string): number {
  if (!model) return 0;
  const exact = WINDOWS[model];
  if (exact) return exact;
  // Dated ids ("claude-haiku-4-5-20251001") name the same model as the alias they extend.
  const prefix = Object.keys(WINDOWS).find((name) => model.startsWith(name));
  return prefix ? WINDOWS[prefix] : 0;
}

type Props = {
  project: string;
  onTouch: (files: string[]) => void;
  onSettled: () => void;
  /**
   * Words put into the field from elsewhere -- a repair the toolchain cannot carry out.
   * Placed in the draft and **never sent**: handing a request over is not the same as
   * deciding to make it, and the person still presses send.
   */
  handOver: string | null;
  onHandedOver: () => void;
};

function Toggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      className="bp-icon"
      onClick={onToggle}
      title={open ? "Hide the conversation" : "Show the conversation"}
    >
      {open ? "▾" : "▴"}
    </button>
  );
}

export function Chat({
  project,
  onTouch,
  onSettled,
  handOver,
  onHandedOver,
}: Props) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AgentSessionRef[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [blocked, setBlocked] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<AgentEvent[]>([]);
  const [context, setContext] = useState(0);
  const [model, setModel] = useState("");
  /** A session is being opened right now. Nothing else may ask for one until it answers. */
  const [connecting, setConnecting] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const offset = useRef(0);
  const timer = useRef<number | null>(null);
  const field = useRef<HTMLTextAreaElement | null>(null);
  const shell = useRef<HTMLDivElement | null>(null);

  /**
   * The conversation closes when attention goes elsewhere.
   *
   * `pointerdown` rather than `click`: a press that lands on the canvas should put the chat
   * away before the canvas does anything with it, so the two never happen in the wrong order.
   * The listener exists only while the panel is open -- a document listener kept alive for a
   * closed panel is a handler that runs on every press in the application for no reason.
   */
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        shell.current &&
        !shell.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  // A request handed over from the repair dialog lands in the field, focused and unsent.
  useEffect(() => {
    if (!handOver) return;
    setDraft((previous) => (previous ? `${previous}\n${handOver}` : handOver));
    setOpen(true);
    field.current?.focus();
    onHandedOver();
  }, [handOver, onHandedOver]);

  /**
   * Every call to the core, with its failure made visible.
   *
   * Without this a rejected request disappears into an unhandled promise and the panel shows
   * nothing at all -- which is how a button comes to be pressed seven times: the person is
   * not being stubborn, they are being told nothing. A refusal is an answer and has to look
   * like one.
   */
  const attempt = useCallback(
    async <T,>(work: () => Promise<T>): Promise<T | null> => {
      try {
        return await work();
      } catch (error) {
        setBlocked(error instanceof Error ? error.message : String(error));
        setBusy(false);
        setStatus("");
        stopPollingRef.current?.();
        return null;
      }
    },
    [],
  );

  const stopPollingRef = useRef<(() => void) | null>(null);

  const absorb = useCallback(
    (state: { session: string | null; sessions: AgentSessionRef[] }) => {
      setCurrent(state.session);
      setSessions(state.sessions);
    },
    [],
  );

  const stopPolling = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);
  stopPollingRef.current = stopPolling;

  useEffect(() => {
    void attempt(async () => {
      const state = await agentSession(project);
      setAvailable(state.available);
      setRunning(state.running);
      absorb(state);
      return state;
    });
  }, [project, absorb, attempt]);

  const poll = useCallback(async () => {
    const answer = await attempt(() => agentPoll(project, offset.current));
    if (answer === null) return;
    offset.current = answer.offset;
    if (answer.context > 0) setContext(answer.context);
    if (answer.model) setModel(answer.model);
    absorb(answer);

    const touched = answer.events.map((event) => event.file).filter(Boolean);
    if (touched.length > 0) onTouch(touched);

    for (const event of answer.events) {
      if (event.kind === "blocked") setBlocked(event.text);
      else if (event.kind !== "done") setStatus(event.text);
    }
    setTranscript((previous) => [...previous, ...answer.events]);

    if (answer.events.some((event) => event.kind === "done")) {
      // The turn is over: stop asking, and read the graph again -- the agent has been
      // editing files, and everything on the canvas is a claim about older code.
      setBusy(false);
      setStatus("");
      stopPolling();
      onSettled();
      return;
    }
    timer.current = window.setTimeout(() => void poll(), POLL_MS);
  }, [project, onTouch, onSettled, stopPolling, absorb, attempt]);

  useEffect(() => stopPolling, [stopPolling]);

  /**
   * Read the opening of a session, and stop.
   *
   * The agent writes its `init` line a moment *after* the process exists, so `agent.start`
   * returning is not the same as the agent having said anything -- and until it does, the
   * panel has no model to draw the context ring against and nothing to show for the press.
   *
   * Bounded on purpose. Polling stops when the agent has announced itself or when the tries
   * run out; a connect that never says anything must stop asking rather than leave a timer
   * running for the rest of the session (P13: polled, with the caller keeping the offset).
   */
  const readOpening = useCallback(async () => {
    for (let tries = 0; tries < 12; tries += 1) {
      const answer = await attempt(() => agentPoll(project, offset.current));
      if (answer === null) return;
      offset.current = answer.offset;
      if (answer.model) setModel(answer.model);
      absorb(answer);
      setTranscript((previous) => [...previous, ...answer.events]);
      for (const event of answer.events) {
        if (event.kind === "blocked") setBlocked(event.text);
      }
      if (
        answer.events.some(
          (event) => event.kind === "ready" || event.kind === "blocked",
        )
      )
        return;
      await new Promise((resolve) => window.setTimeout(resolve, 400));
    }
  }, [project, absorb, attempt]);

  const begin = useCallback(
    async (resume?: string, fork = false) => {
      // Starting the agent spawns a process, which takes a second or two. Without a visible
      // in-flight state the button looks unpressed for that whole time, and a button that
      // looks unpressed gets pressed again -- five `agent.start` calls for one intention.
      if (connecting) return;
      setConnecting(true);
      setBlocked(null);
      try {
        const state = await attempt(() => agentStart(project, resume, fork));
        if (state === null) return;
        setRunning(state.running);
        setAvailable(state.available);
        absorb(state);
        // A different conversation is a different log: start reading it from the top, and
        // drop what the previous one said rather than letting two share a panel.
        offset.current = 0;
        setTranscript([]);
        setContext(0);
        setModel("");
        if (!state.ok) {
          setBlocked(state.detail);
          return;
        }
        await readOpening();
      } finally {
        setConnecting(false);
      }
    },
    [project, absorb, attempt, connecting, readOpening],
  );

  const forget = useCallback(
    async (identifier: string) => {
      const state = await attempt(() => agentForget(project, identifier));
      if (state === null) return;
      setRunning(state.running);
      absorb(state);
      // Forgetting the live conversation closes it, so what was on screen belongs to a
      // session that no longer exists.
      if (!state.running) {
        stopPollingRef.current?.();
        setTranscript([]);
        setStatus("");
        setContext(0);
        setModel("");
        offset.current = 0;
      }
    },
    [project, absorb, attempt],
  );

  const send = useCallback(
    async (text: string) => {
      const said = text.trim();
      if (!said || busy) return;
      setDraft("");
      setBlocked(null);
      setBusy(true);
      setStatus("thinking…");
      const answer = await attempt(() => agentSay(project, said));
      if (answer === null) return;
      if (!answer.ok) {
        setBusy(false);
        setStatus("");
        setBlocked(answer.detail);
        return;
      }
      void poll();
    },
    [project, busy, poll, attempt],
  );

  /** Attach files by naming them the way the agent already understands: `@path`. */
  async function attach() {
    const chosen = await attempt(() =>
      openDialog({ multiple: true, defaultPath: project }),
    );
    if (chosen === null) return;
    const files = Array.isArray(chosen) ? chosen : chosen ? [chosen] : [];
    if (files.length === 0) return;
    const root = project.endsWith("/") ? project : `${project}/`;
    const mentions = files
      .map((file) => (file.startsWith(root) ? file.slice(root.length) : file))
      .map((file) => `@${file}`)
      .join(" ");
    setDraft((previous) =>
      previous ? `${previous} ${mentions} ` : `${mentions} `,
    );
    field.current?.focus();
  }

  // Named `limit` and not `window`: shadowing the global would silently break the timers.
  const limit = windowFor(model);
  const filled = limit > 0 ? Math.min(1, context / limit) : 0;
  const circumference = 2 * Math.PI * 8;

  return (
    <div ref={shell} className={`bp-chat${open ? " is-open" : ""}`}>
      {open ? (
        <div className="bp-chat-panel">
          <div className="bp-chat-head">
            <span className="bp-cap" style={{ margin: 0 }}>
              Conversations
            </span>
            {/* Closing by hand as well as by looking away: a panel that only closes when
                attention moves cannot be put away while attention stays here. */}
            <button
              className="bp-icon"
              onClick={() => setOpen(false)}
              title="Close the conversation"
            >
              ✕
            </button>
          </div>

          <div className="bp-chat-sessions">
            <div className="bp-sess">
              {sessions.map((session) => (
                // A chip and its ✕ are two actions, so they are two buttons -- one nested
                // inside the other would make every close a switch as well.
                <span
                  key={session.id}
                  className={`bp-sess-chip${session.id === current ? " is-on" : ""}`}
                >
                  <button
                    className="bp-sess-open"
                    title={`${session.id} · ${session.at}`}
                    disabled={connecting}
                    onClick={() => void begin(session.id)}
                  >
                    {session.label}
                    <span className="bp-sess-id">{session.id.slice(0, 8)}</span>
                  </button>
                  <button
                    className="bp-sess-shut"
                    title="Forget this conversation — the agent keeps its own transcript"
                    disabled={connecting}
                    onClick={() => void forget(session.id)}
                  >
                    ✕
                  </button>
                </span>
              ))}
              <button
                className="bp-sess-chip bp-sess-act"
                disabled={connecting}
                onClick={() => void begin()}
              >
                + New
              </button>
              {/* A fork keeps the original branch: "do that again differently" must not
                  mean "lose the first attempt". */}
              <button
                className="bp-sess-chip bp-sess-act"
                disabled={!current || connecting}
                onClick={() => current && void begin(current, true)}
              >
                ⑂ Fork
              </button>
            </div>
          </div>

          <div className="bp-chat-log">
            {transcript.map((event, index) => (
              <div key={index} className={`bp-chat-line is-${event.kind}`}>
                <span className="bp-chat-kind">{event.kind}</span>
                <span>{event.text}</span>
              </div>
            ))}
            {transcript.length === 0 ? (
              <div className="bp-empty">
                Nothing said in this conversation yet. What the agent does shows
                on the canvas.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {blocked ? (
        <Notice
          tone="blocked"
          label="blocked"
          text={blocked}
          onClose={() => setBlocked(null)}
        />
      ) : null}

      {status ? (
        <div className="bp-chat-status">
          <span className="bp-livedot" />
          {status}
        </div>
      ) : null}

      <div className="bp-chat-box">
        {available === false ? (
          <div className="bp-chat-row">
            <div className="bp-chat-absent">
              No agent on this machine — install Claude Code.
            </div>
            <Toggle open={open} onToggle={() => setOpen(!open)} />
          </div>
        ) : !running ? (
          // Past conversations are worth looking at before there is a live one, so the
          // transcript stays reachable whether or not anything is connected.
          <div className="bp-chat-row">
            <button
              className="bp-chat-connect"
              disabled={connecting}
              onClick={() => void begin()}
            >
              {connecting ? "Connecting…" : "Connect Claude"}
            </button>
            <Toggle open={open} onToggle={() => setOpen(!open)} />
          </div>
        ) : (
          <>
            <textarea
              ref={field}
              className="bp-chat-field"
              // Typing is the moment the conversation becomes relevant, so focusing the
              // field is what opens it -- rather than a separate press that means the same.
              onFocus={() => setOpen(true)}
              value={draft}
              rows={1}
              placeholder={busy ? "working…" : "ask for a change"}
              spellCheck={false}
              disabled={busy}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send(draft);
                }
              }}
            />

            <div className="bp-chat-tools">
              <button
                className="bp-icon"
                onClick={() => void attach()}
                title="Attach files"
              >
                ＋
              </button>

              {/* The ring fills against the window of the model the agent said it is using;
                  with an unrecognised model there is no fraction to draw, and the count stands
                  alone. Clicking asks the agent to compact -- its own command, not ours. */}
              <button
                className={`bp-ring${filled > 0.7 ? " is-full" : ""}`}
                title={
                  limit > 0
                    ? `${context.toLocaleString()} of ${
                        limit >= 1_000_000
                          ? `${limit / 1_000_000}M`
                          : `${limit / 1000}k`
                      } tokens · ${model} · compact`
                    : `${context.toLocaleString()} tokens carried · window unknown${model ? ` for ${model}` : ""} · compact`
                }
                onClick={() => void send("/compact")}
                disabled={context === 0 || busy}
              >
                <svg viewBox="0 0 20 20" width="18" height="18">
                  <circle cx="10" cy="10" r="8" className="bp-ring-track" />
                  <circle
                    cx="10"
                    cy="10"
                    r="8"
                    className="bp-ring-fill"
                    strokeDasharray={`${filled * circumference} ${circumference}`}
                  />
                </svg>
              </button>

              <span className="bp-chat-count">
                {context > 0 ? `${Math.round(context / 1000)}k` : ""}
              </span>

              <Toggle open={open} onToggle={() => setOpen(!open)} />

              <button
                className="bp-send"
                onClick={() => void send(draft)}
                disabled={busy || !draft.trim()}
                title="Send"
              >
                ↑
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
