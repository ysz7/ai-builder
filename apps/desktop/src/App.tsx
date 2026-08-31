/**
 * The workspace.
 *
 * Two surfaces, permanently: the graph, which is the window, and the chat, which is how the
 * graph changes. Everything else that used to be here -- a blueprint library, a problems
 * list, an MCP catalog, an environment editor, an evidence log, a `Use` tab -- was a face on
 * a mechanism the rebuild deleted, and a panel that opens onto nothing is worse than no panel.
 *
 * The shape is the reference's: an icon rail and a top bar around a full-bleed canvas,
 * everything else summoned over it and dismissed. **Nothing here is a store of graph state.**
 * The graph is one answer from the core, held for as long as it takes to draw and asked for
 * again whenever the project might have changed -- which in Phase 1 means whenever the chat
 * has finished a turn. A copy that outlived the read would be a second opinion, and the code
 * is the only source of truth.
 *
 * The one thing this owns is the layout, and it owns it the way Q13 describes: a cache of
 * where the person put things and whether a system is unfolded, written on drag-end, which
 * **cannot add, remove or rename a node**. An entry with no node is unused rather than
 * tidied away -- an agent rewriting a file makes a node vanish and come back, and a cache
 * that pruned itself on sight would forget where it was every time.
 */

import { useCallback, useEffect, useState } from "react";

import { GraphCanvas } from "./graph/GraphCanvas";
import { Chat } from "./panels/Chat";
import { Menu, type Placed } from "./panels/Menu";
import { NodePanel } from "./panels/Node";
import { Notice } from "./panels/Notice";
import { Settings } from "./panels/Settings";
import { Terminal } from "./panels/Terminal";
import { Welcome } from "./panels/Welcome";
import { Rail } from "./shell/Rail";
import { Sheet } from "./shell/Sheet";
import { TopBar } from "./shell/TopBar";
import {
  graphRead,
  layoutRead,
  layoutWrite,
  observeLast,
  observeRead,
  observeStart,
} from "./core/client";
import type { Graph, Layout, Observation } from "./core/types";

/**
 * The last project, remembered per machine.
 *
 * Browser storage rather than a file, because this is not a fact about any project -- it
 * is a fact about this person's last session, and writing it into a project would put one
 * person's habit into everybody's repository.
 */
const LAST_PROJECT = "framestack.last-project";

/** Light is the base. Dark is the exception, and it is chosen in Settings. */
const THEME = "framestack.theme";

/** The folder's own name. What the top bar calls this project, and what a person calls it. */
function nameOf(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() ?? path;
}

export default function App() {
  const [project, setProject] = useState(
    () => localStorage.getItem(LAST_PROJECT) ?? "",
  );
  const [graph, setGraph] = useState<Graph | null>(null);
  /**
   * What the last run proved, held apart from the graph.
   *
   * They answer different questions and go stale at different moments: the graph is what the
   * code says right now, and this is what a run proved at a commit. Folding one into the
   * other would make a re-parse look like a re-run, which is exactly the confusion that lets
   * a node be green because it exists.
   */
  const [observation, setObservation] = useState<Observation | null>(null);
  const [observing, setObserving] = useState(false);
  /** What the run is printing. Polled with an offset we keep, never pushed (P13). */
  const [log, setLog] = useState("");
  const [layout, setLayout] = useState<Layout>({});
  const [selected, setSelected] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    localStorage.getItem(THEME) === "dark" ? "dark" : "light",
  );
  const [settling, setSettling] = useState(false);
  /** Which rail flyout is open, or "". Nothing is docked; the canvas keeps the window. */
  const [rail, setRail] = useState("");
  /** Which face of the bottom sheet is showing, or "" for no sheet at all. */
  const [sheet, setSheet] = useState("");
  const [menu, setMenu] = useState<Placed>(null);
  /** Presses of `Agent`. A counter, because the second press of an open panel is not a close. */
  const [summon, setSummon] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME, theme);
  }, [theme]);

  const open = useCallback(async (path: string) => {
    if (!path) return;
    localStorage.setItem(LAST_PROJECT, path);
    setRefused(null);
    try {
      // Two answers to two different questions, asked side by side and never derived from
      // one another: the graph says what exists, the cache says where it was put. A layout
      // entry for a node that is gone is harmless; a node with no entry still draws.
      // Three answers to three different questions, asked side by side and never derived
      // from one another: the graph says what exists, the cache says where it was put, and
      // the observation says what a run proved. **None of these runs anything** — opening a
      // window must never execute a stranger's code.
      const [read, stored, proof] = await Promise.all([
        graphRead(path),
        layoutRead(path),
        observeLast(path),
      ]);
      setGraph(read);
      setLayout(stored.layout);
      setObservation(proof.observation);
      setObserving(proof.running);
      if (!read.ok) setRefused(read.detail);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    setGraph(null);
    setObservation(null);
    setSelected("");
    setLog("");
    void open(project);
  }, [project, open]);

  /**
   * Run the project's tests. Never automatic, and never on a re-parse.
   *
   * A window that observed on open would execute a stranger's code because they double-clicked
   * a folder, and a graph that re-ran its own tests after every edit would be a graph whose
   * colours nobody could trust to be about the commit they are looking at.
   */
  const runObserve = useCallback(async () => {
    if (!project || observing) return;
    setRefused(null);
    setLog("");
    setSheet("observe");
    try {
      const started = await observeStart(project);
      setObserving(started.running);
      if (started.observation) setObservation(started.observation);
      // A run that never started still answered: `skipped`, with the reason. That is a
      // result and it is shown as one rather than as an empty panel.
      if (!started.ok && !started.running) setRefused(started.detail);
    } catch (error) {
      setObserving(false);
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, [project, observing]);

  // Polled while it runs, with the offset the core last gave us. It stops on its own: the
  // core reports `running` false only once the verdicts are written down, so the answer that
  // ends the loop is the answer that carries the result.
  useEffect(() => {
    if (!observing || !project) return;
    let offset = 0;
    let live = true;
    const tick = async () => {
      while (live) {
        try {
          const answer = await observeRead(project, offset);
          offset = answer.offset;
          if (answer.output) setLog((held) => held + answer.output);
          if (!answer.running) {
            setObservation(answer.observation);
            setObserving(false);
            return;
          }
        } catch (error) {
          setRefused(error instanceof Error ? error.message : String(error));
          setObserving(false);
          return;
        }
        await new Promise((wake) => setTimeout(wake, 400));
      }
    };
    void tick();
    return () => {
      live = false;
    };
  }, [observing, project]);

  /**
   * Store the whole layout, as the core's contract requires: it keeps this and refuses to
   * look inside, so there is nothing on the far side that could merge two halves of it.
   *
   * A failed write is swallowed on purpose. The worst it can cost is that a card comes back
   * where it was yesterday, and interrupting somebody dragging a node to tell them about a
   * cache would be a notice out of all proportion to what it is about.
   */
  const remember = useCallback(
    (next: Layout) => {
      setLayout(next);
      void layoutWrite(project, next).catch(() => undefined);
    },
    [project],
  );

  const move = useCallback(
    (id: string, at: { x: number; y: number }, settled: boolean) => {
      const next = { ...layout, [id]: { ...layout[id], x: at.x, y: at.y } };
      // Every frame moves the card; only the end of the gesture is written down.
      if (settled) remember(next);
      else setLayout(next);
    },
    [layout, remember],
  );

  // Unfolding a system is the same kind of fact as a coordinate: something a person
  // arranged, kept beside where they put it, changing nothing about the project.
  const toggle = useCallback(
    (id: string) =>
      remember({ ...layout, [id]: { ...layout[id], expanded: !layout[id]?.expanded } }),
    [layout, remember],
  );

  // A rail entry opens the chat or the terminal; neither is a flyout, so opening one is a
  // request to the surface that owns it rather than a panel this component draws.
  useEffect(() => {
    if (rail === "chat") {
      setSummon((n) => n + 1);
      setRail("");
    } else if (rail === "terminal") {
      setSheet("terminal");
      setRail("");
    }
  }, [rail]);

  if (!project) {
    return (
      <Welcome
        onOpen={setProject}
        recent={localStorage.getItem(LAST_PROJECT)}
      />
    );
  }

  const empty = graph !== null && graph.ok && graph.nodes.length === 0;

  return (
    <div className="bp-app">
      <Rail
        open={rail}
        onOpen={setRail}
        onProject={(at) =>
          setMenu({
            x: at.x,
            y: at.y,
            items: [
              { label: nameOf(project), run: () => undefined, checked: true },
              {
                label: "Close this project",
                run: () => setProject(""),
                destructive: true,
              },
            ],
          })
        }
        onSettings={() => setSettling(true)}
      />

      <div className="bp-main">
        <TopBar
          name={nameOf(project)}
          onAgent={() => setSummon((n) => n + 1)}
          onObserve={() => void runObserve()}
          observing={observing}
          observed={observation !== null}
        />

        {/* A refusal is an answer, and an answer nobody is shown is the same as no answer. */}
        {refused ? (
          <Notice
            tone="refused"
            label="refused"
            text={refused}
            onClose={() => setRefused(null)}
          />
        ) : null}

        <div className="bp-stage">
          <GraphCanvas
            graph={graph}
            layout={layout}
            observation={observation}
            selected={selected}
            onSelect={setSelected}
            onMove={move}
            onToggle={toggle}
          />

          {/* Said as a fact about the convention rather than as a verdict on the code: an
              empty canvas over a directory full of Python has to explain that it found no
              *system*, not imply that it found nothing worth drawing. */}
          {empty ? (
            <div className="bp-empty bp-empty-full">
              No system here yet. A directory named `agent/`, `rag/`, `api/` or `worker/`
              that exports what its kind requires becomes a node; ask the chat for one.
            </div>
          ) : null}
        </div>

        {/* Summoned and dismissed. Nothing sits at the bottom of the window by default:
            the canvas gets the whole window. */}
        {sheet ? (
          <Sheet
            face={sheet}
            onFace={setSheet}
            onClose={() => setSheet("")}
            faces={[
              {
                id: "observe",
                label: observing ? "Observe (running)" : "Observe",
                // The suite's own output, unedited. A summary here would be this application
                // paraphrasing the evidence, and the verdict already is the summary.
                content: (
                  <pre className="bp-observe-log">
                    {log ||
                      (observation
                        ? `${observation.detail}\n${observation.at}${
                            observation.commit ? ` · ${observation.commit.slice(0, 7)}` : ""
                          }`
                        : "Nothing has been run here yet.")}
                  </pre>
                ),
              },
              {
                id: "terminal",
                label: "Terminal",
                content: <Terminal project={project} />,
              },
            ]}
          />
        ) : (
          /* The one thing that is always reachable without opening a panel: a shell is how
             a person gets out of a corner the buttons cannot. */
          <button className="bp-sheet-summon" onClick={() => setSheet("terminal")}>
            Terminal
          </button>
        )}
      </div>

      {/* Everything that is not the graph lives on a node. */}
      {graph && selected ? (
        <NodePanel
          project={project}
          graph={graph}
          observation={observation}
          id={selected}
          onClose={() => setSelected("")}
          onSelect={setSelected}
          // A knob was written, so the code changed. The graph is re-read — the edge set and
          // the exports could have moved — and the colours are **deliberately left alone**:
          // they are still what the last run proved, and quietly clearing them would say a
          // test failed. What they are now stale about is a commit, which the panel says.
          onEdited={() => void open(project)}
        />
      ) : null}

      {/* Folded until `Agent` is pressed: it is how a project gets its first line of code,
          and it is a button in the cluster rather than a panel nobody asked for. */}
      <Chat
        project={project}
        summon={summon}
        onTouch={() => undefined}
        onSettled={() => void open(project)}
        // Offered by the chat after a turn that wrote, and pressed by the person. The chat
        // has no way to run it itself, which is the point: colour is earned by a run
        // somebody asked for.
        onObserve={() => void runObserve()}
        handOver={null}
        onHandedOver={() => undefined}
      />

      <Menu at={menu} onClose={() => setMenu(null)} />

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
