/**
 * A flow arrow: one node having run and then another (Q9).
 *
 * It is a custom edge for one reason -- **the arrowhead belongs in the middle of the line,
 * not at its end.** On a graph the size of a real project the ends are where the lines are
 * densest: a dozen arrowheads meet at one card's pin, and the picture stops saying which
 * line came from where. A marker at the midpoint sits in open space, so direction is
 * readable without following the line to its end, and the reading works the same at any
 * zoom.
 *
 * The angle is measured off the rendered path rather than computed from the endpoints,
 * because a smoothstep path turns corners: at the midpoint of an L the endpoint-to-endpoint
 * direction is diagonal and the line is not, and an arrow pointing somewhere the line does
 * not go is worse than no arrow.
 *
 * Colour and corner radius are deliberately softer than the contract edges' default: flow
 * is the loudest thing on the canvas after a run, and at this density near-black right
 * angles read as a wiring diagram of something else.
 */

import { useEffect, useRef, useState } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

/** Where the arrowhead sits and which way it points. Null until the path has been measured. */
type Mark = { x: number; y: number; angle: number };

export function FlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  data,
}: EdgeProps) {
  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    // Generous, so a turn reads as a turn rather than as a corner of a box.
    borderRadius: 18,
  });

  const measured = useRef<SVGPathElement | null>(null);
  const [mark, setMark] = useState<Mark | null>(null);

  useEffect(() => {
    const element = measured.current;
    if (!element) return;
    const length = element.getTotalLength();
    if (!length) return;
    // Two points a little either side of the middle: their difference is the tangent, which
    // is the direction the line is actually going where the arrow is drawn.
    const before = element.getPointAtLength(Math.max(0, length / 2 - 3));
    const after = element.getPointAtLength(Math.min(length, length / 2 + 3));
    setMark({
      x: (before.x + after.x) / 2,
      y: (before.y + after.y) / 2,
      angle: (Math.atan2(after.y - before.y, after.x - before.x) * 180) / Math.PI,
    });
  }, [path]);

  const observed = data?.origin === "observed";

  return (
    <>
      <BaseEdge id={id} path={path} style={style} />
      {/* Never painted: it exists so the arrowhead can be placed on the same geometry the
          edge is drawn with, rather than on a second guess at it. */}
      <path ref={measured} d={path} fill="none" stroke="none" />
      {mark ? (
        <EdgeLabelRenderer>
          <div
            className={`bp-flow-mark${observed ? " is-observed" : " is-wiring"}`}
            style={{
              transform: `translate(-50%, -50%) translate(${mark.x}px, ${mark.y}px) rotate(${mark.angle}deg)`,
            }}
          />
        </EdgeLabelRenderer>
      ) : // Before the first measurement there is a line and no arrowhead, which is the
      // honest intermediate state: nothing is drawn pointing the wrong way.
      null}
    </>
  );
}

/** Kept beside the component so the canvas registers exactly what this file defines. */
export const flowEdgeTypes = { bpFlow: FlowEdge };
