/**
 * The icon rail.
 *
 * Two surfaces, permanently: the graph, which is the window, and the chat, which is how the
 * graph changes. Everything the rail used to hold -- a library of blueprints, an outline, a
 * problems list, an MCP catalog, an environment editor, an evidence log -- was a face on a
 * mechanism the rebuild deleted, and a rail entry that opens onto nothing is worse than no
 * entry at all.
 *
 * What is left is the project's mark, the chat, the terminal drawer and settings. The
 * commands a person presses are on the top bar and on the node, never here: this is where
 * you go, not what you do.
 */

export type RailEntry = {
  id: string;
  label: string;
  /** A path in a 24-box, stroked. Two of them is less than an icon dependency. */
  glyph: string;
};

export const RAIL: RailEntry[] = [
  {
    id: "chat",
    label: "Chat",
    // A speech bubble. The one surface besides the graph.
    glyph: "M20 12a7 7 0 0 1-7 7H8l-4 3V12a7 7 0 0 1 7-7h2a7 7 0 0 1 7 7z",
  },
  {
    id: "terminal",
    label: "Terminal",
    // A prompt. A drawer rather than a tab: it makes no claim about the project (Q22).
    glyph: "M5 6h14v12H5zM8 10l2.5 2L8 14M13 14h3",
  },
];

export function Rail({
  open,
  onOpen,
  onProject,
  onSettings,
}: {
  open: string;
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

      {RAIL.map((entry) => (
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
        </button>
      ))}

      <button
        className="bp-rail-btn bp-rail-last"
        title="Settings"
        aria-label="Settings"
        onClick={onSettings}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <g
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
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
