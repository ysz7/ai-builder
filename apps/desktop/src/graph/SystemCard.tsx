/**
 * A system node, drawn as the reference's card.
 *
 * The anatomy is theirs, element for element: a category tab above and inset from the left
 * edge, a white rounded rectangle with a soft shadow and a hairline, a header of glyph and
 * title, a quiet second line, and a pill. What fills each of those is ours.
 *
 * What it puts on the face of the card is **the reason the node exists**: the kind in the
 * tab, the path underneath, and the required export in the pill. A person reading the
 * canvas can see why `agent/` is an Agent without opening anything, which is the difference
 * between a graph that explains itself and a picture of one.
 *
 * The verdict is a **mark in the header and never a fill on the card**: the tab carries the
 * kind, and a card washed in a state colour would be two facts fighting over one element.
 * Before anything has been observed there is no mark at all — an absent verdict must read as
 * absent, not as an early guess at a good one (I-3).
 *
 * The incomplete state is separate from all of that and is drawn separately: it is a reading
 * of the code itself, the export the package does not have, so it is said in words. A hue
 * there would later fight Observe's for the same meaning.
 *
 * **Ports are rows with a pin each, and they replace the pill rather than joining it.** An
 * edge attaches to an exported symbol, not to a package: `worker → rag.index` and
 * `agent → rag.search` say that uploads index and questions retrieve, which `→ rag` twice
 * does not. On a rag the ports *are* the contract, so drawing the pill underneath would say
 * the same thing twice; on a worker they are the handler names and the pill's `HANDLERS` is
 * only where the list is kept. Either way the card says what it offers once.
 *
 * A single port is drawn as no rows at all — see `hasPorts`. The pin is where it always was.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { GraphNode } from "../core/types";
import { contractOf, glyphOf, isSystem, labelOf, tintBgOf, tintOf } from "./kinds";
import { hasPorts } from "./place";
import { known, markOf, wordsFor } from "./verdicts";

export type CardData = {
  node: GraphNode;
  /** What the last run proved, or `""` where nothing has been observed here. */
  verdict: string;
  /** Why, in the run's own words. Shown on hover rather than on the card: a card is not a log. */
  reason: string;
  /**
   * What the last run cost, already worded — `"7,700 tok · $0.023"` — or `""`.
   *
   * **Not a verdict and never coloured.** Money spent proves nothing; it sits in the card's
   * quiet type beside the path, and a node nobody has run carries nothing at all rather than
   * a zero.
   */
  cost: string;
  /** Whether an edge actually lands on each side. A pin nothing uses is decoration. */
  pins: { in: boolean; out: boolean; up: boolean; down: boolean };
  /** Showing its children rather than a count. View state; it changes nothing in the project. */
  expanded: boolean;
  onOpen: (id: string) => void;
  onToggle: (id: string) => void;
  /** Open this agent's own chat. Only an agent has one; nothing else is talked to. */
  onTalk: (id: string) => void;
  /**
   * Ask the chat to make this node satisfy its kind, naming what it is missing.
   *
   * Absent on a node that has nothing missing, and it produces a **message**, never a file:
   * the graph is still a projection, and the only thing that changes a project is the agent
   * writing code that gets read back.
   */
  onRepair?: (node: GraphNode) => void;
};

export function SystemCard({ data, selected }: NodeProps) {
  const { node, verdict, reason, cost, pins, expanded, onOpen, onToggle, onTalk, onRepair } =
    data as unknown as CardData;
  const ports = hasPorts(node) ? node.ports : [];

  return (
    <div
      className={`bp-card-wrap${selected ? " is-selected" : ""}`}
      style={{
        ["--tint" as string]: tintOf(node.kind),
        ["--tint-bg" as string]: tintBgOf(node.kind),
      }}
      onClick={() => onOpen(node.id)}
      // Double-click is the fold, as the plan states it. Only where there is something to
      // fold: on a childless system it would be a gesture that silently does nothing.
      onDoubleClick={() => node.children.length > 0 && onToggle(node.id)}
    >
      <div className="bp-card-tab">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d={glyphOf(node.kind)}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {labelOf(node.kind)}
      </div>

      <div className="bp-card">
        {/* Both directions of a dependency land on the same card, so both pins live on it —
            but only where an edge uses one. Which is decided by the edges, not here. */}
        {pins.in ? (
          <Handle type="target" position={Position.Left} className="pin pin-data" id="in" />
        ) : null}
        {pins.out ? (
          <Handle type="source" position={Position.Right} className="pin pin-data" id="out" />
        ) : null}
        {pins.up ? (
          <Handle type="target" position={Position.Top} className="pin pin-data" id="up" />
        ) : null}
        {pins.down ? (
          <Handle type="source" position={Position.Bottom} className="pin pin-data" id="down" />
        ) : null}

        <div className="bp-card-head">
          <svg
            className="bp-card-glyph"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            aria-hidden="true"
          >
            <path
              d={glyphOf(node.kind)}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="bp-card-title">{node.name}</span>

          {/* Drawn only when there is one. An absent verdict is drawn as absent, because a
              default would be this application deciding what an unobserved project looks
              like — and every builder that decided that decided "fine". */}
          {known(verdict) ? (
            <span
              className={`bp-mark is-${verdict}`}
              title={reason || wordsFor(verdict)}
              aria-label={wordsFor(verdict)}
            >
              {markOf(verdict)}
            </span>
          ) : null}

          {/* The count, and the fold it belongs to. A system with children says how many
              before it is opened — the plan's `0 to 1`, which is the one number on the
              canvas that changes when the agent writes a package. */}
          {node.children.length > 0 ? (
            <button
              className="bp-card-count nodrag"
              title={expanded ? "Collapse" : "Expand"}
              onClick={(event) => {
                event.stopPropagation();
                onToggle(node.id);
              }}
            >
              {expanded ? "▾" : "▸"} {node.children.length}
            </button>
          ) : null}
        </div>

        {/* A package is a directory and a tool is a file, and the slash is what says which.
            Writing `agent/tools/look_up.py/` would be a path that does not exist. */}
        <div className="bp-card-desc">
          {node.path}
          {isSystem(node.kind) ? "/" : ""}
        </div>

        {/* What the last run cost, where one was measured. **Never coloured and never a
            verdict**: money spent proves nothing, and a card that dressed it as evidence
            would be the flow-document defect wearing a dollar sign. Absent where nothing
            has been run — a row that always existed would invite a default in it. */}
        {/* A file that would not parse, named with the line it stopped on. **It marks the
            node and blanks nothing**: everything else here is still what the last good read
            said, because one unreadable file changes none of it. Drawn apart from the
            verdict mark, which is about a test run rather than about right now. */}
        {node.broken ? (
          <div className="bp-card-broken" title={`${node.broken} — the graph is unchanged`}>
            ⚠ {node.broken}
          </div>
        ) : null}

        {cost ? <div className="bp-card-cost">{cost}</div> : null}

        {/* On the card rather than only in the panel, because talking to the thing is what a
            person came to the canvas to do. Drawn only where the export exists: a button
            whose only possible outcome is an error is worse than no button. */}
        {node.kind === "agent" && node.missing.length === 0 ? (
          <button
            className="bp-card-talk nodrag"
            title="Chat with this agent"
            onClick={(event) => {
              event.stopPropagation();
              onTalk(node.id);
            }}
          >
            Chat
          </button>
        ) : null}

        {/* Stated, never repaired. A directory that looks like a system and is not one is
            the state a half-written package is in, and naming the missing export is the
            whole of what this application can honestly say about it. */}
        {node.reason ? <div className="bp-card-why">{node.reason}</div> : null}

        {/* **The one place the graph talks back**, and it is allowed because a convention
            violation is a fact rather than an opinion: this package does not bind the name
            its kind requires, which is checkable and is checked. The button sends `/repair`
            with the missing export named — it writes nothing itself, and the node turns
            complete only when the code does. */}
        {node.missing.length > 0 && onRepair ? (
          <button
            className="bp-card-talk nodrag"
            title={`Ask the agent to add ${node.missing.join(" and ")}`}
            onClick={(event) => {
              event.stopPropagation();
              onRepair(node);
            }}
          >
            Ask agent to fix
          </button>
        ) : null}

        {/* One row per entry point, each with the pin its edges land on. The pin is placed
            by the row rather than by arithmetic: the row knows where it is, and a number
            here would be a second opinion about the stylesheet. */}
        {ports.length > 0 ? (
          <div className="bp-card-ports">
            {ports.map((port) => (
              <div className="bp-card-port" key={port}>
                <Handle
                  type="target"
                  position={Position.Left}
                  className="pin pin-data"
                  id={`port:${port}`}
                />
                {port}
              </div>
            ))}
          </div>
        ) : node.exports.length > 0 ? (
          <div className="bp-card-pill-row">
            <span
              className="bp-pill"
              title={`${labelOf(node.kind)} exports ${contractOf(node.exports)}`}
            >
              {contractOf(node.exports)}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
