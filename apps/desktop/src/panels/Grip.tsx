/**
 * The border you can pull.
 *
 * One implementation for all three panes, because a resize that behaves differently on the
 * left than at the bottom is a bug nobody reports and everybody feels. What differs between
 * them is only *which* coordinate is the size, which is the table below and nothing else.
 *
 * The strip is deliberately wider than the border it sits on -- a one-pixel target is a
 * target people miss -- while the hint painted on hover is one pixel, so what lights up is
 * the border rather than the hit area (see `.bp-grip::after`).
 *
 * Listeners go on the document for the duration of the drag: the pointer leaves the strip
 * immediately and every pane it crosses would otherwise swallow the movement. They come off
 * on **both** the release and the cancel -- a drag that only listens for one of those is a
 * drag that can latch, and a latched drag takes the whole window with it.
 */

import { useCallback } from "react";

type Side = "bottom" | "left" | "right";

/** Where the pane's far edge is, so the size is the distance from it to the pointer. */
const MEASURE: Record<Side, (event: PointerEvent) => number> = {
  bottom: (event) => window.innerHeight - event.clientY,
  left: (event) => event.clientX,
  right: (event) => window.innerWidth - event.clientX,
};

type Props = {
  side: Side;
  min: number;
  max: () => number;
  onSize: (size: number) => void;
};

export function Grip({ side, min, max, onSize }: Props) {
  const grab = useCallback(
    (event: React.PointerEvent) => {
      event.preventDefault();
      const measure = MEASURE[side];
      const move = (moved: PointerEvent) =>
        onSize(Math.max(min, Math.min(measure(moved), max())));
      const release = () => {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", release);
        document.removeEventListener("pointercancel", release);
        document.body.classList.remove("is-resizing");
      };
      // While dragging, every pane the pointer crosses would otherwise select its text.
      document.body.classList.add("is-resizing");
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", release);
      // **And on cancel.** A pointer can end without ever being released -- the OS takes it
      // for a gesture, the window loses capture, a touch is interrupted -- and a drag that
      // only listens for `pointerup` is then latched forever: the document keeps a move
      // handler, the body keeps `is-resizing`, and the pane follows a pointer nobody is
      // holding. There is no press that can end it, which makes the whole window unusable.
      document.addEventListener("pointercancel", release);
    },
    [side, min, max, onSize],
  );

  return <div className={`bp-grip is-${side}`} onPointerDown={grab} />;
}
