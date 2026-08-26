/**
 * A menu of our own, where the browser's would have been.
 *
 * This is a desktop application. A "Reload / Back / Inspect" menu on a node is the frame
 * showing through the picture -- it offers verbs that belong to a browser and mean nothing
 * here, and it hides the two that do.
 *
 * Placed at the pointer and clamped to the window, closed by a press anywhere else, by
 * Escape, or by choosing something. It is deliberately not a component that knows what any
 * of its items do: the caller supplies the verbs, because a menu that knew about sessions
 * would have to be rewritten the first time something else needed one.
 */

import { useEffect, useRef, useState } from "react";

export type Item = {
  label: string;
  run: () => void;
  /** A verb that destroys something is marked, so a slip is a slip and not a surprise. */
  destructive?: boolean;
};

export type Placed = { x: number; y: number; items: Item[] } | null;

export function Menu({ at, onClose }: { at: Placed; onClose: () => void }) {
  const box = useRef<HTMLDivElement | null>(null);
  const [nudged, setNudged] = useState({ x: 0, y: 0 });

  // Measured after it is drawn, because how much it overhangs is not known before then.
  useEffect(() => {
    if (!at || !box.current) return;
    const size = box.current.getBoundingClientRect();
    setNudged({
      x: Math.min(0, window.innerWidth - (at.x + size.width) - 8),
      y: Math.min(0, window.innerHeight - (at.y + size.height) - 8),
    });
  }, [at]);

  useEffect(() => {
    if (!at) return;
    const away = () => onClose();
    const key = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", key);
    };
  }, [at, onClose]);

  if (!at) return null;

  return (
    <div
      ref={box}
      className="bp-menu"
      style={{ left: at.x + nudged.x, top: at.y + nudged.y }}
      // The press that opens it must not immediately be the press that closes it.
      onPointerDown={(event) => event.stopPropagation()}
    >
      {at.items.map((item) => (
        <button
          key={item.label}
          className={`bp-menu-item${item.destructive ? " is-destructive" : ""}`}
          onClick={() => {
            onClose();
            item.run();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
