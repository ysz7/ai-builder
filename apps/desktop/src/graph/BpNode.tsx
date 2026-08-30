/**
 * One node on the canvas, in the reference's card anatomy (P18.3).
 *
 * Element for element it is the reference's card -- a category tab above and inset from the left
 * edge, a header of glyph, title and a `⋮`, a grey description line, inset field blocks with
 * a small uppercase label, a pill, and a footer row of chips -- and every one of those
 * elements has been given the fact this architecture actually holds:
 *
 *   - their category is a **role** they invented; ours is the kind's **family**, tinted;
 *   - their field blocks hold a prompt; ours hold **knobs**, which the writer can reach
 *     through the syntax tree, edited through the same `knob.set` the inspector uses;
 *   - their footer carries **telemetry**; ours carried **evidence**, and now carries
 *     nothing.
 *
 * That last row is gone by decision, and the trade is worth stating rather than losing.
 * `Green because test_retrieval.py entered it` is the sentence this project exists to be
 * able to say, and P18 drew it here so that a screenshot could find it. What it cost is
 * that pressing Observe changed every card at once -- new chips, a taller box, a green
 * band across a canvas that had just been read -- and the card is a thing a person arranges
 * and looks at, not a report. **The mark is the only thing a run changes now**, which also
 * keeps the drawn card the size `place.cardHeight` predicted, so a frame still wraps its
 * members after a run.
 *
 * The evidence itself did not move far: `Problems` names the test that failed, and
 * the rail's flyout names it for every node at once.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { GraphNode, Knob, Verdict } from "../core/types";
import { KnobBlock } from "../panels/Knob";
import { MODEL_KNOBS, namesAModel } from "../panels/Model";
import { familyName, glyphOf, MARKS, tintBgOf, tintOf } from "./kinds";

/** How many knobs a collapsed card shows. The reference shows one or two blocks; three is
 *  the point where a card stops being scannable and starts being a form. */
const COLLAPSED_KNOBS = 3;

export type BpNodeData = {
  node: GraphNode;
  verdict: Verdict;
  /** Why the node is what it is: the observation's detail, or why no check could run. */
  reason: string;
  /** Set while the agent is editing the file this node lives in. */
  lit: boolean;
  /** Show this node in the Problems panel. Only reachable from a mark that is not green. */
  onProblems: (id: string) => void;
  /** A process this node's kind starts is alive right now. Not a verdict — see `running`. */
  running: boolean;
  /**
   * Every knob, or the first few.
   *
   * A fact about how *this person* is looking at the graph rather than about the project,
   * so it lives in the layout cache beside the coordinates (Q13) -- and like a coordinate,
   * the core stores it and refuses to understand it.
   */
  expanded: boolean;
  onExpand: (id: string) => void;
  onKnob: (node: string, knob: string, value: unknown) => void;
  /** The `⋮`. What it offers is asked of the registry by the caller, never listed here. */
  onMenu: (id: string, at: { x: number; y: number }) => void;
  /**
   * Which of the four pins an edge actually lands on.
   *
   * **A pin is a socket something is plugged into, not decoration.** Drawn unconditionally,
   * every node wore four of them — two at the sides, two at top and bottom — and a node with
   * no edges at all was covered in sockets for relations it does not have. Which ones exist
   * is a fact about the edges, so it is computed where the edges are and passed in. The
   * reference draws a socket on every card; §18.6 says why we do not.
   */
  pins: { dataIn: boolean; dataOut: boolean; execIn: boolean; execOut: boolean };
};

export function BpNode({ data, selected }: NodeProps) {
  const {
    node,
    verdict,
    reason,
    lit,
    running,
    expanded,
    pins,
    onExpand,
    onKnob,
    onMenu,
    onProblems,
  } = data as unknown as BpNodeData;

  // **Where a node names a model, the card shows the model and not its plumbing.** An
  // endpoint and the name of a key variable are two lines of URL on a card somebody is
  // arranging and reading, and they say nothing a glance wants: the question a card answers
  // is *which model*, and the rest is one click away in the inspector, where it is one
  // control (`Model.tsx`). Nothing is dropped from the node -- this is what is drawn.
  const shown = namesAModel(node)
    ? node.knobs.filter((knob) => knob.name === "model" || !MODEL_KNOBS.includes(knob.name))
    : node.knobs;
  const knobs: Knob[] = expanded ? shown : shown.slice(0, COLLAPSED_KNOBS);
  const hidden = shown.length - knobs.length;

  return (
    <div
      className={`bp-card-wrap${selected ? " is-selected" : ""}${lit ? " is-lit" : ""}`}
      style={{
        ["--tint" as string]: tintOf(node.kind),
        ["--tint-bg" as string]: tintBgOf(node.kind),
      }}
    >
      {/* The category tab: above the card and inset from its left edge, tinted and named,
          exactly where the reference puts `Input` / `Action` / `LLM`. It names the family
          and never the state -- the verdict has its own mark, and a tab that changed colour
          when a test failed would be two facts fighting over one element. */}
      <div className="bp-card-tab">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path d={glyphOf(node.kind)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {familyName(node.kind)}
      </div>

      <div className={`bp-card${running ? " is-running" : ""}`}>
        {/* Both relations arrive at the same node, so both pin shapes live on it -- but only
            where an edge uses one. Which is decided by the edge, not here. */}
        {pins.dataIn ? (
          <Handle type="target" position={Position.Left} className="pin pin-data" id="data-in" />
        ) : null}
        {pins.dataOut ? (
          <Handle type="source" position={Position.Right} className="pin pin-data" id="data-out" />
        ) : null}
        {pins.execIn ? (
          <Handle type="target" position={Position.Top} className="pin pin-exec" id="exec-in" />
        ) : null}
        {pins.execOut ? (
          <Handle type="source" position={Position.Bottom} className="pin pin-exec" id="exec-out" />
        ) : null}

        <div className="bp-card-head">
          <svg className="bp-card-glyph" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d={glyphOf(node.kind)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="bp-card-title">{node.title ?? node.id}</span>

          {/* Running is **not a verdict** and is drawn apart from one: a live dot says a
              process is up on this machine, and the mark beside it still says whether
              anything has been proven about the code. A server that runs and fails every
              test has to be able to say both. */}
          {running ? <span className="bp-card-live" title="running" /> : null}
          {/* **The mark is the way into the problem, not a decoration beside it.** A
              verdict that is not green has an address, a reason and somewhere it is listed
              with everything else in that state -- so pressing it opens that list rather
              than asking the reader to find it. Green is not a button because there is
              nothing on the other side of it.
              Green also stays *drawn*, quietly. Hiding it would make the absence of a mark
              mean "proven", and I-5's rule is the opposite one: an absent observation must
              never read as a passing one, and a graph nobody has observed would then look
              much like a graph that passed. */}
          {verdict === "green" ? (
            <span className="bp-mark is-green" title={reason}>
              {MARKS.green}
            </span>
          ) : (
            <button
              className={`bp-mark is-${verdict} nodrag`}
              title={reason || "Show this in Problems"}
              aria-label="Show this in Problems"
              onClick={(event) => {
                event.stopPropagation();
                onProblems(node.id);
              }}
            >
              {MARKS[verdict]}
            </button>
          )}

          <button
            className="bp-card-menu nodrag"
            title="More"
            aria-label="More"
            onClick={(event) => {
              event.stopPropagation();
              const box = event.currentTarget.getBoundingClientRect();
              onMenu(node.id, { x: box.left, y: box.bottom + 4 });
            }}
          >
            ⋮
          </button>
        </div>

        {/* The carrier's own first docstring line (Q29), where there is one. What the node
            says about itself, in the author's words rather than in ours. */}
        {node.summary ? <div className="bp-card-desc">{node.summary}</div> : null}

        {knobs.map((knob) => (
          <KnobBlock
            key={knob.name}
            knob={knob}
            onChange={(value) => onKnob(node.id, knob.name, value)}
          />
        ))}

        {shown.length > COLLAPSED_KNOBS ? (
          <button
            className="bp-card-more nodrag"
            onClick={(event) => {
              event.stopPropagation();
              onExpand(node.id);
            }}
          >
            {hidden > 0 ? `${hidden} more` : "fewer"}
          </button>
        ) : null}

        {/* The kind pill, in the geometry the reference gives the model name, and it spells
            the **registry name in full**. `route` beside a tinted `FastAPI` tab was the
            shorter reading, but the dotted name is the value: it is what `kind=` says in the
            code, what the library behind `+` lists, and what a person types when they ask
            the agent for another one. The comment here always claimed the full name was
            drawn; now it is. */}
        <div className="bp-card-pill-row">
          <span className="bp-pill">{node.kind}</span>
        </div>

        {/* **The reason is not on the card any more**, and this is Q33 finishing its own
            argument. That rule removed the evidence row because a run rewrote every card at
            once; the reason paragraph did the same thing in more words -- after Observe the
            canvas filled with test names and stopped being something a person arranges and
            reads. It is on the mark as a tooltip, in the inspector in full, and in Problems
            beside everything else in the same state. Nothing was lost; it stopped being
            printed in the one place that has to stay legible at a glance. */}
      </div>
    </div>
  );
}
