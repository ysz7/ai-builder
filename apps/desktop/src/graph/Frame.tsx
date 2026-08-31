/**
 * The region drawn around a system's children.
 *
 * **It has no geometry of its own.** The box is computed from where its members actually
 * are, every render, which is why it can never disagree with them — a frame with a stored
 * size would drift the first time somebody moved a card, and then the picture would claim a
 * membership the code does not.
 *
 * It is not draggable and it is not selectable. A frame is a statement about containment
 * that the parser made; the node it belongs to is the card above it, and that is what a
 * person clicks. The one thing the bar does is fold, because a fold is view state and view
 * state is the only thing a frame is allowed to own.
 */

import type { NodeProps } from "@xyflow/react";

import { labelOf, tintBgOf, tintOf } from "./kinds";
import { known, markOf, wordsFor } from "./verdicts";

export type FrameData = {
  /** The parent's id — what the fold is about. Never the frame's own: it does not have one. */
  system: string;
  name: string;
  kind: string;
  count: number;
  /** The parent's aggregate, repeated on the bar so a folded-open card still says it. */
  verdict: string;
  onToggle: (id: string) => void;
};

export function Frame({ data }: NodeProps) {
  const { system, name, kind, count, verdict, onToggle } = data as unknown as FrameData;

  return (
    <div
      className="bp-frame"
      style={{
        ["--tint" as string]: tintOf(kind),
        ["--tint-bg" as string]: tintBgOf(kind),
      }}
    >
      <button
        className="bp-frame-bar nodrag"
        onClick={() => onToggle(system)}
        title="Collapse"
      >
        <span className="bp-chev">▾</span>
        {name} · {labelOf(kind).toLowerCase()}s
        <span className="bp-count">{count}</span>
        {known(verdict) ? (
          <span className={`bp-mark is-${verdict}`} title={wordsFor(verdict)}>
            {markOf(verdict)}
          </span>
        ) : null}
      </button>
    </div>
  );
}
