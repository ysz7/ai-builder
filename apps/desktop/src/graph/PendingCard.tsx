/**
 * Something being written, drawn where it will land.
 *
 * **This is a progress indicator, not a node, and every difference between the two is
 * deliberate.** It has no position in `layout.json`, it cannot be dragged, it has no
 * verdict, no settings and no Run, and it is gone the moment the turn ends — after which
 * the graph is read again and either a real node is there or it is not.
 *
 * Each of those is a way it could have survived its turn, and a marker that survived its
 * turn is a node the code does not have. That is invariant 1 broken by a spinner, which is
 * a genuinely easy way to lose this argument: nothing about it would look wrong until
 * somebody asked why the node was grey.
 *
 * So it is drawn as unmistakably provisional — dashed, tinted, pulsing — and it says what it
 * is waiting for rather than pretending to be the thing it is waiting for.
 */

import { type NodeProps } from "@xyflow/react";

import { glyphOf, labelOf, tintBgOf, tintOf } from "./kinds";

export type PendingData = { kind: string };

export function PendingCard({ data }: NodeProps) {
  const { kind } = data as unknown as PendingData;

  return (
    <div
      className="bp-card-wrap is-pending"
      style={{
        ["--tint" as string]: tintOf(kind),
        ["--tint-bg" as string]: tintBgOf(kind),
      }}
    >
      <div className="bp-card-tab">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d={glyphOf(kind)}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {labelOf(kind)}
      </div>

      <div className="bp-card bp-card-pending">
        <div className="bp-card-head">
          <span className="bp-pending-pulse" aria-hidden="true" />
          <span className="bp-card-title">{labelOf(kind)}</span>
        </div>
        {/* What it is, said plainly. It is not claiming to be a node yet, and the sentence is
            what stops it reading as one that has gone wrong. */}
        <div className="bp-card-desc">being written…</div>
        <div className="bp-card-why">
          It appears for real when the package is on disk and the graph is read again.
        </div>
      </div>
    </div>
  );
}
