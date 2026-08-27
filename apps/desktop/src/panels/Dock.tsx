/**
 * The bottom dock: the problems list and the terminal, sharing one strip of the window.
 *
 * Three ways to size it, and they answer different questions. **Dragging the top border** is
 * "I want a bit more of this"; **double-clicking the header** is "get it out of the way" and
 * back again; and collapsed is not hidden -- the header stays, because the count of what is
 * wrong is the one thing that must be visible without opening anything.
 *
 * The height is remembered in browser storage rather than in the project. It is not a fact
 * about the code, it is a fact about this person's window, and writing it into the project
 * would put one person's habit into everybody's repository (the same reasoning as the last
 * opened project, and the opposite of node positions, which *are* about the graph).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Grip } from "./Grip";

/** What is left when the dock is collapsed: exactly the header. */
const HEADER = 34;
const MIN_OPEN = 96;
const REMEMBERED = "aibuilder.dock";

/**
 * One face of the dock. `badge` is a count worth seeing without opening it -- how much is
 * wrong, how much has diverged -- which is what makes a collapsed dock still informative.
 */
export type Face = {
  id: string;
  label: string;
  badge?: number;
  content: React.ReactNode;
};

type Props = {
  faces: Face[];
  /**
   * Which face is showing, when somebody other than the person decides.
   *
   * Controlled from outside for one reason: starting a service has to be able to bring the
   * terminal forward. Everything else still goes through the tabs, and this is `""` most of
   * the time, which leaves the choice where it belongs.
   */
  face?: string;
  onFace?: (id: string) => void;
};

function stored(): number {
  const raw = Number(localStorage.getItem(REMEMBERED));
  return Number.isFinite(raw) && raw >= HEADER ? raw : 152;
}

/**
 * Which face was last open, remembered per machine.
 *
 * A fact about this window rather than about the code, so browser storage and not the
 * project -- the same reasoning as the dock's height. It exists because the workspace used
 * to unmount on every re-read, which sent the person back to the first tab several times a
 * minute; keeping it means even a reload comes back where they were.
 */
const FACE = "aibuilder.dock-face";

export function Dock({ faces, face, onFace }: Props) {
  const [tab, setTab] = useState(
    () => localStorage.getItem(FACE) ?? faces[0]?.id ?? "",
  );
  const [height, setHeight] = useState(stored);
  /** The height to come back to. Collapsing must not lose the size that was chosen. */
  const restore = useRef(Math.max(stored(), MIN_OPEN));

  const collapsed = height <= HEADER;

  const show = useCallback(
    (id: string) => {
      setTab(id);
      localStorage.setItem(FACE, id);
    },
    [],
  );

  // A face asked for from outside. It opens the dock too: being sent to a panel that is
  // folded away is being sent nowhere.
  useEffect(() => {
    if (!face) return;
    show(face);
    setHeight((now) => (now <= HEADER ? restore.current : now));
    onFace?.("");
  }, [face, show, onFace]);

  useEffect(() => {
    localStorage.setItem(REMEMBERED, String(height));
    if (height > HEADER) restore.current = height;
  }, [height]);

  // Clamped to the header rather than to zero: that is what makes dragging all the way
  // down a collapse rather than a disappearance.
  const ceiling = useCallback(() => window.innerHeight - 160, []);

  return (
    <footer className="bp-dock" style={{ height }}>
      <Grip side="bottom" min={HEADER} max={ceiling} onSize={setHeight} />

      <div
        className="bp-dock-head"
        onDoubleClick={() => setHeight(collapsed ? restore.current : HEADER)}
        title="double-click to collapse or open"
      >
        {faces.map((one) => (
          <button
            key={one.id}
            className={`bp-dock-tab${tab === one.id ? " is-on" : ""}`}
            onClick={() => {
              show(one.id);
              // Choosing a face is asking to see it, so a collapsed dock opens rather than
              // switching to something the person cannot look at.
              if (collapsed) setHeight(restore.current);
            }}
          >
            {one.label}
            {one.badge !== undefined ? (
              <span className="bp-cap-n">{one.badge}</span>
            ) : null}
          </button>
        ))}

        <button
          className="bp-icon bp-dock-fold"
          onClick={() => setHeight(collapsed ? restore.current : HEADER)}
          title={collapsed ? "Open" : "Collapse"}
        >
          {collapsed ? "▴" : "▾"}
        </button>
      </div>

      {/* Collapsed leaves the header and nothing else: the count stays readable, and the
          panel is out of the way without being gone. */}
      {collapsed ? null : (
        <div className="bp-dock-body">
          {faces.find((one) => one.id === tab)?.content ?? null}
        </div>
      )}
    </footer>
  );
}
