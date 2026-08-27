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

import type { NodeProps } from "@xyflow/react";

import type { GraphNode, Verdict } from "../core/types";
import { MARKS, tintOf } from "./kinds";

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
      style={{ ["--tint" as string]: tintOf(node.kind) }}
    >
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
          className="bp-chev"
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
