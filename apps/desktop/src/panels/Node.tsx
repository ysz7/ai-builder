/**
 * What a node is, in full.
 *
 * Everything that is not the graph itself lives on a node: click it and this opens. Today
 * that is the reading — its name, where it is, what its kind requires and whether it has it,
 * what it contains, **which tests reached it**, **its knobs**, and — since Phase 5 — the one
 * thing it can be asked to do: call its own export, or, on `compose.yaml`, bring the stack
 * up. Each of those arrived beside the capability that can answer for it, because a button
 * whose only possible outcome is an error is worse than no button.
 *
 * **Running a node colours nothing.** The verdict on this panel is the last run of the
 * project's tests; the result of pressing `Run` sits below it in its own block and never
 * touches the card. They are two different claims and they are kept two.
 *
 * The tests are listed rather than counted, and that is the point of the panel. A colour on
 * a canvas is what every flow builder already draws; a colour with the name of the test that
 * earned it, which a person can paste into their own terminal, is the thing that cannot be
 * faked by a document.
 *
 * It reads the graph it was handed and holds nothing. A panel with its own copy of a node
 * would be a second source of truth the moment the agent edited a file.
 */

import { useCallback, useEffect, useState } from "react";

import {
  databaseRead,
  editorOpen,
  routesRead,
  settingsRead,
  settingsWrite,
} from "../core/client";
import type {
  DatabaseResult,
  Graph,
  GraphNode,
  Observation,
  RoutesResult,
  SettingsResult,
} from "../core/types";
import { Flyout } from "../shell/Flyout";
import { isSystem, labelOf } from "../graph/kinds";
import { known, markOf, wordsFor } from "../graph/verdicts";
import { Deploy } from "./Deploy";
import { Knob } from "./Knob";
import { McpPanel } from "./McpPanel";
import { Run } from "./Run";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bp-node-row">
      <span className="bp-node-label">{label}</span>
      <div className="bp-node-value">{children}</div>
    </div>
  );
}

export function NodePanel({
  project,
  graph,
  observation,
  id,
  onClose,
  onSelect,
  onEdited,
  deploying,
  onDeploy,
  onUndeploy,
  onTalk,
  onConnected,
}: {
  project: string;
  graph: Graph;
  observation: Observation | null;
  id: string;
  onClose: () => void;
  onSelect: (id: string) => void;
  /** A field was written. The colours on the canvas are now about a file that changed. */
  onEdited: () => void;
  /** Whether the stack this window brought up is still up. The workspace owns it and polls. */
  deploying: boolean;
  onDeploy: () => void;
  onUndeploy: () => void;
  /** Open the agent's own chat. The other half of the split this panel is one side of. */
  onTalk: (id: string) => void;
  /** A server is authorising itself in this terminal. The workspace shows the drawer. */
  onConnected: (shell: string) => void;
}) {
  /**
   * The knobs, asked for when the panel opens on a node and never before.
   *
   * Held here rather than beside the graph because they answer a different question and are
   * read from a different file: the graph says what systems exist, and this says what one of
   * them lets a person tune. Asking for every system's settings on every parse would read
   * four files nobody had opened a panel for.
   */
  const [settings, setSettings] = useState<SettingsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState("");

  /**
   * What this service serves, asked only of a service and only when its panel is open.
   *
   * Held here for the reason the knobs are: it answers a different question than the graph
   * and goes stale at a different moment. **Routes are not nodes** — forty of them would be
   * forty boxes on a canvas — so this is the only place they exist in the interface.
   */
  const [routes, setRoutes] = useState<RoutesResult | null>(null);

  /**
   * What the storage holds, asked only of the database node and only when it is open.
   *
   * **Twelve tables are twelve rows here and never twelve boxes out there.** Table-level
   * edges produce a hairball whose every line has to choose a table to land on; the mapping
   * belongs where it can be read on demand.
   */
  const [database, setDatabase] = useState<DatabaseResult | null>(null);

  useEffect(() => {
    let live = true;
    setSettings(null);
    setRefused("");
    // Only a package can have a `settings.py`. Asking about a file or a server would be
    // asking the core a question with no sensible answer, and it would say so — which would
    // put a refusal in front of a person who asked for nothing.
    const node = graph.nodes.find((item) => item.id === id);
    if (!node || !isSystem(node.kind)) return;
    void settingsRead(project, id)
      .then((answer) => live && setSettings(answer))
      .catch((error: unknown) =>
        live && setRefused(error instanceof Error ? error.message : String(error)),
      );
    return () => {
      live = false;
    };
  }, [project, id, graph]);

  useEffect(() => {
    let live = true;
    setDatabase(null);
    const node = graph.nodes.find((item) => item.id === id);
    if (!node || node.kind !== "dependency") return;
    void databaseRead(project)
      .then((answer) => live && setDatabase(answer))
      // A reading, not the panel. If it cannot be had, the node is still worth showing.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [project, id, graph]);

  useEffect(() => {
    let live = true;
    setRoutes(null);
    // Only an `api/` package declares routes, and the core refuses every other node rather
    // than answering with an empty list. Asking anyway would put that refusal in front of
    // somebody who opened a rag.
    const node = graph.nodes.find((item) => item.id === id);
    if (!node || node.kind !== "api") return;
    void routesRead(project, id)
      .then((answer) => live && setRoutes(answer))
      // A route list is an extra reading, not the panel. If it cannot be had, the rest of
      // the node is still worth showing — so this failure is quiet rather than fatal.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [project, id, graph]);

  const change = useCallback(
    async (field: string, value: number | string | boolean) => {
      setBusy(true);
      setRefused("");
      try {
        const answer = await settingsWrite(project, id, field, value);
        // What is drawn next is the file re-read, including when the write was refused: a
        // panel that kept showing a value the file does not hold would be lying about it.
        setSettings(answer);
        if (!answer.ok) setRefused(answer.detail);
        else onEdited();
      } catch (error) {
        setRefused(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [project, id, onEdited],
  );

  const node = graph.nodes.find((item) => item.id === id);
  if (!node) return null;

  const proof = observation?.verdicts.find((item) => item.node === node.id);

  const children = graph.nodes.filter((item) => item.parent === node.id);
  const related = graph.edges.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );

  return (
    <Flyout title={node.name} onClose={onClose}>
      <div className="bp-node-panel">
        <Row label="Kind">{labelOf(node.kind)}</Row>
        <Row label="Path">
          <code>{node.path}</code>
        </Row>

        {/* A file node and an MCP server promise nothing, so they are asked for nothing. The
            absence is the same one that keeps them uncoloured: no contract to satisfy. */}
        {!isSystem(node.kind) ? null : (
          <Row label="Required export">
            <div className="bp-node-exports">
              {node.exports.map((name) => (
                <code
                  key={name}
                  className={node.missing.includes(name) ? "is-missing" : undefined}
                >
                  {name}
                </code>
              ))}
            </div>
          </Row>
        )}

        {/* Where an edge may land, and for a tool the whole of what it is: its public
            functions. Listed here as well as on the card, because the card draws rows only
            where there is more than one — a single port is the node, and a row restating
            the title is a second name for one thing. */}
        {node.ports.length > 0 ? (
          <Row label={node.kind === "tool" ? `Functions (${node.ports.length})` : "Ports"}>
            <div className="bp-node-exports">
              {node.ports.map((port) => (
                <code key={port}>{port}</code>
              ))}
            </div>
          </Row>
        ) : null}

        {/* Said plainly, and never repaired into something plausible. This sentence is the
            most useful thing the parser can produce, because it is the way out of the state
            the node is actually in. */}
        {node.reason ? <div className="bp-node-why">{node.reason}</div> : null}

        {/* What a run proved, with the run's own words for it and the tests behind it.
            Absent where nothing has been observed: an unobserved node says nothing here
            rather than saying "unknown", because a row that always exists invites a default
            to be put in it. */}
        {proof && known(proof.verdict) ? (
          <Row label="Verdict">
            <div className="bp-node-verdict">
              <span className={`bp-mark is-${proof.verdict}`}>{markOf(proof.verdict)}</span>
              <span>{proof.reason || wordsFor(proof.verdict)}</span>
            </div>
            {observation ? (
              <div className="bp-node-when">
                {observation.at}
                {observation.commit ? ` · ${observation.commit.slice(0, 7)}` : ""}
              </div>
            ) : null}
          </Row>
        ) : null}

        {proof && proof.tests.length > 0 ? (
          <Row label={`Tests that reached it (${proof.tests.length})`}>
            <div className="bp-node-files">
              {proof.tests.map((test) => (
                <code key={test}>{test}</code>
              ))}
            </div>
          </Row>
        ) : null}

        {children.length > 0 ? (
          <Row label={`Children (${children.length})`}>
            <div className="bp-node-list">
              {children.map((child: GraphNode) => (
                <button key={child.id} onClick={() => onSelect(child.id)}>
                  {child.name}
                </button>
              ))}
            </div>
          </Row>
        ) : null}

        {related.length > 0 ? (
          <Row label="Edges">
            <div className="bp-node-list">
              {related.map((edge) => (
                <span key={edge.id}>
                  {edge.source === node.id ? "→ " : "← "}
                  {edge.source === node.id ? edge.target : edge.source}
                  {edge.label ? ` (${edge.label})` : ""}
                </span>
              ))}
            </div>
          </Row>
        ) : null}

        {/* What the storage holds, and who touches each of it. The file is where the table
            is declared, which is a fact rather than an inference — and `[vector]` is what
            makes the node itself read `postgres + pgvector`. */}
        {database && database.present ? (
          <>
            {database.target ? (
              <Row label="Connection">
                <code>{database.target}</code>
              </Row>
            ) : null}
            {database.tables.length > 0 ? (
              <Row label={`Tables (${database.tables.length})`}>
                <div className="bp-routes">
                  {database.tables.map((table) => (
                    <button
                      key={`${table.file} ${table.name}`}
                      className="bp-route"
                      title={`declared in ${table.file}`}
                      onClick={() => void editorOpen(project, table.file, 1)}
                    >
                      <span className="bp-route-path">{table.name}</span>
                      <span className="bp-route-to">
                        {table.vector ? "[vector] " : ""}← {table.file}
                      </span>
                    </button>
                  ))}
                </div>
              </Row>
            ) : (
              <Row label="Tables">
                <span className="bp-node-quiet">
                  no models declared, so there is nothing to list
                </span>
              </Row>
            )}
          </>
        ) : null}

        {/* Where each request goes next, and never a node for any of it. The arrow is read
            from the handler's own calls; `?` is a real answer and is never guessed away,
            because a person can read the handler but cannot un-read a target this asserted.
            A handler that calls nothing shows no arrow at all — that is no downstream rather
            than an unknown one, and the two are different claims. */}
        {routes && routes.ok && routes.routes.length > 0 ? (
          <Row label={`Routes (${routes.routes.length})`}>
            <div className="bp-routes">
              {routes.routes.map((route) => (
                <button
                  key={`${route.method} ${route.path} ${route.handler}`}
                  className="bp-route"
                  title={`${route.handler} in ${route.file}`}
                  onClick={() => void editorOpen(project, route.file, 1)}
                >
                  <span className="bp-route-verb">{route.method}</span>
                  <span className="bp-route-path">{route.path}</span>
                  <span className="bp-route-to">
                    {route.unsure
                      ? "→ ?"
                      : route.targets.length > 0
                      ? `→ ${route.targets.join(", ")}`
                      : ""}
                  </span>
                </button>
              ))}
            </div>
          </Row>
        ) : null}

        {/* The knobs, and only where the convention puts them: one `BaseSettings` subclass
            in the system's own `settings.py`. A system with none shows none and says so —
            nothing here creates the file, because a `settings.py` written because a panel was
            opened would be the toolchain deciding a system has knobs. */}
        {settings && isSystem(node.kind) ? (
          settings.path ? (
            <Row label={`Settings · ${settings.class_name}`}>
              {settings.fields.map((one) => (
                <Knob
                  key={one.name}
                  field={one}
                  busy={busy}
                  onChange={(value) => void change(one.name, value)}
                  onOpen={() => void editorOpen(project, settings.path, one.line)}
                />
              ))}
              <button
                className="bp-node-open"
                onClick={() => void editorOpen(project, settings.path, 1)}
              >
                Open {settings.path}
              </button>
            </Row>
          ) : (
            <Row label="Settings">
              <span className="bp-node-quiet">{settings.detail}</span>
            </Row>
          )
        ) : null}

        {refused ? <div className="bp-node-why">{refused}</div> : null}

        {/* An agent is talked to rather than filled in, so it gets a door to its own panel
            instead of a form here. Settings on this side, conversation on that one. */}
        {node.kind === "agent" ? (
          <div className="bp-run">
            <span className="bp-node-label">Run</span>
            <button className="bp-run-go bp-run-wide" onClick={() => onTalk(node.id)}>
              Chat with it
            </button>
            <div className="bp-run-note">
              Calls <code>run(message)</code>. Each turn is a separate process.
            </div>
          </div>
        ) : !isSystem(node.kind) ? null : (
          /* One node, one export, no traversal. The graph is a projection and this is the
             proof of it: there is nothing here that could mean "and then the next node". */
          <Run project={project} node={node} />
        )}

        {/* A server is somebody else's program. What the project knows about it is one entry
            in one file — shown here — and the one thing worth pressing is `Connect`, which
            runs that entry's own command where a person can watch it. Adding or changing a
            server is a code edit, which is the chat's job. */}
        {node.kind === "mcp" ? (
          <McpPanel project={project} node={node} onConnected={onConnected} />
        ) : null}

        {/* The one file node that can be asked to do something, and the only deployment
            target there is. `.env`, the Dockerfile and `mcp.json` are opened and edited. */}
        {node.id === "compose.yaml" ? (
          <Deploy
            project={project}
            running={deploying}
            onUp={onDeploy}
            onDown={onUndeploy}
          />
        ) : null}

        {node.files.length > 0 ? (
          <Row label={`Files (${node.files.length})`}>
            <div className="bp-node-files">
              {node.files.map((file) => (
                <code key={file}>{file}</code>
              ))}
            </div>
          </Row>
        ) : null}
      </div>
    </Flyout>
  );
}
