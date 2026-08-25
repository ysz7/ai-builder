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

import { agentPoll, agentSay, agentSession, agentStart } from "../core/client";
import type { AgentEvent, AgentSessionRef } from "../core/client";

const POLL_MS = 700;

/**
 * What the ring is drawn against.
 *
 * **An assumption, and it is labelled as one.** The stream reports how many tokens a turn
 * carried and never what the window is, so a percentage here is ours rather than the agent's.
 * The raw count is always shown beside it, so the number a person acts on is the real one.
 */
const ASSUMED_WINDOW = 200_000;

type Props = {
  project: string;
  onTouch: (files: string[]) => void;
  onSettled: () => void;
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

export function Chat({ project, onTouch, onSettled }: Props) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AgentSessionRef[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [blocked, setBlocked] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<AgentEvent[]>([]);
  const [context, setContext] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const offset = useRef(0);
  const timer = useRef<number | null>(null);
  const field = useRef<HTMLTextAreaElement | null>(null);

  /**
   * Every call to the core, with its failure made visible.
   *
   * Without this a rejected request disappears into an unhandled promise and the panel shows
   * nothing at all -- which is how a button comes to be pressed seven times: the person is
   * not being stubborn, they are being told nothing. A refusal is an answer and has to look
   * like one.
   */
  const attempt = useCallback(async <T,>(work: () => Promise<T>): Promise<T | null> => {
    try {
      return await work();
    } catch (error) {
      setBlocked(error instanceof Error ? error.message : String(error));
      setBusy(false);
      setStatus("");
      stopPollingRef.current?.();
      return null;
    }
  }, []);

  const stopPollingRef = useRef<(() => void) | null>(null);

  const absorb = useCallback((state: { session: string | null; sessions: AgentSessionRef[] }) => {
    setCurrent(state.session);
    setSessions(state.sessions);
  }, []);

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

  const begin = useCallback(
    async (resume?: string, fork = false) => {
      setBlocked(null);
      const state = await attempt(() => agentStart(project, resume, fork));
      if (state === null) return;
      setRunning(state.running);
      setAvailable(state.available);
      absorb(state);
      // A different conversation is a different log: start reading it from the top, and drop
      // what the previous one said rather than letting two of them share a panel.
      offset.current = 0;
      setTranscript([]);
      setContext(0);
      if (!state.ok) setBlocked(state.detail);
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
    const chosen = await attempt(() => openDialog({ multiple: true, defaultPath: project }));
    if (chosen === null) return;
    const files = Array.isArray(chosen) ? chosen : chosen ? [chosen] : [];
    if (files.length === 0) return;
    const root = project.endsWith("/") ? project : `${project}/`;
    const mentions = files
      .map((file) => (file.startsWith(root) ? file.slice(root.length) : file))
      .map((file) => `@${file}`)
      .join(" ");
    setDraft((previous) => (previous ? `${previous} ${mentions} ` : `${mentions} `));
    field.current?.focus();
  }

  const filled = Math.min(1, context / ASSUMED_WINDOW);
  const circumference = 2 * Math.PI * 8;

  return (
    <div className={`bp-chat${open ? " is-open" : ""}`}>
      {open ? (
        <div className="bp-chat-panel">
          <div className="bp-chat-sessions">
            <span className="bp-cap" style={{ margin: 0 }}>
              Conversations
            </span>
            <div className="bp-sess">
              {sessions.map((session) => (
                <button
                  key={session.id}
                  className={`bp-sess-chip${session.id === current ? " is-on" : ""}`}
                  title={`${session.id} · ${session.at}`}
                  onClick={() => void begin(session.id)}
                >
                  {session.label}
                  <span className="bp-sess-id">{session.id.slice(0, 8)}</span>
                </button>
              ))}
              <button className="bp-sess-chip" onClick={() => void begin()}>
                + New
              </button>
              {/* A fork keeps the original branch: "do that again differently" must not
                  mean "lose the first attempt". */}
              <button
                className="bp-sess-chip"
                disabled={!current}
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
                Nothing said in this conversation yet. What the agent does shows on the canvas.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {blocked ? (
        <div className="bp-chat-blocked">
          <span className="bp-chat-kind">blocked</span>
          {blocked}
        </div>
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
            <div className="bp-chat-absent">No agent on this machine — install Claude Code.</div>
            <Toggle open={open} onToggle={() => setOpen(!open)} />
          </div>
        ) : !running ? (
          // Past conversations are worth looking at before there is a live one, so the
          // transcript stays reachable whether or not anything is connected.
          <div className="bp-chat-row">
            <button className="bp-chat-connect" onClick={() => void begin()}>
              Connect Claude
            </button>
            <Toggle open={open} onToggle={() => setOpen(!open)} />
          </div>
        ) : (
          <>
            <textarea
              ref={field}
              className="bp-chat-field"
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
              <button className="bp-icon" onClick={() => void attach()} title="Attach files">
                ＋
              </button>

              {/* The ring is drawn against an assumed window, so the count is always beside
                  it. Clicking asks the agent to compact -- its own command, not ours. */}
              <button
                className={`bp-ring${filled > 0.7 ? " is-full" : ""}`}
                title={`${context.toLocaleString()} tokens carried · assuming a ${ASSUMED_WINDOW.toLocaleString()} window · compact`}
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

              <span className="bp-chat-count">{context > 0 ? `${Math.round(context / 1000)}k` : ""}</span>

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
