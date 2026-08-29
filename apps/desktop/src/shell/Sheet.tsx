/**
 * The bottom sheet: the terminal and the project's commands, summoned and dismissed.
 *
 * The dock is deleted (P18.1). Its five faces went where each of them belonged -- problems
 * and evidence to the rail, observe and repairs onto the node -- and these two are what is
 * left: a shell a person types into, and the commands the project already declares. Neither
 * is a view of the graph, and neither has anything to say when nobody is looking at it.
 *
 * So **nothing sits at the bottom of the window by default.** The reference gives the canvas
 * the whole window and so do we; this appears because somebody asked for it, or because
 * something they started has output to show, and it goes away again.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Grip } from "../panels/Grip";

const MIN = 140;
const REMEMBERED = "framestack.sheet";

export type SheetFace = { id: string; label: string; content: React.ReactNode };

function stored(): number {
  const raw = Number(localStorage.getItem(REMEMBERED));
  return Number.isFinite(raw) && raw >= MIN ? raw : 240;
}

export function Sheet({
  faces,
  face,
  onFace,
  onClose,
}: {
  faces: SheetFace[];
  face: string;
  onFace: (id: string) => void;
  onClose: () => void;
}) {
  const [height, setHeight] = useState(stored);
  const ceiling = useCallback(() => window.innerHeight - 200, []);
  const first = useRef(true);

  useEffect(() => {
    localStorage.setItem(REMEMBERED, String(height));
  }, [height]);

  // Focus is the caller's business, not ours: it opens the sheet on the face it wants.
  useEffect(() => {
    first.current = false;
  }, []);

  const showing = faces.find((one) => one.id === face) ?? faces[0];

  return (
    <section className="bp-sheet" style={{ height }}>
      <Grip side="bottom" min={MIN} max={ceiling} onSize={setHeight} />
      <header className="bp-sheet-head">
        {faces.map((one) => (
          <button
            key={one.id}
            className={`bp-sheet-tab${showing?.id === one.id ? " is-on" : ""}`}
            onClick={() => onFace(one.id)}
          >
            {one.label}
          </button>
        ))}
        <button className="bp-icon bp-sheet-close" onClick={onClose} title="Close" aria-label="Close">
          ✕
        </button>
      </header>
      <div className="bp-sheet-body">{showing?.content ?? null}</div>
    </section>
  );
}
