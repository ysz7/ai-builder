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

import { Fragment, useEffect, useRef, useState } from "react";

export type Item = {
  label: string;
  run: () => void;
  /** A verb that destroys something is marked, so a slip is a slip and not a surprise. */
  destructive?: boolean;
  /**
   * A heading drawn before this item, where it starts a new group.
   *
   * The menu still does not know what its items mean -- it compares the heading with the one
   * before it and draws a line when they differ. Which items belong together is the caller's
   * statement, not something inferred here.
   */
  section?: string;
  /** Shown as the one in force. A menu of settings has to say what the setting *is*. */
  checked?: boolean;
};

export type Placed = { x: number; y: number; items: Item[] } | null;

/** How close to the window's edge a menu may come. */
const MARGIN = 8;

export function Menu({ at, onClose }: { at: Placed; onClose: () => void }) {
  const box = useRef<HTMLDivElement | null>(null);
  const [nudged, setNudged] = useState({ x: 0, y: 0 });

  // Measured after it is drawn, because how much it overhangs is not known before then.
  useEffect(() => {
    if (!at || !box.current) return;
    const size = box.current.getBoundingClientRect();
    setNudged({
      x: Math.min(0, window.innerWidth - (at.x + size.width) - 8),
      // Nudged up to fit, but never past the top of the window. A menu with more entries
      // than the window is tall cannot be nudged into view at all -- it would be pulled off
      // the top instead -- so the pull is floored here and the list scrolls inside itself.
      y: Math.max(MARGIN - at.y, Math.min(0, window.innerHeight - (at.y + size.height) - MARGIN)),
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
      {at.items.map((item, index) => (
        <Fragment key={`${item.section ?? ""}/${item.label}`}>
          {item.section && item.section !== at.items[index - 1]?.section ? (
            <div className="bp-menu-head">{item.section}</div>
          ) : null}
          <button
            className={`bp-menu-item${item.destructive ? " is-destructive" : ""}${
              item.checked ? " is-checked" : ""
            }`}
            onClick={() => {
              onClose();
              item.run();
            }}
          >
            {/* A fixed column either way, so choosing does not shift the list under
                the pointer that is still over it. The label is its own box beside that
                column rather than text flowing after it: an item long enough to wrap --
                "Ask before running commands" -- used to put its second line underneath the
                tick, which reads as a different item starting. */}
            <span className="bp-menu-tick" aria-hidden="true">
              {item.checked ? "✓" : ""}
            </span>
            <span className="bp-menu-label">{item.label}</span>
          </button>
        </Fragment>
      ))}
    </div>
  );
}
