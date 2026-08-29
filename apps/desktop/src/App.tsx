/**
 * The workspace.
 *
 * One `graph.read` is the whole picture -- nodes, verdicts, evidence, flow, diagnostics --
 * and every panel is a view of that one answer. There is deliberately no store of graph
 * state here: a second copy would be a second opinion, and I-1 says the code is the only
 * source of truth. **The redesign changed none of that** (P18): every surface below is a
 * view of the same call, and no button appeared whose answer the core cannot give. A
 * redesign that needed a new source of truth would be the design failing, not the
 * architecture.
 *
 * The shape is the reference's (P18.1): an icon rail and a top bar around a full-bleed
 * canvas, everything else summoned over it and dismissed. The dock is gone -- its five
 * faces went to the rail, onto the node, and into a sheet nobody has to look at.
 *
 * The one thing this owns is the layout, and it owns it the way Q13 describes: a cache of
 * where the person put things -- and now of which cards they unfolded -- written on
 * drag-end, which cannot add, remove or rename a node. Everything else is asked for and
 * rendered.
 *
 * **Observing is never automatic.** `graph.read --observe` runs the project's own tests in a
 * subprocess, so it happens because somebody pressed a button and for no other reason (P11).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Grip } from "./panels/Grip";
import { Notice } from "./panels/Notice";
import { Terminal } from "./panels/Terminal";
import { Commands } from "./panels/Commands";
import { Settings } from "./panels/Settings";
import { Canvas } from "./graph/Canvas";
import { Chat } from "./panels/Chat";
import { Welcome } from "./panels/Welcome";
import { Evidence } from "./panels/Evidence";
import { Inspector } from "./panels/Inspector";
import { Library } from "./panels/Library";
import { Problems } from "./panels/Problems";
import { Tree } from "./panels/Tree";
import { Menu, type Placed } from "./panels/Menu";
import { Rail } from "./shell/Rail";
import { TopBar } from "./shell/TopBar";
import { Flyout } from "./shell/Flyout";
import { Sheet } from "./shell/Sheet";
import {
  envDown,
  envStatus,
  envUp,
  graphCompositions,
  graphRead,
  knobSet,
  nodeConnect,
  layoutRead,
  layoutWrite,
  nodeSetTitle,
  runStart,
  runStatus,
  runStop,
  workStatus,
} from "./core/client";
import { kindRegistry, startsByKind } from "./core/registry";
import type {
  Composition,
  Environment,
  GraphRead,
  Layout,
  NodeKindInfo,
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
 * How wide the person made the inspector.
 *
 * Browser storage for the same reason as the last project: a pane width is a fact about this
 * window, not about the code. Node positions are the opposite case -- they *are* about the
 * graph -- which is why those go through `layout.write` instead.
 */
const PANE = "framestack.pane-right";

/** Light is the base now (P18.5). Dark is the exception, and it is chosen in Settings. */
const THEME = "framestack.theme";

/** Whatever the canvas must keep, so the inspector cannot be dragged over the whole window. */
const CANVAS_FLOOR = 360;

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
 * null for the length of a subprocess and **the whole workspace unmounted**.
 *
 * So the previous answer is kept until the next one arrives. `reading` says a read is in
 * flight; nothing disappears while it is. The first read of a project is the one exception —
 * there is nothing to keep — and that one still says "Reading…".
 */

/**
 * The agent reports absolute paths; a node's address is project-relative, so one has to be
 * turned into the other or the canvas lights nothing.
 */
function relative(file: string, project: string): string {
  const root = project.endsWith("/") ? project : `${project}/`;
  return file.startsWith(root) ? file.slice(root.length) : file;
}

/** The folder's own name. What the top bar calls this project, and what a person calls it. */
function nameOf(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() ?? path;
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
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem(THEME) === "dark" ? "dark" : "light"),
  );
  /** Files the agent is touching right now. The canvas lights the nodes in them. */
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [settling, setSettling] = useState(false);
  const [paneWidth, setPaneWidth] = useState(() => widthOf(PANE, 320));
  /** A repair the toolchain cannot carry out, on its way to the chat's field. */
  const [handOver, setHandOver] = useState<string | null>(null);
  /** Which rail flyout is open, or "". Nothing is docked; the canvas keeps the window. */
  const [rail, setRail] = useState("");
  /** Which face of the bottom sheet is showing, or "" for no sheet at all. */
  const [sheet, setSheet] = useState("");
  const [terminalTab, setTerminalTab] = useState("");
  const [menu, setMenu] = useState<Placed>(null);
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(null);
  /** Presses of `Agent`. A counter, because the second press of an open panel is not a close. */
  const [summon, setSummon] = useState(0);
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
  /** The registry, whole. What a node's own verbs are is its answer, never a list here. */
  const [kinds, setKinds] = useState<NodeKindInfo[]>([]);
  /** What may be connected to what (P21). The core's table, held rather than reinvented. */
  const [compositions, setCompositions] = useState<Composition[]>([]);
  /** What the compose file declares and where it stands. Null until docker has been asked. */
  const [services, setServices] = useState<Environment | null>(null);

  const pending = useRef<number | null>(null);
  const opened = useRef(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(PANE, String(paneWidth));
  }, [paneWidth]);

  const open = useCallback(async (path: string, observe: boolean) => {
    if (!path) return;
    localStorage.setItem(LAST_PROJECT, path);
    // Kept, not cleared: see the note on `Load`. A re-read that emptied the workspace is
    // what made every action flash.
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
          [id]: { ...previous[id], collapsed: !previous[id]?.collapsed },
        };
        void layoutWrite(project, next).catch(() => undefined);
        return next;
      });
    },
    [project],
  );

  /** Every knob on this card, or the first few. Beside the coordinates, for the same reason. */
  const onToggleExpand = useCallback(
    (id: string) => {
      setLayout((previous) => {
        const next = {
          ...previous,
          [id]: { ...previous[id], expanded: !previous[id]?.expanded },
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
      .then((answer) => setKinds(answer.kinds))
      .catch(() => undefined);
    // A canvas that cannot read this offers no connections at all, which is the same answer
    // as a project whose kinds compose with nothing -- and never a guess that they do.
    void graphCompositions()
      .then((answer) => setCompositions(answer.compositions))
      .catch(() => undefined);
  }, []);

  /**
   * A drag from one node to another (P21).
   *
   * It writes code and then re-reads. **Nothing draws an arrow here**: an edge appears
   * because a type now crosses a boundary, or because a run drew a flow (Q9), and a write
   * that stands while no arrow appears is information rather than a bug. A refusal is an
   * ordinary answer -- two kinds whose composition the registry does not describe get a
   * sentence naming both, and the agent is what it points at.
   */
  const onConnect = useCallback(
    async (source: string, target: string) => {
      setBusy(true);
      setRefused(null);
      try {
        const result = await nodeConnect(project, source, target);
        if (!result.ok) setRefused(result.refused ?? "the connection was refused");
        else await open(project, observed);
      } catch (error) {
        setRefused(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [project, observed, open],
  );

  const starts = startsByKind(kinds);

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
        setSheet("terminal");
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

  /**
   * The `⋮` on a card.
   *
   * Three verbs of the workspace's own, and then **whatever the registry says this kind can
   * do** -- talk to it, hand it documents, start it. Nothing about those is listed here: a
   * kind opts in by naming a way in (§5.6), so a kind that has not opted in gets no item
   * rather than one that does nothing. Choosing one selects the node, which is where the
   * buttons and their state actually live; the menu is a way in, never a second way to act.
   */
  const onMenu = useCallback(
    (id: string, at: { x: number; y: number }) => {
      const node = graph?.graph.nodes.find((one) => one.id === id);
      if (!node) return;
      const info = kinds.find((kind) => kind.name === node.kind);
      const verbs: { label: string; run: () => void }[] = [];
      const reveal = () => setSelected(id);
      if (info?.converses) verbs.push({ label: `Talk (${info.converses})`, run: reveal });
      if (info?.indexes) verbs.push({ label: `Index (${info.indexes})`, run: reveal });
      if (info?.starts) verbs.push({ label: `Start / stop (${info.starts})`, run: reveal });

      setMenu({
        x: at.x,
        y: at.y,
        items: [
          {
            section: "Node",
            label: "Rename…",
            run: () => setRenaming({ id, value: node.title ?? "" }),
          },
          { section: "Node", label: "Open code", run: () => setSelected(id) },
          {
            section: "Node",
            label: "Copy node id",
            run: () => void navigator.clipboard.writeText(id).catch(() => undefined),
          },
          ...verbs.map((verb) => ({ ...verb, section: "Verbs" })),
        ],
      });
    },
    [graph, kinds],
  );

  const rename = useCallback(async () => {
    if (!renaming) return;
    setBusy(true);
    try {
      const result = await nodeSetTitle(project, renaming.id, renaming.value);
      if (!result.ok) setRefused(result.refused ?? "the rename was refused");
      else await open(project, observed);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
      setRenaming(null);
    }
  }, [renaming, project, observed, open]);

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

  const problems = graph
    ? graph.diagnostics.length + Object.keys(graph.skipped).length
    : 0;

  const flyout = (() => {
    if (!rail) return null;
    if (rail === "library")
      return {
        title: "Library",
        body: (
          <Library
            project={project}
            // An insert wrote files into the project, so the picture is a claim about code
            // that has changed. Re-read, and never observe: the new node is unproven until
            // somebody runs something, which is the whole of I-5 through this gesture.
            onInserted={() => void open(project, observed)}
          />
        ),
      };
    if (!graph) return null;
    if (rail === "outline")
      return {
        title: "Outline",
        body: <Tree graph={graph} selected={selected} onSelect={setSelected} />,
      };
    if (rail === "problems")
      return {
        title: "Problems",
        body: <Problems graph={graph} onSelect={setSelected} />,
      };
    if (rail === "evidence")
      return {
        title: "Evidence",
        body: <Evidence graph={graph} observed={observed} onSelect={setSelected} />,
      };
    return null;
  })();

  return (
    <div className="bp-app">
      <Rail
        open={rail}
        problems={problems}
        onOpen={setRail}
        onProject={(at) =>
          setMenu({
            x: at.x,
            y: at.y,
            items: [
              { label: nameOf(project), run: () => undefined, checked: true },
              { label: "Close this project", run: () => setProject(""), destructive: true },
            ],
          })
        }
        onSettings={() => setSettling(true)}
      />

      <div className="bp-main">
        <TopBar
          name={nameOf(project)}
          observed={observed}
          reading={reading}
          running={Boolean(alive.run)}
          servicesUp={Boolean(alive.env)}
          onObserve={() => void open(project, true)}
          onRun={() => {
            const act = alive.run ? runStop : runStart;
            void act(project)
              .then(() => readAlive())
              .catch((error: unknown) =>
                setRefused(error instanceof Error ? error.message : String(error)),
              );
          }}
          onEnv={() => {
            const act = alive.env ? envDown : envUp;
            void act(project)
              .then(() => readAlive())
              .catch((error: unknown) =>
                setRefused(error instanceof Error ? error.message : String(error)),
              );
          }}
          onAgent={() => setSummon((n) => n + 1)}
        />

        {load.status === "failed" ? (
          <Notice
            tone="failed"
            label="failed"
            text={load.message}
            onClose={() => setLoad({ status: "idle" })}
          />
        ) : null}

        {/* A refusal with nothing selected used to go nowhere: `refused` was only drawn
            inside the inspector, and the cluster's own verbs -- `Run`, `Env` -- can be
            refused with no node open at all. A refusal is an answer, and an answer nobody
            is shown is the same as no answer. */}
        {refused && !node ? (
          <Notice
            tone="refused"
            label="refused"
            text={refused}
            onClose={() => setRefused(null)}
          />
        ) : null}

        <div className="bp-stage">
          {graph ? (
            <Canvas
              graph={graph}
              layout={layout}
              litFiles={touched}
              runningKinds={runningKinds}
              selected={selected}
              onSelect={setSelected}
              onMove={onMove}
              onToggleCollapse={onToggleCollapse}
              onToggleExpand={onToggleExpand}
              onKnob={onKnob}
              onMenu={onMenu}
              onConnect={(source, target) => void onConnect(source, target)}
              compositions={compositions}
            />
          ) : (
            <div className="bp-empty bp-empty-full">
              {load.status === "loading"
                ? "Reading…"
                : "This project has nothing on its graph yet."}
            </div>
          )}

          {/* Over the canvas, not beside it: closing gives the whole window back. */}
          {flyout ? (
            <Flyout title={flyout.title} onClose={() => setRail("")}>
              {flyout.body}
            </Flyout>
          ) : null}

          {/* No selection, no panel. It used to hold two dead tabs and the words "Select a
              node." -- a column of nothing, taking a fifth of the window from the canvas. */}
          {graph && node ? (
            <div className="bp-inspector-wrap" style={{ width: paneWidth }}>
              <Grip
                side="right"
                min={260}
                max={() => window.innerWidth - CANVAS_FLOOR}
                onSize={setPaneWidth}
              />
              <Inspector
                project={project}
                graph={graph}
                node={node}
                busy={busy}
                refused={refused}
                running={Boolean(alive[starts[node.kind] ?? ""])}
                services={services}
                onKnob={onKnob}
                onDismiss={() => setRefused(null)}
                onActed={() => {
                  void readAlive();
                  void open(project, observed);
                }}
                onWritten={() => void open(project, observed)}
                onHandOver={(request) => {
                  setHandOver(request);
                  setSummon((n) => n + 1);
                }}
                onClose={() => setSelected(null)}
              />
            </div>
          ) : null}
        </div>

        {/* Summoned and dismissed. Nothing sits at the bottom of the window by default:
            the reference gives the canvas the whole window and so do we (P18.1). */}
        {sheet ? (
          <Sheet
            face={sheet}
            onFace={setSheet}
            onClose={() => setSheet("")}
            faces={[
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
                // The commands the project already has (P17.6). Not a node: a front end is
                // run, not modelled, and nothing here turns a colour (Q20).
                id: "commands",
                label: "Commands",
                content: <Commands project={project} />,
              },
            ]}
          />
        ) : null}

        {/* The one thing that is always reachable without opening a panel: a shell and the
            project's commands are how a person gets out of a corner the buttons cannot. */}
        {!sheet ? (
          <button className="bp-sheet-summon" onClick={() => setSheet("terminal")}>
            Terminal
          </button>
        ) : null}
      </div>

      {/* Folded until `Agent` is pressed: it is how a project gets its first line of code,
          and it is now a button in the cluster rather than a panel nobody asked for. */}
      <Chat
        project={project}
        summon={summon}
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

      <Menu at={menu} onClose={() => setMenu(null)} />

      {renaming ? (
        <div className="bp-modal-scrim" onClick={() => setRenaming(null)}>
          <div className="bp-modal" onClick={(event) => event.stopPropagation()}>
            <div className="bp-modal-title">Rename node</div>
            {/* The title and nothing else: an id is an address other code refers to, and a
                rename that moved it would break every reference silently. `node.set_title`
                writes the one thing that is safe to change. */}
            <input
              className="bp-field"
              autoFocus
              value={renaming.value}
              onChange={(event) =>
                setRenaming({ ...renaming, value: event.target.value })
              }
              onKeyDown={(event) => {
                if (event.key === "Enter") void rename();
                if (event.key === "Escape") setRenaming(null);
              }}
            />
            <div className="bp-modal-acts">
              <button className="bp-btn" onClick={() => setRenaming(null)}>
                Cancel
              </button>
              <button className="bp-btn is-primary" disabled={busy} onClick={() => void rename()}>
                Rename
              </button>
            </div>
          </div>
        </div>
      ) : null}

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
