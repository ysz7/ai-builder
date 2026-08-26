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

  const start = () =>
    void act("Open", async () => {
      const answer = await talkOpen(project, node);
      if (!answer.ok) {
        setFailed(answer.detail);
        return;
      }
      setOpen(true);
      offset.current = 0;
      // Read once, so the reason the project gave for being ready is not lost.
      await read();
    });

  const send = () =>
    void act("Ask", async () => {
      const text = draft.trim();
      if (!text) return;
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
      <div className="bp-cap">
        Talk{" "}
        <span className="bp-cap-n">{open ? "listening" : "not open"}</span>
      </div>

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

      <div className="bp-acts">
        {open ? (
          <>
            <input
              className="bp-field"
              value={draft}
              placeholder="Ask it something"
              spellCheck={false}
              disabled={busy !== ""}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") send();
              }}
            />
            <button className="bp-btn" disabled={busy !== ""} onClick={send}>
              {busy === "Ask" ? "…" : "Ask"}
            </button>
            <button className="bp-btn" disabled={busy !== ""} onClick={shut}>
              {busy === "Close" ? "…" : "Close"}
            </button>
          </>
        ) : (
          <button className="bp-btn" disabled={busy !== ""} onClick={start}>
            {busy === "Open" ? "…" : "Talk to it"}
          </button>
        )}
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
