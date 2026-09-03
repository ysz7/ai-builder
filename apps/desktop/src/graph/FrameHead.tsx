/**
 * What a system contains, drawn while it is folded.
 *
 * A count on the parent's own header said "there is more here" and nothing else: a person
 * had to know that the number was a fold before it meant anything, and until they pressed it
 * the tools and the routes were absent from the picture. **They are in the code either way**,
 * so the honest drawing is one that shows them at both sizes — folded, this bar stands for
 * them and carries a line to the card that holds them; open, the line moves onto the cards
 * themselves and this is replaced by the frame around them.
 *
 * It is a bar and never a card, because it is not a node: it has no verdict, no settings, no
 * position of its own in `layout.json` and nothing to run. What it has is a fold, which is
 * view state, and view state is the only thing a thing like this may own.
 */

import { useRef } from "react";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { glyphOf, labelOf, tintBgOf, tintOf } from "./kinds";

export type FrameHeadData = {
  /** The parent's id. The fold is about it, and this bar has no id of its own to fold. */
  system: string;
  /** What is inside, counted by kind — the same tally the open frame's bar carries. */
  parts: { kind: string; count: number }[];
  /** Which side of the parent this hangs off — see `holdSide` for why that is not taste. */
  side: "left" | "bottom";
  onToggle: (id: string) => void;
};

export function FrameHead({ data }: NodeProps) {
  const { system, parts, side, onToggle } = data as unknown as FrameHeadData;
  // The commonest kind gives the bar its colour and its glyph, so a folded row of tools
  // looks like tools. With one kind inside — which is nearly always — it simply is that one.
  const main = parts[0]?.kind ?? "file";
  /**
   * Where the press started, so a drag is not read as a click.
   *
   * The bar is both — it can be moved, and pressing it opens the frame in the place it was
   * moved to — and React Flow's drag ends with an ordinary click on the element underneath.
   * Three pixels is the difference between putting something somewhere and pressing it.
   */
  const from = useRef<{ x: number; y: number } | null>(null);

  const said = parts
    .map(
      (part) =>
        `${part.count} ${labelOf(part.kind).toLowerCase()}${part.count === 1 ? "" : "s"}`,
    )
    .join(" · ");

  return (
    <div
      className="bp-head"
      style={{
        ["--tint" as string]: tintOf(main),
        ["--tint-bg" as string]: tintBgOf(main),
      }}
    >
      {/* The line leaves from the side the parts belong on: a service's routes run into it
          left to right, the way every other flow on this canvas does, and an agent's tools
          hang below it where they cannot be read as a step in anything. */}
      {side === "left" ? (
        <Handle type="source" position={Position.Right} className="pin pin-data" id="out" />
      ) : (
        <Handle type="target" position={Position.Top} className="pin pin-data" id="up" />
      )}
      <button
        className="bp-head-bar"
        title="Expand — it opens where it is"
        onPointerDown={(event) => {
          from.current = { x: event.clientX, y: event.clientY };
        }}
        onClick={(event) => {
          const at = from.current;
          from.current = null;
          if (at && Math.hypot(event.clientX - at.x, event.clientY - at.y) > 3) return;
          onToggle(system);
        }}
      >
        <span className="bp-chev">▸</span>
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d={glyphOf(main)}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {said}
      </button>
    </div>
  );
}
