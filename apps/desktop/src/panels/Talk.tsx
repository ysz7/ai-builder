/**
 * The conversation, on the node (P17.3).
 *
 * The chat panel pointed at a different answerer: what changes is **who is speaking**, not
 * what a conversation looks like. Which is also why this appears in the node's own pane and
 * adds nothing to the graph — a conversation is an action on a node, never a node of its own
 * (Q18), and a node the canvas drew rather than the code declared would be the second source
 * of truth I-1 forbids.
 *
 * **Which nodes get it comes from the registry**, never from a list of kind names kept here:
 * a kind opts in by naming a way in, and a kind that has not shows no button at all rather
 * than one that appears to work (P17.2).
 *
 * **Nothing is pushed** (P13). Opening spawns the project's interpreter and returns once the
 * project says it is listening; answers are polled with an offset this side keeps, and the
 * polling stops when there is nothing more coming. **Nothing is remembered here**: the
 * project holds the conversation — its checkpointer, its `thread_id` — and a history kept on
 * this side would behave differently on the canvas than it does in production (Q19).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { talkClose, talkOpen, talkPoll, talkSay } from "../core/client";
import type { TalkEvent } from "../core/types";
import { Notice } from "./Notice";

const POLL_MS = 500;

type Props = { project: string; node: string; onAnswered: () => void };

/** Is this event a line of the conversation? `ready` is the panel's status, not a line. */
function worthShowing(event: TalkEvent): boolean {
  return ["asked", "answer", "failed"].includes(event.type);
}

export function Talk({ project, node, onAnswered }: Props) {
  const [lines, setLines] = useState<TalkEvent[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [draft, setDraft] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  const offset = useRef(0);
  const timer = useRef<number | null>(null);
  const waiting = useRef(false);
  const tail = useRef<HTMLDivElement | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const read = useCallback(async () => {
    try {
      const answer = await talkPoll(project, node, offset.current);
      offset.current = answer.offset;
      const shown = answer.events.filter(worthShowing);
      if (shown.length > 0) setLines((previous) => [...previous, ...shown]);
      if (shown.some((event) => ["answer", "failed"].includes(event.type))) {
        waiting.current = false;
        // Something was said, so the node has evidence it did not have before (P17.4).
        // The graph is asked again rather than left showing what was true before.
        onAnswered();
      }
      if (!answer.running) {
        setOpen(false);
        stopPolling();
        return;
      }
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
      stopPolling();
      return;
    }
    // Asked again only while an answer is outstanding. A conversation sitting idle costs
    // nothing, which is what makes polling honest rather than a push loop with extra steps.
    if (waiting.current) timer.current = window.setTimeout(() => void read(), POLL_MS);
  }, [project, node, onAnswered, stopPolling]);

  // A different node is a different conversation, and neither one's transcript may land in
  // the other's panel. The one that was open stays open in the core — it is the project's
  // process, and closing it because somebody clicked elsewhere would throw away its memory.
  useEffect(() => {
    offset.current = 0;
    waiting.current = false;
    setLines([]);
    setOpen(false);
    setFailed(null);
    return stopPolling;
  }, [project, node, stopPolling]);

  useEffect(() => {
    if (tail.current) tail.current.scrollTop = tail.current.scrollHeight;
  }, [lines]);

  async function act(label: string, run: () => Promise<void>) {
    setBusy(label);
    setFailed(null);
    try {
      await run();
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  /**
   * Ask, opening the conversation first if this is the first question.
   *
   * **The surface is open from the start; the process is not** (P11). The card shows a box
   * to type in because a chat with a button in front of it is a chat nobody has yet, and a
   * canvas that spawned the project's interpreter for every conversable node the moment it
   * drew one would be starting things nobody asked for -- a process per agent, held open
   * for a question that may never come. Typing is not asking; pressing Ask is, and that is
   * the gesture the spawn hangs off.
   */
  const send = () =>
    void act("Ask", async () => {
      const text = draft.trim();
      if (!text) return;
      if (!open) {
        const started = await talkOpen(project, node);
        if (!started.ok) {
          setFailed(started.detail);
          return;
        }
        setOpen(true);
        offset.current = 0;
        await read();
      }
      const answer = await talkSay(project, node, text);
      if (!answer.ok) {
        setFailed(answer.detail);
        return;
      }
      setDraft("");
      waiting.current = true;
      void read();
    });

  const shut = () =>
    void act("Close", async () => {
      stopPolling();
      await talkClose(project, node);
      setOpen(false);
      // The conversation is over, so the evidence it carried is over with it: a node goes
      // back to unproven rather than keeping a claim nobody can repeat (P17.4).
      onAnswered();
    });

  return (
    <>
      {lines.length > 0 ? (
        <div className="bp-talk-log" ref={tail}>
          {lines.map((event, index) => (
            <div
              className={`bp-turn${event.type === "asked" ? " is-you" : ""}`}
              key={`${index}-${event.type}`}
            >
              <div className="bp-turn-text">
                {event.type === "failed"
                  ? event.detail || "the node broke on that question"
                  : event.text}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* The reference's composer: a box to type in with its actions on a strip inside it,
          rather than a field and a row of buttons under the card. There is no `Talk to it`
          in front of it -- see `send` for why the *surface* being open does not mean a
          process is (P11). */}
      <div className="bp-compose">
        <textarea
          className="bp-compose-text"
          value={draft}
          rows={3}
          placeholder="Ask it something"
          spellCheck={false}
          disabled={busy !== ""}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // Enter asks; Shift+Enter is a newline, because a question can be a paragraph.
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <div className="bp-compose-bar">
          {/* What the process is doing, said where the reference puts its word count. It is
              the only place `open` is visible now, and it is a report rather than a switch:
              the button that opened it is gone, and closing lives beside it. */}
          <span className="bp-compose-state">
            {busy !== "" ? "…" : open ? "listening" : "not started"}
          </span>
          {open ? (
            <button
              className="bp-compose-icon"
              title="Close the conversation"
              aria-label="Close the conversation"
              disabled={busy !== ""}
              onClick={shut}
            >
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <path
                  d="M6 6l12 12M18 6L6 18"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          ) : null}
          <button
            className="bp-compose-send"
            title="Ask"
            aria-label="Ask"
            disabled={busy !== "" || draft.trim() === ""}
            onClick={send}
          >
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              <path
                d="M5 12h13m0 0-5-5m5 5-5 5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </div>

      {failed ? (
        <Notice
          tone="refused"
          text={failed}
          onClose={() => setFailed(null)}
        />
      ) : null}
    </>
  );
}
