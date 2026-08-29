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
 * Two surfaces, one file: the rail's flyout, which is the whole graph, and the inspector's
 * section, which is one node. They say the same things about a different number of nodes.
 */

import { useState } from "react";

import type { GraphRead, Observation } from "../core/types";

/**
 * One node's evidence, named rather than described.
 *
 * `by` is the identifier the core gained for this (P18.3): the test that entered the node,
 * as data. The sentence beside it stays -- it is the right answer wherever there is room for
 * one -- but nothing here parses it to find the name.
 */
export function EvidenceChips({ observation }: { observation: Observation | null }) {
  if (!observation) return null;
  return (
    <div className="bp-chips">
      <span className={`bp-chip${observation.passed ? " is-ok" : " is-bad"}`}>
        {observation.passed ? "proven by" : "failed in"}{" "}
        {observation.by || observation.check}
      </span>
      {observation.by ? <span className="bp-chip is-quiet">{observation.check}</span> : null}
    </div>
  );
}

/**
 * The reason, and a way to take it somewhere else.
 *
 * The reason is often the only thing that explains a red node -- an import that failed, a
 * check that could not run -- and the next thing anybody does with it is paste it: to the
 * agent, into a search, into a message to a colleague. Retyping a `ModuleNotFoundError` out
 * of a panel is not work a person should be doing.
 *
 * It copies **what is shown and nothing more**. No node id, no kind, no timestamp bolted on:
 * what the reader saw is what lands on their clipboard, and anything else would be this
 * panel deciding what their message should say.
 */
function Why({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <p className="bp-evidence-why">
      <button
        className="bp-why-copy"
        title="Copy this reason"
        onClick={() => {
          // A clipboard that refuses is a fact worth showing: silence here reads as a copy
          // that worked, and the person finds out it did not when they paste nothing.
          navigator.clipboard
            .writeText(text)
            .then(() => setCopied(true))
            .catch(() => setCopied(false));
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "copied" : "copy"}
      </button>
      {text}
    </p>
  );
}

/** The evidence for one node: what proved it, or what could not be asked and why. */
export function NodeEvidence({ graph, node }: { graph: GraphRead; node: string }) {
  const observation = graph.observations[node] ?? null;
  const skipped = graph.skipped[node];
  const verdict = graph.verdicts[node] ?? "unproven";

  return (
    <div className="bp-evidence">
      <div className="bp-evidence-row">
        <span className={`bp-sev is-${verdict}`}>{verdict}</span>
        <EvidenceChips observation={observation} />
      </div>
      <Why
        text={
          observation?.detail ??
          skipped ??
          "nothing has been run against this node yet — grey means unasked, not broken"
        }
      />
      {/* A check that *could not run* is a different fact from one that ran and failed, and
          it is the one most easily read as "fine". It gets its own line. */}
      {skipped && observation ? (
        <p className="bp-evidence-why">skipped: {skipped}</p>
      ) : null}
    </div>
  );
}

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
