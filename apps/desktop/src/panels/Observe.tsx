/**
 * The evidence: what ran, what passed, and what nothing has run through.
 *
 * **This is where green comes from** (I-5). A node is green only if it parses *and* passes an
 * observable check, and the static gate cannot produce that on its own — so until somebody
 * presses the button here, every node is `unproven`, which is deliberately not the same as
 * "fine". A check that could not run says so and leaves the node unproven; an absent
 * observation is never read as a passing one.
 *
 * Running is a press and never a side effect (P11): it hands the project's own test suite to
 * the project's own interpreter, which imports and executes somebody's code. Drawing a graph
 * must never do that.
 */

import type { GraphRead } from "../core/types";

type Props = {
  graph: GraphRead;
  observed: boolean;
  busy: boolean;
  onRun: () => void;
  onSelect: (id: string) => void;
};

export function Observe({ graph, observed, busy, onRun, onSelect }: Props) {
  const verdicts = Object.entries(graph.verdicts);
  const tally = (which: string) => verdicts.filter(([, verdict]) => verdict === which).length;

  return (
    <div className="bp-observe">
      <div className="bp-observe-bar">
        <button className="bp-btn bp-btn-go" disabled={busy} onClick={onRun}>
          {busy ? "Running…" : "Run the project's tests"}
        </button>
        <span className="bp-observe-tally">
          <span className="bp-sev is-green">{tally("green")} green</span>
          <span className="bp-sev is-broken">{tally("broken")} broken</span>
          <span className="bp-sev is-unproven">{tally("unproven")} unproven</span>
        </span>
        {!observed ? (
          <span className="bp-observe-note">
            nothing has been run — every node is unproven until it has been
          </span>
        ) : null}
      </div>

      {verdicts.map(([id, verdict]) => {
        const observation = graph.observations[id];
        const skipped = graph.skipped[id];
        return (
          <button key={id} className="bp-problem" onClick={() => onSelect(id)}>
            <span className={`bp-sev is-${verdict}`}>{verdict}</span>
            <span className="bp-problem-msg">
              {observation?.detail ?? skipped ?? "no check has run"}
            </span>
            <span className="bp-problem-addr">{observation?.check ?? id}</span>
          </button>
        );
      })}

      {verdicts.length === 0 ? (
        <div className="bp-empty">Nothing on the graph to observe yet.</div>
      ) : null}
    </div>
  );
}
