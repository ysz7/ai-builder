/**
 * The buttons on a node.
 *
 * **Nothing here happens by itself** (P11). Bringing services up, starting the application,
 * starting a worker, reaching a consumed MCP server -- each is a verb the core exposes
 * precisely so that looking at a graph never does it, and each one runs because a person
 * pressed it and for no other reason.
 *
 * Which buttons a node gets comes from its `kind`, which is the registry's job to define --
 * so a kind with no verbs simply has none, and no button is invented for it.
 *
 * Input is typed, never synthesized (I-5): the path a route is called with and the arguments
 * a tool is called with come from the person. Manufacturing either would manufacture the
 * evidence that came back.
 */

import { useEffect, useState } from "react";

import {
  envCall,
  envDown,
  envUp,
  mcpInspect,
  ragIndex,
  runCall,
  runStart,
  runStop,
  workStart,
  workStop,
} from "../core/client";
import { kindRegistry } from "../core/registry";
import type {
  Environment,
  GraphNode,
  InspectResult,
  NodeKindInfo,
} from "../core/types";
import { Copy } from "./Copy";
import { Notice } from "./Notice";
import { Talk } from "./Talk";

type Props = {
  project: string;
  node: GraphNode;
  /**
   * Is the process this node's kind starts alive right now?
   *
   * Asked of the core by the workspace and handed down, because it is not a fact about the
   * node: the graph is a projection of code and a pid is not in the code. What it decides
   * here is which verb the button offers — a Stop on a stopped service is a button that can
   * only fail, and two buttons that never change are two buttons nobody reads.
   */
  running: boolean;
  /**
   * What the compose file declares, for the node that carries it.
   *
   * Handed down rather than asked for here, because the workspace already asks on a clock
   * and two askers would mean two answers about the same docker. `null` until docker has
   * been asked at all.
   */
  services: Environment | null;
  onActed: () => void;
};

/** What came back, in the words the core used. Never re-worded, never turned into a verdict. */
type Said = { ok: boolean; text: string } | null;

function say(ok: boolean, text: string): Said {
  return { ok, text };
}

/**
 * The three families of process verb, keyed by what the registry calls them.
 *
 * A table and not a chain of `if`s about kind names: the registry decides which family a
 * kind is in, and this decides what that family's two buttons do. Adding a kind touches
 * neither -- which is the whole reason `starts` was put in the registry.
 */
const PROCESS_VERBS: Record<
  string,
  {
    go: string;
    halt: string;
    start: (project: string) => Promise<Said>;
    stop: (project: string) => Promise<Said>;
  }
> = {
  run: {
    go: "Run",
    halt: "Stop",
    start: async (project) => {
      const answer = await runStart(project);
      return say(
        answer.ok,
        answer.state ? `running on port ${answer.state.port}` : answer.detail,
      );
    },
    stop: async (project) => {
      const answer = await runStop(project);
      return say(answer.ok, answer.detail);
    },
  },
  work: {
    go: "Start worker",
    halt: "Stop worker",
    start: async (project) => {
      const answer = await workStart(project);
      return say(answer.ok, answer.detail);
    },
    stop: async (project) => {
      const answer = await workStop(project);
      return say(answer.ok, answer.detail);
    },
  },
  env: {
    go: "Up",
    halt: "Down",
    start: async (project) => {
      const answer = await envUp(project);
      return say(answer.ok, answer.detail || answer.services.join(", "));
    },
    stop: async (project) => {
      const answer = await envDown(project);
      return say(answer.ok, answer.detail);
    },
  },
};

/** One line of the log under the buttons: what was pressed, and what answered. */
type Line = { at: string; label: string; ok: boolean; text: string };

/**
 * How many answers are kept.
 *
 * A short log rather than one line, because these questions come in runs -- start it, call
 * it, call it again with a different path -- and the useful thing is almost always the
 * comparison with the previous answer. Long enough to hold a session's worth of pressing,
 * short enough that it never becomes a place to scroll.
 */
const KEPT = 12;

export function Actions({ project, node, running, services, onActed }: Props) {
  /**
   * What each press answered, newest last, **under the buttons**.
   *
   * It used to be one notice at the bottom of the pane, which is why pressing Call read as
   * nothing happening: the answer appeared below the fold, was replaced by the next press,
   * and went away with the re-read that followed. A log says what happened, in order, where
   * the button that did it is.
   */
  const [log, setLog] = useState<Line[]>([]);
  const [busy, setBusy] = useState("");
  const [path, setPath] = useState("/");
  const [method, setMethod] = useState("GET");
  /** Which service's row is open for a call, if any. One at a time: it is one panel. */
  const [calling, setCalling] = useState("");
  const [servicePath, setServicePath] = useState("/");
  const [offered, setOffered] = useState<InspectResult | null>(null);
  const [kind, setKind] = useState<NodeKindInfo | null>(null);

  useEffect(() => {
    let current = true;
    // A registry that cannot be read costs the extra verbs, never the panel: a node with no
    // entry simply has no way in, which is the same answer as a kind that did not opt in.
    void kindRegistry()
      .then((all) => {
        if (current) setKind(all.find((entry) => entry.name === node.kind) ?? null);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [node.kind]);

  // A different node is a different subject: the log belongs to it, not to the pane.
  useEffect(() => setLog([]), [node.id]);

  function note(label: string, answer: Said) {
    if (!answer) return;
    setLog((previous) =>
      [
        ...previous,
        {
          at: new Date().toLocaleTimeString(),
          label,
          ok: answer.ok,
          text: answer.text,
        },
      ].slice(-KEPT),
    );
  }

  async function act(label: string, run: () => Promise<Said>) {
    setBusy(label);
    try {
      note(label, await run());
      // An action that changed something changes the graph's evidence too, so the picture
      // is asked for again rather than left showing what was true before the press.
      onActed();
    } catch (error) {
      note(label, say(false, error instanceof Error ? error.message : String(error)));
    } finally {
      setBusy("");
    }
  }

  const button = (label: string, run: () => Promise<Said>, tone = "") => (
    <button
      className={`bp-btn${tone ? ` ${tone}` : ""}`}
      disabled={busy !== ""}
      onClick={() => void act(label, run)}
    >
      {busy === label ? "…" : label}
    </button>
  );

  const rows: React.ReactNode[] = [];

  /**
   * Start and stop, and **only the one that can happen next.**
   *
   * Which verb family a kind belongs to comes from the registry (`starts`), never from a
   * list of kind names here -- that list was a second opinion about the registry, and it
   * went stale the moment a kind was added to one and not the other. Whether it is up comes
   * from the core, asked on a clock.
   *
   * One button and not two: a Stop beside a stopped service is a button whose only outcome
   * is a refusal, and a pair that looks the same in both states tells a person nothing about
   * which state they are in. Green starts, red stops, and the word beside it says which.
   */
  const family = kind?.starts ?? "";
  if (family) {
    const verb = PROCESS_VERBS[family];
    if (verb) {
      rows.push(
        <div className="bp-acts" key="process">
          {running
            ? button(verb.halt, () => verb.stop(project), "bp-btn-stop")
            : button(verb.go, () => verb.start(project), "bp-btn-go")}
          <span className={`bp-acts-state${running ? " is-on" : ""}`}>
            {running ? "running" : "stopped"}
          </span>
        </div>,
      );
    }
  }


  // What the compose file declares, and how to reach it. The node used to be two buttons
  // and nothing else: the containers came up and the panel said nothing about where they
  // were, so the next question -- "how do I talk to it?" -- had to be answered somewhere
  // else entirely (Q24). Ports are docker's answer about docker's file (§5.8), never read
  // here and never guessed.
  if (node.kind === "docker.compose" && services) {
    rows.push(
      <div className="bp-services" key="services">
        {services.docker_unavailable ? (
          <div className="bp-empty">{services.docker_unavailable}</div>
        ) : null}
        {services.services.map((service) => (
          <div className="bp-service" key={service.name}>
            <div className="bp-service-head">
              {/* Two facts, two marks. A filled dot is docker saying the container is up; a
                  ring is a port that answered. A container that runs while nothing answers
                  on it is the most common state there is, and one dot could not say it. */}
              <span
                className={`bp-service-dot${service.running ? " is-up" : ""}`}
                title={service.running ? "the container is running" : "not running"}
              />
              <span className="bp-service-name">{service.name}</span>
              <span className="bp-service-ports">
                {service.ports.length > 0
                  ? service.ports.map((port) => `:${port}`).join(" ")
                  : "publishes nothing"}
              </span>
              <span
                className={`bp-service-answer${service.reachable ? " is-on" : ""}`}
              >
                {service.reachable
                  ? "answers"
                  : service.ports.length > 0
                    ? "silent"
                    : "—"}
              </span>
              {service.ports.length > 0 ? (
                <button
                  className="bp-btn bp-btn-slim"
                  onClick={() =>
                    setCalling(calling === service.name ? "" : service.name)
                  }
                >
                  {calling === service.name ? "Close" : "Call"}
                </button>
              ) : null}
            </div>

            {calling === service.name ? (
              // The path is typed, like a route's: what a container answers on is its own
              // business, and inventing one would synthesize the request as well as the
              // answer (I-5).
              <div className="bp-acts">
                <input
                  className="bp-field"
                  value={servicePath}
                  spellCheck={false}
                  onChange={(event) => setServicePath(event.target.value)}
                />
                {button(`GET ${service.name}`, async () => {
                  const answer = await envCall(
                    project,
                    service.name,
                    servicePath,
                    "GET",
                  );
                  return say(
                    answer.ok,
                    answer.status
                      ? `${answer.status} · ${answer.body}`
                      : answer.detail,
                  );
                })}
              </div>
            ) : null}
          </div>
        ))}
        {services.services.length === 0 && !services.docker_unavailable ? (
          <div className="bp-empty">this file declares no services</div>
        ) : null}
      </div>,
    );
  }

  if (node.kind === "fastapi.route") {
    rows.push(
      // The route's own path is on its decorator, which the IR does not carry -- and asking
      // the running application for it is not a question it answers. So it is typed.
      <div className="bp-acts" key="call">
        <select
          className="bp-field bp-field-slim"
          value={method}
          onChange={(e) => setMethod(e.target.value)}
        >
          {["GET", "POST", "PUT", "PATCH", "DELETE"].map((verb) => (
            <option key={verb}>{verb}</option>
          ))}
        </select>
        <input
          className="bp-field"
          value={path}
          spellCheck={false}
          onChange={(event) => setPath(event.target.value)}
        />
        {button("Call", async () => {
          const answer = await runCall(project, path, method);
          return say(
            answer.ok,
            answer.status ? `${answer.status} · ${answer.body}` : answer.detail,
          );
        })}
      </div>,
    );
  }

  if (node.kind === "mcp.server") {
    rows.push(
      <div className="bp-acts" key="mcp">
        {button("Inspect", async () => {
          const answer = await mcpInspect(project, node.id);
          setOffered(answer);
          return say(answer.ok, answer.detail || answer.status);
        })}
      </div>,
    );
  }

  if (kind?.indexes) {
    rows.push(
      // A write into somebody's store, so it is a press and never a consequence of drawing
      // the graph (P11) -- and what it says is what the store said, not what went in.
      <div className="bp-acts" key="index">
        {button("Index", async () => {
          const answer = await ragIndex(project, node.id);
          return say(
            answer.ok,
            answer.held ? `${answer.detail} · holds ${answer.held}` : answer.detail,
          );
        })}
      </div>,
    );
  }

  const talking = kind?.converses ? (
    <Talk project={project} node={node.id} onAnswered={onActed} />
  ) : null;

  if (rows.length === 0 && talking === null) return null;

  return (
    <>
      {rows.length > 0 ? <div className="bp-cap">Actions</div> : null}
      {rows}

      {/* A conversation is an action on this node, and it is drawn where its other verbs
          are -- there is nothing new on the graph, and nothing new to select (Q18). */}
      {talking}

      {offered ? (
        <div className="bp-offered">
          {/* Contents, never nodes (Q12): a remote tool has no carrier here, so it is shown
              on the server that offers it and written down nowhere. */}
          <div className="bp-cap">Offered {offered.tools.length}</div>
          {offered.tools.map((tool) => (
            <div className="bp-offer" key={tool.name}>
              <span
                className={
                  offered.allowed.includes(tool.name)
                    ? "bp-offer-on"
                    : "bp-offer-off"
                }
              >
                {tool.name}
              </span>
              <span className="bp-offer-help">{tool.description}</span>
            </div>
          ))}
          {offered.missing.length > 0 ? (
            <Notice
              tone="refused"
              text={`allowed but not offered: ${offered.missing.join(", ")}`}
            />
          ) : null}
        </div>
      ) : null}

      {/* What each press answered, where the press was. A log rather than one notice: the
          answers come in runs -- start it, call it, call it again -- and the useful thing is
          almost always the comparison with the one before. */}
      {log.length > 0 ? (
        <div className="bp-acts-log">
          <div className="bp-cap">
            Log
            <button
              className="bp-icon bp-acts-clear"
              onClick={() => setLog([])}
              title="Clear"
            >
              ✕
            </button>
          </div>
          {log.map((line, index) => (
            <div
              key={index}
              className={`bp-acts-line${line.ok ? "" : " is-refused"}`}
            >
              <span className="bp-acts-when">{line.at}</span>
              <span className="bp-acts-what">{line.label}</span>
              <span className="bp-acts-said">{line.text || "—"}</span>
              {/* Per line, because a line is what anybody wants: the docker daemon's
                  complaint goes to a search or to the agent below, and retyping it out of a
                  panel is not work a person should be doing. What is copied is what the
                  answer said -- not the time and not the button that asked. */}
              {line.text ? <Copy text={line.text} what="what this answered" /> : null}
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}
