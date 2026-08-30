/**
 * What was proven, and by which run.
 *
 * **This is where green comes from** (I-5). A node is green only if it parses *and* passes an
 * observable check, and the static gate cannot produce that on its own — so until somebody
 * presses Observe, every node is `unproven`, which is deliberately not the same as "fine". A
 * check that could not run says so and leaves the node unproven; an absent observation is
 * never read as a passing one.
 *
 * It has no run button of its own any more. Observing is the most emphatic verb in this
 * application and it belongs in the control cluster, where the reference puts `Publish`
 * (P18.1) -- a second copy down here would be a second way to start somebody's test suite,
 * and the whole point of P11 is that there is exactly one, pressed on purpose.
 *
 * **One surface, not two.** It used to draw a section in the inspector as well, and that
 * copy is gone: a person looking for what a run proved goes to `Problems`, which lists every
 * failing and unproven node with its reason, or here, which is the whole graph at once. The
 * node's own card carries the verdict as its mark. Three copies of one fact made the
 * inspector long and told nobody anything a fourth time.
 */

import type { GraphRead } from "../core/types";

/** The whole graph's evidence, as the rail's flyout draws it. */
export function Evidence({
  graph,
  observed,
  onSelect,
}: {
  graph: GraphRead;
  observed: boolean;
  onSelect: (id: string) => void;
}) {
  const verdicts = Object.entries(graph.verdicts);
  const tally = (which: string) =>
    verdicts.filter(([, verdict]) => verdict === which).length;

  return (
    <div className="bp-observe">
      <div className="bp-observe-bar">
        <span className="bp-observe-tally">
          <span className="bp-sev is-green">{tally("green")} green</span>
          <span className="bp-sev is-broken">{tally("broken")} broken</span>
          <span className="bp-sev is-unproven">{tally("unproven")} unproven</span>
        </span>
      </div>

      {!observed ? (
        // The sentence a person needs on the day they open a project and find it grey.
        // Unproven is not broken and never was; what it says is that nobody has asked yet,
        // and asking is one press away. It goes back to unproven on every reopen because
        // observing runs somebody's tests, and a window coming back must never do that
        // (P11) -- so this says so rather than leaving it looking like a regression.
        <div className="bp-observe-note">
          nothing has been run yet — press Observe, up in the bar
        </div>
      ) : null}

      {verdicts.map(([id, verdict]) => {
        const observation = graph.observations[id];
        const skipped = graph.skipped[id];
        return (
          <button key={id} className="bp-problem" onClick={() => onSelect(id)}>
            <span className={`bp-sev is-${verdict}`}>{verdict}</span>
            <span className="bp-problem-msg">
              {observation?.detail ?? skipped ?? "no check has run against this yet"}
            </span>
            <span className="bp-problem-addr">
              {observation?.by || observation?.check || id}
            </span>
          </button>
        );
      })}

      {verdicts.length === 0 ? (
        <div className="bp-empty">Nothing on the graph to observe yet.</div>
      ) : null}
    </div>
  );
}
