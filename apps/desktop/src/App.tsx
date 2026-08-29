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
import {
  envStatus,
  graphRead,
  knobSet,
  layoutRead,
  layoutWrite,
  runStatus,
  workStatus,
} from "./core/client";
import { kindRegistry, startsByKind } from "./core/registry";
import type {
  Environment,
  GraphRead,
  Layout,
  Placement,
  RunState,
} from "./core/types";

/** How long a drag has to be over before the layout is stored. */
const SETTLE_MS = 400;

/**
 * How often the workspace asks which processes are alive.
 *
 * **Asked, never assumed, and never pushed** (P13). Whether the application is up is not in
 * the code, so the graph cannot carry it — and it changes for reasons that have nothing to do
 * with this window: a person's own terminal, a crash, a port already taken. Both reads are a
 * state file and a `kill(pid, 0)`, which is cheap enough to ask for on a clock and honest
 * enough to draw a node's colour from.
 */
const ALIVE_MS = 2000;

/**
 * The last project, remembered per machine.
 *
 * Browser storage rather than a file, because this is not a fact about any project -- it
 * is a fact about this person's last session, and writing it into a project would put one
 * person's habit into everybody's repository.
 */
const LAST_PROJECT = "framestack.last-project";

/**
 * How wide the person made the side panes.
 *
 * Browser storage for the same reason as the last project: a pane width is a fact about this
 * window, not about the code, and writing it into the project would put one person's habit
 * into everybody's repository. Node positions are the opposite case -- they *are* about the
 * graph -- which is why those go through `layout.write` instead.
 */
const PANES = { left: "framestack.pane-left", right: "framestack.pane-right" };

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
 * Why a re-read no longer clears the picture.
 *
 * Every action here ends with `open(project, observed)` — a knob written, a service started,
 * a route called, a repair applied — because what is on screen is a claim about older code.
 * That is right. What was wrong is that the re-read went through `loading`, so `graph` became
 * null for the length of a subprocess and **the whole workspace unmounted**: the canvas, the
 * panes, and the dock with whichever face the person was reading. It came back with the dock
 * on its first tab and the screen flashing once per press.
 *
 * So the previous answer is kept until the next one arrives. `busy` says a read is in flight;
 * nothing disappears while it is. The first read of a project is the one exception — there is
 * nothing to keep — and that one still says "Reading…".
 */

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
  /** A `graph.read` is in flight. The picture stays; this is what says it is being checked. */
  const [reading, setReading] = useState(false);
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
  /**
   * Which processes are alive, by the verb family that starts them.
   *
   * The one fact on this screen that is **not** a projection of the code (I-1 is untouched):
   * a graph says what a project is, and a pid says what is happening on this machine right
   * now. Kept apart from the graph for exactly that reason, and asked for on a clock rather
   * than inferred from having pressed a button — the person's own terminal can stop a server
   * this window started.
   */
  const [alive, setAlive] = useState<Record<string, boolean>>({});
  /**
   * The two processes this toolchain started, with their pid and port.
   *
   * Kept apart from `alive` because they answer different questions: `alive` is "is this
   * kind of node running", which the canvas draws and the buttons switch on, and this is
   * "which process, where", which the terminal prints in its status line. Docker has no
   * entry here on purpose — a compose project is several containers and no pid of ours.
   */
  const [processes, setProcesses] = useState<Record<string, RunState>>({});
  /** Which verb family starts each kind, from the registry. Never a list of our own. */
  const [starts, setStarts] = useState<Record<string, string>>({});
  /** What the compose file declares and where it stands. Null until docker has been asked. */
  const [services, setServices] = useState<Environment | null>(null);
  /**
   * A dock face, and a terminal tab inside it, asked for by something that just happened.
   *
   * Starting a service opens its output: a person who pressed Run is asking "did it come
   * up?", and making them go and find the answer is making them ask twice. Requests rather
   * than modes -- each is cleared the moment it has been honoured, so nothing here takes the
   * choice of panel away from the person for longer than one event.
   */
  const [face, setFace] = useState("");
  const [terminalTab, setTerminalTab] = useState("");

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
    // Kept, not cleared: see the note on `Load`. A re-read that emptied the workspace is
    // what made every action flash and reset the dock.
    setLoad((previous) =>
      previous.status === "ready" ? previous : { status: "loading" },
    );
    setReading(true);
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
      // A failed re-read is a notice, never an empty screen: what is drawn was true a moment
      // ago, and throwing it away tells the person less than keeping it and saying so.
      setLoad((previous) =>
        previous.status === "ready"
          ? previous
          : {
              status: "failed",
              message: error instanceof Error ? error.message : String(error),
            },
      );
      setRefused(error instanceof Error ? error.message : String(error));
    } finally {
      setReading(false);
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

  // The registry, once. A canvas that cannot read it draws no running state at all, which
  // is the same answer as a project whose kinds start nothing.
  useEffect(() => {
    void kindRegistry()
      .then((kinds) => setStarts(startsByKind(kinds)))
      .catch(() => undefined);
  }, []);

  const readAlive = useCallback(async () => {
    if (!project) return;
    // All three, together, and failures cost the colour rather than the workspace: this is a
    // decoration on a node, and a core that cannot answer must not empty the screen.
    const [application, worker, environment] = await Promise.all([
      runStatus(project).catch(() => null),
      workStatus(project).catch(() => null),
      envStatus(project).catch(() => null),
    ]);
    setProcesses({
      run: application?.state ?? null,
      work: worker?.state ?? null,
    });
    setServices(environment?.environment ?? null);
    setAlive({
      run: Boolean(application?.state),
      work: Boolean(worker?.state),
      // **Docker's own answer, not a port that responds.** A compose project is up when its
      // containers are, which is what the button started; reachability is a different claim
      // and belongs to the service rows, where it can be said about one service at a time.
      env: Boolean(environment?.environment.up),
    });
  }, [project]);

  useEffect(() => {
    void readAlive();
    const clock = window.setInterval(() => void readAlive(), ALIVE_MS);
    return () => window.clearInterval(clock);
  }, [readAlive]);

  // A process that has just appeared brings its log forward -- **once**, on the edge. A
  // check on every tick would drag the person back to the terminal each time they went
  // somewhere else while a server was up.
  const wasAlive = useRef<Record<string, boolean>>({});
  useEffect(() => {
    for (const [family, tab] of [
      ["run", "app"],
      ["work", "worker"],
    ] as const) {
      const up = Boolean(alive[family]);
      if (up && !wasAlive.current[family]) {
        setFace("terminal");
        setTerminalTab(tab);
      }
      wasAlive.current[family] = up;
    }
  }, [alive]);

  /** Is this node's kind the sort of thing that starts, and is that thing up right now? */
  const runningKinds = new Set(
    Object.entries(starts)
      .filter(([, family]) => alive[family])
      .map(([kind]) => kind),
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
          Framestack <em>AI Builder</em>
        </span>

        {/* The bar carries no readouts and no verbs of its own any more. The project's path
            was for whoever was building this; `Read` did what opening, an agent turn and
            `Observe` already do; and observing and repairing are lists to read rather than
            buttons to press and forget, so they are faces of the dock. What stays is the one
            thing that is true of the whole workspace: whether anything has been run. */}
        {graph ? (
          // Said as a fact about what has happened rather than as a state a project is in:
          // "not observed" reads like a fault, and a project that has just been opened has
          // nothing wrong with it -- nobody has run anything yet, which is different.
          <span
            className="bp-live"
            title={
              observed
                ? "the project's tests were run for this picture"
                : "nothing has been run yet -- Observe is where green comes from"
            }
          >
            <span className={`bp-livedot${observed ? "" : " is-off"}`} />
            {observed ? "observed" : "nothing run yet"}
            {reading ? " · reading…" : ""}
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
          style={{
            gridTemplateColumns: node
              ? `${leftWidth}px 1fr ${rightWidth}px`
              : `${leftWidth}px 1fr`,
          }}
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
            runningKinds={runningKinds}
            selected={selected}
            onSelect={setSelected}
            onMove={onMove}
            onToggleCollapse={onToggleCollapse}
          />

          {/* No selection, no pane. It held two dead tabs and the words "Select a node." --
              a column of nothing, taking a fifth of the window away from the canvas. The
              canvas takes the space back until there is something to say. */}
          {node ? (
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
                  >
                    Code
                  </button>
                </div>

                {tab === "code" ? (
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
                    <Actions
                      project={project}
                      node={node}
                      running={Boolean(alive[starts[node.kind] ?? ""])}
                      services={services}
                      onActed={() => {
                        void readAlive();
                        void open(project, observed);
                      }}
                    />
                  </>
                )}
              </div>
            </aside>
          ) : null}

          <Dock
            face={face}
            onFace={setFace}
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
                    busy={reading}
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
                content: (
                  <Terminal
                    project={project}
                    processes={processes}
                    focus={terminalTab}
                    onFocused={() => setTerminalTab("")}
                  />
                ),
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
