/**
 * Every addressed thing that is wrong. Unreal's Compiler Results.
 *
 * Three kinds of wrong, and they are different claims rather than one list with three
 * colours: a **diagnostic** is the static gate's judgement about the code, a **broken** node
 * is a run that entered it and failed, and an **unproven** one is a check that could not be
 * asked. Only the first exists before anybody presses Observe, which is why this panel used
 * to go quiet after a run that had just reddened half the graph -- the failures were on the
 * cards and nowhere else, and the panel that is named after problems did not list them.
 *
 * It is also the home of the one claim that cannot be drawn: a carrier the code holds and
 * the graph does not (Q12) has an address and **no node**, so a list of addresses is the
 * only place it can live.
 *
 * **Handing the list to the agent is composed here, and it is not a repair.** Nothing in
 * this panel edits code: it writes a request into the chat, where a person reads it before
 * anything is sent. `repair.apply` is the verb that changes a file, it is addressed at one
 * divergence, and §9's second case has two non-equivalent answers -- so a button that
 * silently resolved a list of them is exactly the thing `apply_repair`'s required
 * `resolution` exists to prevent. This one asks.
 */

import { useState } from "react";

import type { GraphRead } from "../core/types";

type Props = {
  graph: GraphRead;
  onSelect: (id: string) => void;
  /** Put a request in front of the person, in the chat. Never sends it for them. */
  onHandOver: (request: string) => void;
};

/** The nodes a run entered and failed. Drawn from the verdict, never from prose. */
function broken(graph: GraphRead): { id: string; why: string }[] {
  return Object.entries(graph.verdicts)
    .filter(([, verdict]) => verdict === "broken")
    .map(([id]) => ({
      id,
      why: graph.observations[id]?.detail || "a run entered this node and it failed",
    }));
}

/**
 * The list as a request, in the diagnostics' own words.
 *
 * Each line is an address and the catalogue's own repair text -- which is why that text
 * exists (`diagnostics.CATALOGUE`) rather than a message invented at the call site. A
 * failing node contributes the test that failed, because the name of the test is the whole
 * of what the agent needs to reproduce it.
 */
function asRequest(graph: GraphRead): string {
  const lines: string[] = [];
  for (const diagnostic of graph.diagnostics) {
    const at = `${diagnostic.location.file}:${diagnostic.location.start_line}`;
    lines.push(`- [${diagnostic.code}] ${at} — ${diagnostic.message}\n  ${diagnostic.repair}`);
  }
  for (const one of broken(graph)) {
    const by = graph.observations[one.id]?.by;
    lines.push(`- [failing] ${one.id} — ${one.why}${by ? `\n  the test: ${by}` : ""}`);
  }
  for (const [id, why] of Object.entries(graph.skipped)) {
    lines.push(`- [unproven] ${id} — ${why}`);
  }
  return [
    "Fix the problems this project's graph reports. Each line is an address and what the",
    "toolchain says about it. Change the code, not the markup, unless the diagnostic asks",
    "for markup; a node is green only once the project's own tests enter it and pass.",
    "",
    ...lines,
  ].join("\n");
}

export function Problems({ graph, onSelect, onHandOver }: Props) {
  const unproven = Object.entries(graph.skipped);
  const failing = broken(graph);
  const [copied, setCopied] = useState(false);
  const total = graph.diagnostics.length + failing.length + unproven.length;

  return (
    <div className="bp-problems">
      {total > 0 ? (
        <div className="bp-problems-acts">
          <button className="bp-btn bp-btn-go" onClick={() => onHandOver(asRequest(graph))}>
            Hand all to the agent
          </button>
          <button
            className="bp-btn"
            onClick={() => {
              // A refusal is worth showing: silence reads as a copy that worked, and the
              // person finds out otherwise when they paste nothing.
              navigator.clipboard
                .writeText(asRequest(graph))
                .then(() => setCopied(true))
                .catch(() => setCopied(false));
              window.setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? "copied" : "Copy"}
          </button>
        </div>
      ) : null}

      {/* The count lives on the rail, so a closed panel still says how much is wrong. What
          stays here is the claim that cannot be drawn as a node (Q12). */}
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
          <span className={`bp-sev is-${diagnostic.severity}`}>{diagnostic.code}</span>
          <span className="bp-problem-msg">{diagnostic.message}</span>
          <span className="bp-problem-addr">
            {diagnostic.location.file}:{diagnostic.location.start_line}
          </span>
        </button>
      ))}

      {/* A run's failures, which is what a person is looking at this panel for after
          pressing Observe. The reason is the observation's own text -- the same sentence the
          inspector shows, because there is one answer and two places that need it. */}
      {failing.map((one) => (
        <button key={one.id} className="bp-problem" onClick={() => onSelect(one.id)}>
          <span className="bp-sev is-error">failing</span>
          <span className="bp-problem-msg">{one.why}</span>
          <span className="bp-problem-addr">{one.id}</span>
        </button>
      ))}

      {unproven.map(([id, why]) => (
        <button key={id} className="bp-problem" onClick={() => onSelect(id)}>
          <span className="bp-sev is-unproven">unproven</span>
          <span className="bp-problem-msg">{why}</span>
          <span className="bp-problem-addr">{id}</span>
        </button>
      ))}

      {total === 0 ? (
        <div className="bp-empty">Nothing is wrong, and everything that ran, passed.</div>
      ) : null}
    </div>
  );
}
