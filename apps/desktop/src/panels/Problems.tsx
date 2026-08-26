/**
 * Every addressed thing that is wrong. Unreal's Compiler Results.
 *
 * It is also the home of the one claim that cannot be drawn: a carrier the code holds and
 * the graph does not (Q12) has an address and **no node**, so a list of addresses is the
 * only place it can live.
 */

import type { GraphRead } from "../core/types";

type Props = {
  graph: GraphRead;
  onSelect: (id: string) => void;
};

export function Problems({ graph, onSelect }: Props) {
  const unproven = Object.entries(graph.skipped);

  return (
    <div className="bp-problems">
      {/* The count lives on the dock's tab, so a collapsed dock still says how much is
          wrong. What stays here is the claim that cannot be drawn as a node (Q12). */}
      {graph.completeness.state !== "proven" ? (
        <div className="bp-cap">
          <span className="bp-cap-n" title={graph.completeness.detail}>
            completeness unproven
          </span>
        </div>
      ) : null}

      {graph.diagnostics.map((diagnostic, index) => (
        <button
          key={`${diagnostic.code}:${index}`}
          className="bp-problem"
          onClick={() => diagnostic.node && onSelect(diagnostic.node)}
          title={diagnostic.repair}
        >
          <span className={`bp-sev is-${diagnostic.severity}`}>
            {diagnostic.code}
          </span>
          <span className="bp-problem-msg">{diagnostic.message}</span>
          <span className="bp-problem-addr">
            {diagnostic.location.file}:{diagnostic.location.start_line}
          </span>
        </button>
      ))}

      {unproven.map(([id, why]) => (
        <button key={id} className="bp-problem" onClick={() => onSelect(id)}>
          <span className="bp-sev is-unproven">unproven</span>
          <span className="bp-problem-msg">{why}</span>
          <span className="bp-problem-addr">{id}</span>
        </button>
      ))}

      {graph.diagnostics.length + unproven.length === 0 ? (
        <div className="bp-empty">
          Nothing is wrong, and everything that ran, passed.
        </div>
      ) : null}
    </div>
  );
}
