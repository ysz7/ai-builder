/**
 * A group, drawn as a frame around what it contains.
 *
 * The frame has **no geometry of its own** -- it is the bounding box of its members,
 * recomputed on every render. That is why it can never disagree with what is inside it,
 * and why dragging a member drags the frame around it rather than out of alignment.
 *
 * A collapsed frame **keeps its mark**. Without that, collapsing a group would be a way of
 * making the graph look better by looking at less of it.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { GraphNode, Verdict } from "../core/types";
import { glyphOf, MARKS, tintBgOf, tintOf } from "./kinds";

export type BpGroupData = {
  node: GraphNode;
  verdict: Verdict;
  reason: string;
  collapsed: boolean;
  memberCount: number;
  selected: boolean;
  /** A process this group's kind starts is alive right now. */
  running: boolean;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
};

export function BpGroup({ data }: NodeProps) {
  const {
    node,
    verdict,
    reason,
    collapsed,
    memberCount,
    selected,
    running,
    onToggle,
    onSelect,
  } = data as unknown as BpGroupData;

  return (
    <div
      className={`bp-frame${collapsed ? " is-collapsed" : ""}${
        selected ? " is-selected" : ""
      }${running ? " is-running" : ""}`}
      style={{
        ["--tint" as string]: tintOf(node.kind),
        ["--tint-bg" as string]: tintBgOf(node.kind),
      }}
    >
      {/* The one anchor a frame has, and it exists for exactly one line: the dashed one
          from a chat card (Q34), which sits to the frame's left and points at it. A frame
          is otherwise pinless on purpose -- the two real relations land on member cards,
          not on the region around them -- so this is invisible and carries no meaning of
          its own. Without it the line from an agent's chat card was silently dropped,
          because React Flow renders no edge naming a handle that is not there, and an
          agent is always a group. */}
      <Handle
        type="target"
        position={Position.Left}
        id="talk-in"
        className="bp-pin-hidden"
        isConnectable={false}
      />

      {/* **The bar is the node.** A group is a node like any other -- it has a kind, a
          verdict, knobs and the buttons that start it -- and drawing it as nothing but a
          region around its members left the one node a person most wants (the service) with
          no way to select it on the canvas at all. So the bar selects, and the chevron
          beside it folds: two actions, two buttons, rather than one that guesses. */}
      <button
        className="bp-frame-bar"
        onClick={() => onSelect(node.id)}
        title={node.title ?? node.id}
      >
        <span
          // Not a drag handle: the triangle is 9px of text and a hand that slips while
          // pressing it would move the whole subtree instead of folding it.
          className="bp-chev nodrag"
          role="button"
          tabIndex={-1}
          title={collapsed ? "Expand" : "Collapse"}
          onClick={(event) => {
            event.stopPropagation();
            onToggle(node.id);
          }}
        >
          {collapsed ? "▸" : "▾"}
        </span>
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <path
            d={glyphOf(node.kind)}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {running ? <span className="bp-node-live" title="running" /> : null}
        {node.title ?? node.id}
        <span className="bp-count">{memberCount}</span>
        <span className={`bp-mark is-${verdict}`} title={reason}>
          {MARKS[verdict]}
        </span>
      </button>
    </div>
  );
}
