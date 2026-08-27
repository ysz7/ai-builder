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
  /** A process this node's kind starts is alive right now. Not a verdict — see `running`. */
  running: boolean;
  /**
   * Which of the four pins an edge actually lands on.
   *
   * **A pin is a socket something is plugged into, not decoration.** Drawn unconditionally,
   * every node wore four of them — two at the sides, two at top and bottom — and a node with
   * no edges at all was covered in sockets for relations it does not have. Which ones exist
   * is a fact about the edges, so it is computed where the edges are and passed in.
   */
  pins: { dataIn: boolean; dataOut: boolean; execIn: boolean; execOut: boolean };
};

export function BpNode({ data, selected }: NodeProps) {
  const { node, verdict, reason, lit, running, pins } =
    data as unknown as BpNodeData;

  return (
    <div
      className={`bp-node${selected ? " is-selected" : ""}${lit ? " is-lit" : ""}${
        running ? " is-running" : ""
      }`}
      style={{ ["--tint" as string]: tintOf(node.kind) }}
    >
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

      <div className="bp-node-head">
        {/* Running is **not a verdict** and is drawn apart from one: a live dot says a
            process is up on this machine, and the mark beside it still says whether
            anything has been proven about the code. A server that runs and fails every
            test has to be able to say both. */}
        {running ? <span className="bp-node-live" title="running" /> : null}
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
