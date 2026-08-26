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
import { Commands } from "./panels/Commands";
import { Code } from "./panels/Code";
import { Observe } from "./panels/Observe";
import { Repairs } from "./panels/Repairs";
import { Settings } from "./panels/Settings";
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
  const [settling, setSettling] = useState(false);
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

        {/* The bar carries no readouts and no verbs of its own any more. The project's path
            was for whoever was building this; `Read` did what opening, an agent turn and
            `Observe` already do; and observing and repairing are lists to read rather than
            buttons to press and forget, so they are faces of the dock. What stays is the one
            thing that is true of the whole workspace: whether anything has been run. */}
        {graph ? (
          <span className="bp-live">
            <span className={`bp-livedot${observed ? "" : " is-off"}`} />
            {observed ? "observed" : "not observed"}
          </span>
        ) : null}

        {/* A gear and nothing round it: settings are not a verb of the workspace, and a
            bordered button among no other buttons reads as the bar's one action. */}
        <button
          className="bp-gear"
          onClick={() => setSettling(true)}
          title="Settings"
          aria-label="Settings"
        >
          <svg
            viewBox="0 0 24 24"
            width="17"
            height="17"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            {/* Teeth around the ring. Rays out of the centre draw a sun, which is what the
                first attempt at this was. */}
            <path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
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
            faces={[
              {
                id: "problems",
                label: "Problems",
                badge:
                  graph.diagnostics.length + Object.keys(graph.skipped).length,
                content: <Problems graph={graph} onSelect={setSelected} />,
              },
              {
                // Where green comes from (I-5), and a face rather than a bar button because
                // the evidence is a list to read, not a verb to press and forget.
                id: "observe",
                label: "Observe",
                content: (
                  <Observe
                    graph={graph}
                    observed={observed}
                    busy={load.status === "loading"}
                    onRun={() => void open(project, true)}
                    onSelect={setSelected}
                  />
                ),
              },
              {
                id: "repair",
                label: "Repair",
                content: (
                  <Repairs
                    project={project}
                    onDone={() => void open(project, observed)}
                    onHandOver={setHandOver}
                  />
                ),
              },
              {
                id: "terminal",
                label: "Terminal",
                content: <Terminal project={project} />,
              },
              {
                // The commands the project already has (P17.6). A face and not a node:
                // a front end is run, not modelled, and nothing here turns a colour (Q20).
                id: "commands",
                label: "Commands",
                content: <Commands project={project} />,
              },
            ]}
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

      {settling ? (
        <Settings
          project={project}
          theme={theme}
          onTheme={setTheme}
          onCloseProject={() => {
            setSettling(false);
            setProject("");
          }}
          onClose={() => setSettling(false)}
        />
      ) : null}
    </div>
  );
}
