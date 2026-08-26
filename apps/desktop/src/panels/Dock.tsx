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

type Tab = "problems" | "terminal";

type Props = {
  problems: React.ReactNode;
  terminal: React.ReactNode;
  /** How many addressed things are wrong. Shown on the tab, so a collapsed dock still says. */
  count: number;
};

function stored(): number {
  const raw = Number(localStorage.getItem(REMEMBERED));
  return Number.isFinite(raw) && raw >= HEADER ? raw : 152;
}

export function Dock({ problems, terminal, count }: Props) {
  const [tab, setTab] = useState<Tab>("problems");
  const [height, setHeight] = useState(stored);
  /** The height to come back to. Collapsing must not lose the size that was chosen. */
  const restore = useRef(Math.max(stored(), MIN_OPEN));

  const collapsed = height <= HEADER;

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
        <button
          className={`bp-dock-tab${tab === "problems" ? " is-on" : ""}`}
          onClick={() => {
            setTab("problems");
            if (collapsed) setHeight(restore.current);
          }}
        >
          Problems <span className="bp-cap-n">{count}</span>
        </button>
        <button
          className={`bp-dock-tab${tab === "terminal" ? " is-on" : ""}`}
          onClick={() => {
            setTab("terminal");
            if (collapsed) setHeight(restore.current);
          }}
        >
          Terminal
        </button>

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
          {tab === "problems" ? problems : terminal}
        </div>
      )}
    </footer>
  );
}
