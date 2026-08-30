/**
 * The left icon rail (P18.1).
 *
 * A narrow icon column pinned to the window's left edge, **not a panel**: each entry opens
 * a flyout over the canvas, and the canvas keeps the full window. The order is the
 * reference's own -- mark, `+`, nodes, chart, history, gear -- and each slot has been given
 * the thing this workspace actually has:
 *
 *   | reference     | ours                                          |
 *   | product mark  | the project's mark, and the project switcher  |
 *   | `+`           | the node library                              |
 *   | nodes glyph   | the outline                                   |
 *   | chart glyph   | problems, with its count as a badge           |
 *   | history glyph | evidence: what was proven, and by which run   |
 *   | gear          | settings                                      |
 *
 * The badge on `Problems` is the one number that must be legible without opening anything.
 * The dock used to carry it; nothing sits at the bottom of the window any more, so it sits
 * on the icon.
 */

export type RailEntry = {
  id: string;
  label: string;
  /** A path in a 24-box, stroked. Six of them is less than an icon dependency. */
  glyph: string;
  badge?: number;
};

export const RAIL: RailEntry[] = [
  { id: "library", label: "Library", glyph: "M12 5v14M5 12h14" },
  {
    id: "outline",
    label: "Outline",
    glyph: "M5 6h6v5H5zM13 13h6v5h-6zM8 11v4h5",
  },
  {
    id: "problems",
    label: "Problems",
    glyph: "M5 19V9M10 19V5M15 19v-7M20 19v-4",
  },
  {
    id: "integrations",
    label: "Integrations",
    // A plug. The one rail entry that opens a window rather than a flyout, because what it
    // holds is a catalog and a form rather than a list to glance at.
    glyph: "M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3",
  },
  {
    id: "env",
    label: "Environment",
    // A key. The one surface here that holds a value rather than describing the project.
    glyph: "M15 7a4 4 0 1 1-3.9 5H8v3H5v-3l3.1-3H11a4 4 0 0 1 4-2zm1 3.2h.01",
  },
  {
    id: "evidence",
    label: "Evidence",
    glyph: "M4 12a8 8 0 1 0 2.3-5.6M4 4v3.5h3.5M12 8v4l3 2",
  },
];

export function Rail({
  open,
  problems,
  onOpen,
  onProject,
  onSettings,
}: {
  open: string;
  problems: number;
  onOpen: (id: string) => void;
  onProject: (at: { x: number; y: number }) => void;
  onSettings: () => void;
}) {
  return (
    <nav className="bp-rail" aria-label="Workspace">
      {/* The project's mark, where the reference puts the product's. It is a button, and
          what it opens is the project switcher -- the one thing above the graph. */}
      <button
        className="bp-rail-mark"
        title="Project"
        aria-label="Project"
        onClick={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          onProject({ x: box.right + 6, y: box.top });
        }}
      >
        <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
          <path
            d="M12 3 4 7.5v9L12 21l8-4.5v-9zM4 7.5 12 12l8-4.5M12 12v9"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {RAIL.map((entry) => {
        const badge = entry.id === "problems" ? problems : 0;
        return (
          <button
            key={entry.id}
            className={`bp-rail-btn${open === entry.id ? " is-on" : ""}`}
            title={entry.label}
            aria-label={entry.label}
            onClick={() => onOpen(open === entry.id ? "" : entry.id)}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d={entry.glyph}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {/* A count and never a dot: "3 problems" and "one problem" are different
                situations, and a dot says the same thing about both. Zero draws nothing --
                a badge reading 0 is a decoration that has to be read to be dismissed. */}
            {badge > 0 ? <span className="bp-rail-badge">{badge}</span> : null}
          </button>
        );
      })}

      <button
        className="bp-rail-btn bp-rail-last"
        title="Settings"
        aria-label="Settings"
        onClick={onSettings}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            {/* Teeth around the ring. Rays out of the centre draw a sun, which is what the
                first attempt at this was. */}
            <path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z" />
            <circle cx="12" cy="12" r="3" />
          </g>
        </svg>
      </button>
    </nav>
  );
}
