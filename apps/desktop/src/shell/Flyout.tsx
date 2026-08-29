/**
 * A panel over the canvas, opened from the rail.
 *
 * The reference keeps **no permanent column**: everything the rail opens floats over the
 * canvas and closing it gives the canvas the whole window back. That is the opposite of
 * what this workspace grew into -- a panel per phase, docked forever, each one taking a
 * fifth of the screen whether or not anybody was reading it.
 *
 * It knows nothing about what it contains. A flyout that knew it held diagnostics would be
 * rewritten the first time something else needed one.
 */

import { useEffect } from "react";

export function Flyout({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  // Escape closes it. On a canvas that fills the window, a panel with no keyboard way out
  // is a panel a person has to go and find the corner of.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <aside className="bp-flyout" role="dialog" aria-label={title}>
      <header className="bp-flyout-head">
        <span className="bp-flyout-title">{title}</span>
        <button className="bp-icon" onClick={onClose} title="Close" aria-label="Close">
          ✕
        </button>
      </header>
      <div className="bp-flyout-body">{children}</div>
    </aside>
  );
}
