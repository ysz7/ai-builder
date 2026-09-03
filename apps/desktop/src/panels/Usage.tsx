/**
 * What the last run cost, step by step.
 *
 * **Tokens are measured; dollars are arithmetic.** The core stores what a provider answered —
 * a model, an input count, an output count — and prices it on read from a table shipped with
 * this build. A model the table does not have shows its tokens and **no** dollar figure, and
 * the sentence under the total says which model that was. A number nobody can re-derive is
 * the same defect as a green node nobody ran a test for, in the currency people care about.
 *
 * **It measures, it does not instrument.** Nothing was added to the project to produce this:
 * the counting happens in the child process `Run` already spawns, in a driver written into
 * `.framestack/` and deleted with it. Delete Framestack and the project is what it was.
 *
 * Langfuse is a **link and never a fetch**. Where a project's `.env` says it sends traces,
 * there is a way to go and read them where they live; nothing here pulls them in, and nothing
 * falls back to them.
 */

import { useCallback, useEffect, useState } from "react";

import { usageRead } from "../core/client";
import type { UsageResult } from "../core/types";

/** Thousands, the way a person reads a token count. */
export function tokens(count: number): string {
  return count.toLocaleString("en-US");
}

/**
 * Dollars, or nothing at all.
 *
 * Four decimal places because a single call is fractions of a cent and `$0.00` beside a real
 * call would read as free. `null` renders as an em dash: an absence a person can see.
 */
export function dollars(cost: number | null): string {
  if (cost === null) return "—";
  return `$${cost.toFixed(cost < 0.01 ? 4 : 3)}`;
}

export function Usage({ project, node }: { project: string; node: string }) {
  const [state, setState] = useState<UsageResult | null>(null);

  const read = useCallback(async () => {
    try {
      setState(await usageRead(project, node));
    } catch {
      // A ledger that cannot be read is history missing, not a panel broken. The rest of
      // the node is still worth showing.
    }
  }, [project, node]);

  useEffect(() => {
    setState(null);
    void read();
  }, [read]);

  if (!state || state.calls.length === 0) return null;

  return (
    <div className="bp-run">
      <span className="bp-node-label">
        Last run · {state.calls.length} step{state.calls.length === 1 ? "" : "s"}
      </span>

      <div className="bp-routes">
        {state.calls.map((call, index) => (
          <div className="bp-route" key={`${call.at}-${index}`} title={call.model}>
            <span className="bp-route-verb">step {index + 1}</span>
            <span className="bp-route-path">
              {tokens(call.input)} in · {tokens(call.output)} out
            </span>
            <span className="bp-route-to">{dollars(call.cost)}</span>
          </div>
        ))}
      </div>

      <div className="bp-usage-total">
        <span>{tokens(state.tokens)} tok</span>
        <span>{dollars(state.cost)}</span>
      </div>

      {/* Said plainly rather than papered over with a zero: the tokens above are real and
          the price is the thing this build does not have. */}
      {state.unpriced.length > 0 ? (
        <div className="bp-run-note">
          no price for {state.unpriced.join(", ")} — the tokens are measured, the dollars are
          not guessed
        </div>
      ) : null}

      {state.langfuse ? (
        <a
          className="bp-node-open"
          href={state.langfuse}
          target="_blank"
          rel="noreferrer noopener"
        >
          Open the trace in Langfuse
        </a>
      ) : null}
    </div>
  );
}
