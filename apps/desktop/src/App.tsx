/**
 * The workspace.
 *
 * One `graph.read` is the whole picture -- nodes, verdicts, evidence, flow, diagnostics --
 * and every panel is a view of that one answer. There is deliberately no store of graph
 * state here: a second copy would be a second opinion, and I-1 says the code is the only
 * source of truth.
 *
 * The one thing this owns is the layout, and it owns it the way Q13 describes: a cache of
 * where the person put things, written on drag-end, which cannot add, remove or rename a
 * node. Everything else is asked for and rendered.
 *
 * **Observing is never automatic.** `graph.read --observe` runs the project's own tests in a
 * subprocess, so it happens because somebody pressed a button and for no other reason (P11).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Actions } from "./panels/Actions";
import { Dock } from "./panels/Dock";
import { Grip } from "./panels/Grip";
import { Notice } from "./panels/Notice";
import { Terminal } from "./panels/Terminal";
import { Code } from "./panels/Code";
import { Repairs } from "./panels/Repairs";
import { Canvas } from "./graph/Canvas";
import { Chat } from "./panels/Chat";
import { Welcome } from "./panels/Welcome";
import { Details } from "./panels/Details";
import { Problems } from "./panels/Problems";
import { Tree } from "./panels/Tree";
import { graphRead, knobSet, layoutRead, layoutWrite } from "./core/client";
import type { GraphRead, Layout, Placement } from "./core/types";

/** How long a drag has to be over before the layout is stored. */
const SETTLE_MS = 400;

/**
 * The last project, remembered per machine.
 *
 * Browser storage rather than a file, because this is not a fact about any project -- it
 * is a fact about this person's last session, and writing it into a project would put one
 * person's habit into everybody's repository.
 */
const LAST_PROJECT = "aibuilder.last-project";

/**
 * How wide the person made the side panes.
 *
 * Browser storage for the same reason as the last project: a pane width is a fact about this
 * window, not about the code, and writing it into the project would put one person's habit
 * into everybody's repository. Node positions are the opposite case -- they *are* about the
 * graph -- which is why those go through `layout.write` instead.
 */
const PANES = { left: "aibuilder.pane-left", right: "aibuilder.pane-right" };

/** Whatever the canvas must keep, so a pane cannot be dragged over the whole window. */
const CANVAS_FLOOR = 320;

function widthOf(key: string, fallback: number): number {
  const raw = Number(localStorage.getItem(key));
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

type Load =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; graph: GraphRead }
  | { status: "failed"; message: string };

/**
 * The agent reports absolute paths; a node's address is project-relative, so one has to be
 * turned into the other or the canvas lights nothing.
 */
function relative(file: string, project: string): string {
  const root = project.endsWith("/") ? project : `${project}/`;
  return file.startsWith(root) ? file.slice(root.length) : file;
}

export default function App() {
  const [project, setProject] = useState(
    () => localStorage.getItem(LAST_PROJECT) ?? "",
  );
  const [load, setLoad] = useState<Load>({ status: "idle" });
  const [layout, setLayout] = useState<Layout>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [observed, setObserved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  /** Files the agent is touching right now. The canvas lights the nodes in them. */
  const [touched, setTouched] = useState<Set<string>>(new Set());
  /** Which face of the selection is showing: what it is set to, or what it is made of. */
  const [tab, setTab] = useState<"details" | "code">("details");
  const [repairing, setRepairing] = useState(false);
  const [leftWidth, setLeftWidth] = useState(() => widthOf(PANES.left, 216));
  const [rightWidth, setRightWidth] = useState(() => widthOf(PANES.right, 258));
  /** A repair the toolchain cannot carry out, on its way to the chat's field. */
  const [handOver, setHandOver] = useState<string | null>(null);

  const pending = useRef<number | null>(null);
  const opened = useRef(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(PANES.left, String(leftWidth));
    localStorage.setItem(PANES.right, String(rightWidth));
  }, [leftWidth, rightWidth]);

  const open = useCallback(async (path: string, observe: boolean) => {
    if (!path) return;
    localStorage.setItem(LAST_PROJECT, path);
    setLoad({ status: "loading" });
    setRefused(null);
    try {
      // The layout is asked for beside the graph, never derived from it: the graph says
      // what exists, the cache says where it was put, and neither answers the other's
      // question.
      const [graph, stored] = await Promise.all([
        graphRead(path, observe),
        layoutRead(path),
      ]);
      setLayout(stored.layout);
      setLoad({ status: "ready", graph });
      setObserved(observe);
    } catch (error) {
      setLoad({
        status: "failed",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }, []);

  // Reopen what was open last, and read only -- never observe. Running a stranger's tests
  // because a window came back is exactly the side effect P11 forbids.
  useEffect(() => {
    if (opened.current || !project) return;
    opened.current = true;
    void open(project, false);
  }, [project, open]);

  /** Store where things are, once the drag has settled. */
  const onMove = useCallback(
    (moved: Record<string, Placement>) => {
      setLayout((previous) => {
        const next = { ...previous, ...moved };
        if (pending.current !== null) window.clearTimeout(pending.current);
        pending.current = window.setTimeout(() => {
          // A layout that cannot be stored costs the arrangement, never the session -- but
          // it must say so rather than losing the person's work in silence.
          void layoutWrite(project, next).catch((error: unknown) =>
            setRefused(error instanceof Error ? error.message : String(error)),
          );
        }, SETTLE_MS);
        return next;
      });
    },
    [project],
  );

  const onToggleCollapse = useCallback(
    (id: string) => {
      setLayout((previous) => {
        // Collapsed and nothing else. A frame has no position to store, and inventing a
        // 0,0 for one is how a collapsed group ends up in the corner of the canvas.
        const next = {
          ...previous,
          [id]: { collapsed: !previous[id]?.collapsed },
        };
        void layoutWrite(project, next).catch(() => undefined);
        return next;
      });
    },
    [project],
  );

  const onKnob = useCallback(
    async (node: string, knob: string, value: unknown) => {
      setBusy(true);
      setRefused(null);
      try {
        const result = await knobSet(project, node, knob, value);
        // A refusal is a normal answer to a normal question -- the panel says why and the
        // value stays what it was. Only a write that landed changes the graph.
        if (!result.ok) setRefused(result.refused ?? "the write was refused");
        else await open(project, observed);
      } catch (error) {
        setRefused(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [project, observed, open],
  );

  const graph = load.status === "ready" ? load.graph : null;

  // No project, no workspace. The path field it replaces was a developer's affordance --
  // the first thing a person needs is a way in, not a text box.
  if (!project) {
    return (
      <Welcome
        recent={localStorage.getItem(LAST_PROJECT)}
        onOpen={(path) => {
          opened.current = true;
          setProject(path);
          void open(path, false);
        }}
      />
    );
  }

  const node =
    graph?.graph.nodes.find((candidate) => candidate.id === selected) ?? null;
  const reasonFor = (id: string | null) =>
    id ? (graph?.observations[id]?.detail ?? graph?.skipped[id] ?? "") : "";

  return (
    <div className="bp-app">
      <header className="bp-bar">
        <span className="bp-brand">
          Awesome <em>AI Builder</em>
        </span>

        <span className="bp-project">{project}</span>
        <button className="bp-btn" onClick={() => void open(project, false)}>
          Read
        </button>
        {/* Running the project is an action, never a side effect of looking at it. */}
        <button
          className="bp-btn"
          onClick={() => void open(project, true)}
          title="runs the project"
        >
          Observe
        </button>

        {graph ? (
          <span className="bp-live">
            <span className={`bp-livedot${observed ? "" : " is-off"}`} />
            {observed ? "observed" : "not observed"}
          </span>
        ) : null}

        {/* Divergence is detected against the snapshot, never by watching files (I-6), so
            this is a dialog somebody opens rather than something that interrupts them. */}
        <button
          className="bp-btn"
          onClick={() => setRepairing(true)}
          title="what diverged"
        >
          Repair
        </button>

        <button
          className="bp-btn"
          onClick={() => setProject("")}
          title="close this project"
        >
          Close
        </button>
        <button
          className="bp-btn bp-theme"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "Light" : "Dark"}
        </button>
      </header>

      {load.status === "failed" ? (
        <Notice
          tone="failed"
          label="failed"
          text={load.message}
          onClose={() => setLoad({ status: "idle" })}
        />
      ) : null}

      {graph ? (
        <div
          className="bp-grid"
          style={{ gridTemplateColumns: `${leftWidth}px 1fr ${rightWidth}px` }}
        >
          <aside className="bp-pane bp-pane-left">
            <Grip
              side="left"
              min={150}
              max={() => window.innerWidth - rightWidth - CANVAS_FLOOR}
              onSize={setLeftWidth}
            />
            <div className="bp-pane-scroll">
              <div className="bp-cap">
                Project{" "}
                <span className="bp-cap-n">{graph.graph.nodes.length}</span>
              </div>
              <Tree graph={graph} selected={selected} onSelect={setSelected} />
            </div>
          </aside>

          <Canvas
            graph={graph}
            layout={layout}
            litFiles={touched}
            selected={selected}
            onSelect={setSelected}
            onMove={onMove}
            onToggleCollapse={onToggleCollapse}
          />

          <aside className="bp-pane bp-pane-right">
            <Grip
              side="right"
              min={190}
              max={() => window.innerWidth - leftWidth - CANVAS_FLOOR}
              onSize={setRightWidth}
            />
            <div className="bp-pane-scroll">
              <div className="bp-tabs">
                <button
                  className={`bp-tab${tab === "details" ? " is-on" : ""}`}
                  onClick={() => setTab("details")}
                >
                  Details
                </button>
                <button
                  className={`bp-tab${tab === "code" ? " is-on" : ""}`}
                  onClick={() => setTab("code")}
                  disabled={!node}
                >
                  Code
                </button>
              </div>

              {tab === "code" && node ? (
                <Code
                  project={project}
                  node={node.id}
                  onWritten={() => void open(project, observed)}
                />
              ) : (
                <>
                  <Details
                    node={node}
                    reason={reasonFor(selected)}
                    busy={busy}
                    refused={refused}
                    onKnob={onKnob}
                    onDismiss={() => setRefused(null)}
                  />
                  {node ? (
                    <Actions
                      project={project}
                      node={node}
                      onActed={() => void open(project, observed)}
                    />
                  ) : null}
                </>
              )}
            </div>
          </aside>

          <Dock
            count={graph.diagnostics.length + Object.keys(graph.skipped).length}
            problems={<Problems graph={graph} onSelect={setSelected} />}
            terminal={<Terminal project={project} />}
          />
        </div>
      ) : (
        <div className="bp-empty bp-empty-full">
          {load.status === "loading"
            ? "Reading…"
            : "This project has nothing on its graph yet."}
        </div>
      )}

      {/* Always docked, project or not: it is how a project gets its first line of code. */}
      <Chat
        project={project}
        onTouch={(files) =>
          setTouched(new Set(files.map((file) => relative(file, project))))
        }
        onSettled={() => {
          setTouched(new Set());
          void open(project, observed);
        }}
        handOver={handOver}
        onHandedOver={() => setHandOver(null)}
      />

      {repairing ? (
        <Repairs
          project={project}
          onDone={() => void open(project, observed)}
          onClose={() => setRepairing(false)}
          onHandOver={(request) => {
            setHandOver(request);
            setRepairing(false);
          }}
        />
      ) : null}
    </div>
  );
}
