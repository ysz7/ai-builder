/**
 * Talking to the agent you built — which is **not** the agent that built it.
 *
 * Two conversations now exist in this window and confusing them would be expensive: the
 * builder chat writes Python into the project, and this one calls `run(message)` and shows
 * what came back. They are kept apart the same way `run.py` keeps them apart in the core —
 * one writes code, the other calls an export — and this panel exists rather than a block in
 * the node panel so that the separation is visible rather than merely true.
 *
 * ## Every turn is a fresh process, and the panel says so
 *
 * The core imports no user code, so each call is its own interpreter. An agent that
 * remembers anything between turns remembers it because **its own code** stores it — the
 * lesson `rag/store.py` already learned the hard way, where an index that lived for the
 * length of one process could be filled or queried but never both.
 *
 * So this deliberately does **not** keep a conversation and feed it back as history. That
 * would make Framestack the thing that remembers, and the agent would then behave one way
 * here and another way when the person runs it from their own terminal — which is invariant
 * 6 broken in the least visible way there is. The notice at the top of the panel is not a
 * disclaimer; it is the one thing a person has to know to read what they are seeing.
 *
 * What is on screen is what happened while the panel was open. Nothing is stored, and
 * closing it loses the transcript: a transcript worth keeping is one the agent's own code
 * would have kept.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { runRead, runStart, runStop } from "../core/client";
import type { GraphNode } from "../core/types";
import { Flyout } from "../shell/Flyout";
import { Markdown } from "../code/markdown";
import { Copy } from "./Copy";

/** How often a turn is polled while it runs. Output is polled, never pushed (P13). */
const BEAT = 250;

type Turn = {
  message: string;
  /** What `run` returned. `null` while the call is still going. */
  reply: string | null;
  /** The child's traceback, verbatim, when it raised. */
  error: string;
  /** What the agent printed on its way. Its own words, unedited. */
  output: string;
  at: string;
};

export function AgentChat({
  project,
  node,
  onClose,
  onSettings,
}: {
  project: string;
  node: GraphNode;
  onClose: () => void;
  /** Back to the node's settings, verdict and files. The other half of the split. */
  onSettings: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [refused, setRefused] = useState("");
  const foot = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    foot.current?.scrollIntoView({ block: "end" });
  }, [turns, running]);

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message || running) return;

    setDraft("");
    setRefused("");
    setRunning(true);
    setTurns((held) => [
      ...held,
      { message, reply: null, error: "", output: "", at: new Date().toISOString() },
    ]);

    const settle = (reply: string | null, error: string, output: string) =>
      setTurns((held) =>
        held.map((turn, index) =>
          index === held.length - 1 ? { ...turn, reply, error, output } : turn,
        ),
      );

    try {
      const started = await runStart(project, node.id, "run", { message });
      if (!started.ok) {
        // A call that never started still answered, with the reason. It belongs against the
        // message it failed for, not in a corner of the window.
        settle(null, started.detail, "");
        setRunning(false);
        return;
      }

      let offset = 0;
      let printed = "";
      for (;;) {
        const answer = await runRead(project, node.id, offset);
        offset = answer.offset;
        if (answer.output) {
          printed += answer.output;
          settle(null, "", printed);
        }
        if (!answer.running) {
          const outcome = answer.outcome;
          if (outcome && outcome.ok) {
            // A string is the ordinary case, because `run` returns one. Anything else is
            // shown as what it is rather than coerced: the return type is the user's.
            settle(
              typeof outcome.value === "string"
                ? outcome.value
                : JSON.stringify(outcome.value, null, 2),
              "",
              printed,
            );
          } else {
            settle(null, outcome?.error || answer.detail, printed);
          }
          setRunning(false);
          return;
        }
        await new Promise((wake) => setTimeout(wake, BEAT));
      }
    } catch (error) {
      settle(null, error instanceof Error ? error.message : String(error), "");
      setRunning(false);
    }
  }, [draft, running, project, node.id]);

  return (
    // On the right, where the builder's own chat is. It is the same act — saying something
    // and reading an answer — and a conversation that opened on the opposite edge from the
    // other conversation would be two applications in one window.
    <Flyout title={node.name} side="right" onClose={onClose}>
      <div className="bp-talk">
        {/* The one thing a person has to know to read this panel correctly, said where they
            will read it rather than in documentation they will not. */}
        <div className="bp-talk-notice">
          Each message is a separate process. This agent remembers nothing between turns
          unless its own code stores it.
          <button className="bp-talk-settings" onClick={onSettings}>
            Settings, files and verdict →
          </button>
        </div>

        {node.missing.length > 0 ? (
          <div className="bp-node-why">{node.reason}</div>
        ) : (
          <div className="bp-talk-roll">
            {turns.length === 0 ? (
              <div className="bp-talk-empty">
                Calls <code>run(message)</code> in <code>{node.path}/</code>.
              </div>
            ) : null}

            {turns.map((turn, index) => (
              <div className="bp-talk-turn" key={`${turn.at}-${index}`}>
                {/* The same shapes the builder's own chat uses, because it is the same
                    reading: a person's line as a bubble on the right, an answer as text
                    across the panel. What the person typed is shown **as typed** —
                    rendering their asterisks would be editing what they said. */}
                <div className="bp-turn is-you">
                  <div className="bp-turn-text">{turn.message}</div>
                </div>

                {turn.output ? (
                  <pre className="bp-talk-printed">{turn.output}</pre>
                ) : null}

                {turn.reply !== null ? (
                  // Formatted, because a model answers in Markdown and a panel that showed
                  // the asterisks would be the only place in this application that did.
                  <div className="bp-turn is-says">
                    <div className="bp-turn-text">
                      <Markdown source={turn.reply} />
                    </div>
                  </div>
                ) : turn.error ? (
                  /* Verbatim, never repaired into something plausible: it is the way out of
                     the state the code is actually in — which is also why it is the one
                     thing here somebody needs to take somewhere else. A traceback is read in
                     an editor, pasted to a colleague, given back to the chat; selectable and
                     with a button, because a stack trace nobody can copy is evidence held
                     hostage by the panel showing it. */
                  <div className="bp-talk-wrong">
                    <pre className="bp-talk-broke">{turn.error}</pre>
                    <Copy text={turn.error} what="this traceback" />
                  </div>
                ) : (
                  /* Where the work is happening, in the transcript, exactly as the builder's
                     own chat says it. */
                  <div className="bp-turn is-working">
                    <span className="bp-livedot" />
                    <span className="bp-step-text">running…</span>
                  </div>
                )}
              </div>
            ))}
            <div ref={foot} />
          </div>
        )}

        {refused ? <div className="bp-node-why">{refused}</div> : null}

        {/* The field the builder's own chat uses, with none of the row under it: there is no
            attachment, no mode and no context here, and drawing those controls dead would be
            promising four things this panel cannot do. */}
        <div className="bp-talk-ask">
          <textarea
            className="bp-chat-field"
            rows={1}
            placeholder="Say something to it"
            value={draft}
            disabled={node.missing.length > 0}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          {running ? (
            <button
              className="bp-send is-stop"
              onClick={() => void runStop(project, node.id)}
              title="End this turn"
              aria-label="Stop"
            >
              ■
            </button>
          ) : (
            <button
              className="bp-send"
              disabled={!draft.trim() || node.missing.length > 0}
              onClick={() => void send()}
              title="Send"
              aria-label="Send"
            >
              ↑
            </button>
          )}
        </div>
      </div>
    </Flyout>
  );
}
