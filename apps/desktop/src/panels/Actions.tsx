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
  envDown,
  envUp,
  graphKinds,
  mcpInspect,
  ragIndex,
  runCall,
  runStart,
  runStop,
  workStart,
  workStop,
} from "../core/client";
import type { GraphNode, InspectResult, NodeKindInfo } from "../core/types";
import { Notice } from "./Notice";
import { Talk } from "./Talk";

/**
 * The registry, asked once and kept for the window's lifetime.
 *
 * Which verbs a node has is the **registry's** answer (§5.6): a kind opts in by naming a way
 * in, and a kind that has not opted in shows no button at all rather than one that does
 * nothing. Keeping a list of kind names here instead would be a second opinion about the
 * registry, and it would go stale the first time somebody added a kind to it.
 */
let registry: Promise<NodeKindInfo[]> | null = null;

function kinds(): Promise<NodeKindInfo[]> {
  registry ??= graphKinds().then((answer) => answer.kinds);
  return registry;
}

type Props = { project: string; node: GraphNode; onActed: () => void };

/** What came back, in the words the core used. Never re-worded, never turned into a verdict. */
type Said = { ok: boolean; text: string } | null;

function say(ok: boolean, text: string): Said {
  return { ok, text };
}

export function Actions({ project, node, onActed }: Props) {
  const [said, setSaid] = useState<Said>(null);
  const [busy, setBusy] = useState("");
  const [path, setPath] = useState("/");
  const [method, setMethod] = useState("GET");
  const [offered, setOffered] = useState<InspectResult | null>(null);
  const [kind, setKind] = useState<NodeKindInfo | null>(null);

  useEffect(() => {
    let current = true;
    // A registry that cannot be read costs the extra verbs, never the panel: a node with no
    // entry simply has no way in, which is the same answer as a kind that did not opt in.
    void kinds()
      .then((all) => {
        if (current) setKind(all.find((entry) => entry.name === node.kind) ?? null);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [node.kind]);

  async function act(label: string, run: () => Promise<Said>) {
    setBusy(label);
    setSaid(null);
    try {
      setSaid(await run());
      // An action that changed something changes the graph's evidence too, so the picture
      // is asked for again rather than left showing what was true before the press.
      onActed();
    } catch (error) {
      setSaid(
        say(false, error instanceof Error ? error.message : String(error)),
      );
    } finally {
      setBusy("");
    }
  }

  const button = (label: string, run: () => Promise<Said>) => (
    <button
      className="bp-btn"
      disabled={busy !== ""}
      onClick={() => void act(label, run)}
    >
      {busy === label ? "…" : label}
    </button>
  );

  const rows: React.ReactNode[] = [];

  if (node.kind === "docker.compose") {
    rows.push(
      <div className="bp-acts" key="compose">
        {button("Up", async () => {
          const answer = await envUp(project);
          return say(answer.ok, answer.detail || answer.services.join(", "));
        })}
        {button("Down", async () => {
          const answer = await envDown(project);
          return say(answer.ok, answer.detail);
        })}
      </div>,
    );
  }

  if (node.kind === "fastapi.service" || node.kind === "mcp.service") {
    rows.push(
      <div className="bp-acts" key="run">
        {button("Run", async () => {
          const answer = await runStart(project);
          return say(
            answer.ok,
            answer.state ? `port ${answer.state.port}` : answer.detail,
          );
        })}
        {button("Stop", async () => {
          const answer = await runStop(project);
          return say(answer.ok, answer.detail);
        })}
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

  if (node.kind === "queue.workers" || node.kind === "queue.app") {
    rows.push(
      <div className="bp-acts" key="work">
        {button("Start worker", async () => {
          const answer = await workStart(project);
          return say(answer.ok, answer.detail);
        })}
        {button("Stop worker", async () => {
          const answer = await workStop(project);
          return say(answer.ok, answer.detail);
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

      {said ? (
        <Notice
          tone={said.ok ? "said" : "refused"}
          text={said.text}
          onClose={() => setSaid(null)}
        />
      ) : null}
    </>
  );
}
