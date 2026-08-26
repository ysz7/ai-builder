/**
 * One step of a turn: what the agent thought, or a tool it called and what came back.
 *
 * Folded by default and openable, because the two questions are different. *What is it
 * doing?* is answered by one line — `running pytest -q` — and that is what a person watching
 * wants. *What exactly did it do?* needs the arguments and the answer, and wanting that is
 * the exception, so it costs a click rather than the whole panel's height.
 *
 * A result is shown **against the call it answers**, paired by the agent's own
 * `tool_use_id` — after, in a flat list, is not the same as *for*, and with two tools in
 * flight it is not even true.
 */

import { useState } from "react";

import type { AgentEvent } from "../core/client";

type Props = { event: AgentEvent; answer: AgentEvent | null };

export function Step({ event, answer }: Props) {
  const [open, setOpen] = useState(false);
  const more = Boolean(event.detail || answer?.text);

  if (event.kind === "thinking") {
    return (
      <div className="bp-step is-thinking">
        <button className="bp-step-line" onClick={() => setOpen(!open)}>
          <span className="bp-step-mark">{open ? "▾" : "▸"}</span>
          <span className="bp-step-text">thought</span>
        </button>
        {open ? <div className="bp-step-body">{event.text}</div> : null}
      </div>
    );
  }

  return (
    <div
      className={`bp-step${answer?.kind === "blocked" ? " is-blocked" : ""}`}
    >
      <button className="bp-step-line" onClick={() => more && setOpen(!open)}>
        <span className="bp-step-mark">{more ? (open ? "▾" : "▸") : "·"}</span>
        <span className="bp-step-text">{event.text}</span>
        {/* A refusal is named on the folded line: there is no permission round-trip to
            intercept, so a denied tool must be visible without being opened (Q17). */}
        {answer?.kind === "blocked" ? (
          <span className="bp-step-no">refused</span>
        ) : null}
      </button>

      {open ? (
        <div className="bp-step-body">
          {event.detail ? (
            <div className="bp-step-in">{event.detail}</div>
          ) : null}
          {answer?.text ? (
            <div className="bp-step-out">{answer.text}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
