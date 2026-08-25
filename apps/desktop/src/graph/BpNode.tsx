/**
 * One node on the canvas.
 *
 * The whole of I-5, drawn: a mark that says what is known, and **the reason beside it**.
 * `detail` and `skipped` are the most useful strings the core returns -- "the broker does
 * not answer -- start it from the compose file's node" is a repair instruction, not a
 * status -- so reducing either to a coloured dot would throw away the answer and keep the
 * decoration.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { GraphNode, Verdict } from "../core/types";
import { MARKS, shortKind, tintOf } from "./kinds";

export type BpNodeData = {
  node: GraphNode;
  verdict: Verdict;
  /** Why the node is what it is: the observation's detail, or why no check could run. */
  reason: string;
  /** Set while the agent is editing the file this node lives in. */
  lit: boolean;
};

export function BpNode({ data, selected }: NodeProps) {
  const { node, verdict, reason, lit } = data as unknown as BpNodeData;

  return (
    <div
      className={`bp-node${selected ? " is-selected" : ""}${lit ? " is-lit" : ""}`}
      style={{ ["--tint" as string]: tintOf(node.kind) }}
    >
      {/* Both relations arrive at the same node, so both pin shapes live on it. Which one
          is used is decided by the edge, not here. */}
      <Handle type="target" position={Position.Left} className="pin pin-data" id="data-in" />
      <Handle type="source" position={Position.Right} className="pin pin-data" id="data-out" />
      <Handle type="target" position={Position.Top} className="pin pin-exec" id="exec-in" />
      <Handle type="source" position={Position.Bottom} className="pin pin-exec" id="exec-out" />

      <div className="bp-node-head">
        <span className="bp-node-title">{node.title ?? node.id}</span>
        <span className="bp-node-kind">{shortKind(node.kind)}</span>
        <span className={`bp-mark is-${verdict}`} title={reason}>
          {MARKS[verdict]}
        </span>
      </div>
      {reason ? (
        <div className="bp-node-body">
          <div className="bp-node-why">{reason}</div>
        </div>
      ) : null}
    </div>
  );
}
