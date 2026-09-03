/**
 * A dialog in the middle of the window, for the one surface that earns it.
 *
 * The rail's panels are flyouts: they sit at the left edge, the canvas keeps working behind
 * them, and closing one gives the window back. A **node** is the opposite kind of thing to
 * look at. It is everything about one box — what it is, what it contains, what a run proved,
 * what a person can tune, what it can be asked to do — and at 340px against the left edge
 * that becomes one long column somebody scrolls, with the node itself hidden underneath it.
 *
 * So this is centred, wide enough for two columns, and modal: while it is open the thing
 * being read is the only thing on screen, and the scrim is the way out along with `Escape`
 * and the corner. It knows nothing about what it contains — the same rule the flyout keeps,
 * and the reason both of them are two dozen lines.
 */

import { useEffect } from "react";

export function Modal({
  title,
  /** A short word above the title: the kind, drawn in the kind's own colour. */
  badge,
  /** One line under the title: where the thing is. `""` for nothing. */
  subtitle,
  /** The badge's ink and ground, in the kind's own colours. */
  tint,
  tintBg,
  onClose,
  children,
}: {
  title: string;
  badge?: string;
  subtitle?: string;
  tint?: string;
  tintBg?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <div className="bp-modal-scrim" onClick={onClose}>
      <div
        className="bp-focus"
        role="dialog"
        aria-label={title}
        // The scrim closes; the dialog does not close because somebody clicked inside it.
        onClick={(event) => event.stopPropagation()}
      >
        <header className="bp-focus-head">
          <div className="bp-focus-name">
            {badge ? (
              <span
                className="bp-focus-badge"
                style={
                  {
                    ["--tint" as string]: tint,
                    ["--tint-bg" as string]: tintBg,
                  } as React.CSSProperties
                }
              >
                {badge}
              </span>
            ) : null}
            <span className="bp-focus-title">{title}</span>
            {subtitle ? <code className="bp-focus-where">{subtitle}</code> : null}
          </div>
          <button className="bp-icon" onClick={onClose} title="Close" aria-label="Close">
            ✕
          </button>
        </header>
        <div className="bp-focus-body">{children}</div>
      </div>
    </div>
  );
}
