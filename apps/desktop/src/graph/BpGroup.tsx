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
  onToggle: (id: string) => void;
};

export function BpGroup({ data }: NodeProps) {
  const { node, verdict, reason, collapsed, memberCount, onToggle } =
    data as unknown as BpGroupData;

  return (
    <div
      className={`bp-frame${collapsed ? " is-collapsed" : ""}`}
      style={{ ["--tint" as string]: tintOf(node.kind) }}
    >
      <button
        className="bp-frame-bar"
        onClick={() => onToggle(node.id)}
        title={collapsed ? "Expand" : "Collapse"}
      >
        <span className="bp-chev">{collapsed ? "▸" : "▾"}</span>
        {node.title ?? node.id}
        <span className="bp-count">{memberCount}</span>
        <span className={`bp-mark is-${verdict}`} title={reason}>
          {MARKS[verdict]}
        </span>
      </button>
    </div>
  );
}
