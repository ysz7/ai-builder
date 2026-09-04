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
  ollamaModels,
  routesRead,
  settingsAbout,
  settingsRead,
  settingsWrite,
  statusRead,
} from "../core/client";
import type {
  DatabaseResult,
  McpProbe,
  Graph,
  GraphNode,
  Observation,
  RoutesResult,
  SettingField,
  SettingsAbout,
  SettingsResult,
  StatusResult,
} from "../core/types";
import { Modal } from "../shell/Modal";
import { isSystem, labelOf, tintBgOf, tintOf } from "../graph/kinds";
import { known, markOf, wordsFor } from "../graph/verdicts";
import { Deploy } from "./Deploy";
import { Docker } from "./Docker";
import { Knob } from "./Knob";
import { Ollama } from "./Ollama";
import { Service } from "./Service";
import { McpPanel } from "./McpPanel";
import { Run } from "./Run";
import { Usage } from "./Usage";
import { ChatRoute } from "./ChatRoute";

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
  onLogs,
  onTalk,
  onRepair,
  onConnected,
  onProbed,
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
  /** Show the stack's log. It lives in the bottom sheet, which the workspace owns. */
  onLogs: () => void;
  /** Open the agent's own chat. The other half of the split this panel is one side of. */
  onTalk: (id: string) => void;
  /** Ask the chat to make this node satisfy its kind, naming what it is missing. */
  onRepair: (node: GraphNode) => void;
  /** A server is authorising itself in this terminal. The workspace shows the drawer. */
  onConnected: (shell: string) => void;
  /**
   * A server answered a probe. Handed up so the card on the canvas can say the same thing.
   *
   * One probe, two places: the panel has the reason, the card has the word. Neither can say
   * something the other does not, because there is only one answer behind both.
   */
  onProbed: (probe: McpProbe) => void;
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

  /**
   * The knobs that name this dependency, gathered from the systems that declare them.
   *
   * A dependency has no `settings.py` — it is not a package, and one written for it would
   * be this application putting a file in somebody's project so a panel had something to
   * show. What it has is the fields other systems spend on it, and they are edited here
   * through the same writer, with the owning system named on the group.
   */
  const [about, setAbout] = useState<SettingsAbout | null>(null);

  /**
   * What Ollama has pulled on this machine, offered under text fields as suggestions.
   *
   * Never a catalogue and never a constraint: it is what the daemon says is here, asked
   * when a panel is open, and the field still writes whatever a person types.
   */
  const [models, setModels] = useState<string[]>([]);

  /**
   * What a connection last answered about this dependency.
   *
   * Asked here as well as on the canvas, because the panel is where the **reason** goes: a
   * red ring says something is wrong and the sentence beside it says what, which is the
   * difference between a colour a person can act on and one that is decoration.
   */
  const [status, setStatus] = useState<StatusResult | null>(null);
  const [asking, setAsking] = useState(false);

  const check = useCallback(async () => {
    setAsking(true);
    try {
      setStatus(await statusRead(project, id));
    } catch {
      // A status that could not be asked is not a status. The previous answer stays, because
      // inventing `unreachable` out of a transport failure of ours would be a wrong colour.
    } finally {
      setAsking(false);
    }
  }, [project, id]);

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
    setStatus(null);
    const node = graph.nodes.find((item) => item.id === id);
    // Only a dependency has one. Everything else in the graph is either the project's own
    // code, which has a verdict, or something declared that nothing can be asked about.
    if (node?.kind === "dependency") void check();
  }, [id, graph, check]);

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
    setAbout(null);
    const node = graph.nodes.find((item) => item.id === id);
    if (node?.kind !== "dependency") return;
    void settingsAbout(project, id)
      .then((answer) => live && setAbout(answer))
      // An extra reading, like the routes and the tables: a panel that could not have it is
      // still worth showing, and a refusal nobody asked for is worse than a missing block.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [project, id, graph]);

  // Asked for whenever the project talks to Ollama at all, because the field a person edits
  // may be on the agent's panel rather than on Ollama's. Nothing is pulled by asking: the
  // list is what the daemon already has, and a daemon that is not running answers nothing.
  useEffect(() => {
    let live = true;
    setModels([]);
    if (!graph.nodes.some((item) => item.id === "ollama")) return;
    void ollamaModels(project)
      .then((answer) => live && setModels(answer.models.map((one) => one.name)))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [project, graph]);

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

  /**
   * The same write, aimed at the system a group belongs to.
   *
   * `change` writes to the node the panel is open on, which is right for a system and wrong
   * for a dependency: there is no file behind `ollama`, and the field being edited lives in
   * `agent/settings.py`. What comes back is that system's whole settings, so the answer is
   * re-filtered rather than merged — the file is re-read either way.
   */
  const changeIn = useCallback(
    async (system: string, field: string, value: number | string | boolean) => {
      setBusy(true);
      setRefused("");
      try {
        const answer = await settingsWrite(project, system, field, value);
        if (!answer.ok) setRefused(answer.detail);
        else onEdited();
        // Ask again rather than patching what is on screen: which fields name this
        // dependency is the core's answer, and a value written here can change it.
        setAbout(await settingsAbout(project, id));
      } catch (error) {
        setRefused(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [project, id, onEdited],
  );

  /**
   * Whether this field is one to offer model names under.
   *
   * Two ways to be sure enough, and neither writes anything: the field is *called* a model,
   * or its value already **is** one of the models this machine has. A list under every text
   * field would put model names under a system prompt, which is noise pretending to be help.
   */
  const suggestFor = (field: SettingField): string[] =>
    models.length > 0 &&
    (/model/i.test(field.name) || models.includes(String(field.value ?? "")))
      ? models
      : [];

  const node = graph.nodes.find((item) => item.id === id);
  if (!node) return null;

  const proof = observation?.verdicts.find((item) => item.node === node.id);

  const children = graph.nodes.filter((item) => item.parent === node.id);
  const related = graph.edges.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );

  return (
    // The kind and the path move into the header: they are what the card on the canvas
    // already says, and two rows repeating it were the first two things in a column
    // somebody had to scroll past to reach anything they came for.
    <Modal
      title={node.name}
      badge={labelOf(node.kind)}
      subtitle={node.path}
      tint={tintOf(node.kind)}
      tintBg={tintBgOf(node.kind)}
      onClose={onClose}
    >
      <div className="bp-node-panel">

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
            the node is actually in — and beside it, the way to act on it. The button sends a
            message naming the missing export; it writes nothing, and the node turns complete
            when the code does. */}
        {node.reason ? <div className="bp-node-why">{node.reason}</div> : null}
        {node.missing.length > 0 ? (
          <button className="bp-node-open" onClick={() => onRepair(node)}>
            Ask agent to add {node.missing.join(" and ")}
          </button>
        ) : null}

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

        {/* A status, in words, with the reason under it. **Never a verdict**: a connection
            reached is not a test passed, and the two are drawn apart so a person cannot read
            one as the other. The refresh is here because the plan asks every dependency to
            carry one — polling stops when the window loses focus, and this is the way back. */}
        {status ? (
          <Row label="Status">
            <div className={`bp-status is-${asking ? "checking" : status.status}`}>
              <span className="bp-status-dot" />
              {asking ? "checking…" : status.status}
              <button
                className="bp-status-refresh nodrag"
                title="Check again"
                onClick={() => void check()}
                disabled={asking}
              >
                ↻
              </button>
            </div>
            <div className="bp-node-when">{status.detail}</div>
          </Row>
        ) : null}

        {/* Where the value behind a knob actually lives, for the keys that are not defaults
            in a file. `.env` is not drawn on the canvas — nothing imports it, so it was a
            card with no line to anything — and this is the door to it, on the node that
            reads it. Only ever `Open`: a secret is not shown, copied or carried in a
            payload, and the one place it is written is the file itself. */}
        {node.kind === "dependency" && graph.nodes.some((one) => one.id === ".env") ? (
          <Row label="Environment">
            <button className="bp-node-open" onClick={() => void editorOpen(project, ".env", 1)}>
              Open .env
            </button>
          </Row>
        ) : null}

        {/* The knobs that name this dependency, on the dependency rather than three panels
            away. **The file is still somebody's system** — there is nothing behind `ollama`
            to write to — so the group says whose `settings.py` it is and opens it. This is a
            view of the same class through the same writer, never a second place a value
            lives. */}
        {about?.groups.map((group) => (
          <Row key={group.node} label={`Settings · ${group.class_name}`}>
            {group.fields.map((one) => (
              <Knob
                key={`${group.node}.${one.name}`}
                field={one}
                busy={busy}
                suggest={suggestFor(one)}
                onChange={(value) => void changeIn(group.node, one.name, value)}
                onOpen={() => void editorOpen(project, group.path, one.line)}
              />
            ))}
            <button
              className="bp-node-open"
              onClick={() => void editorOpen(project, group.path, 1)}
            >
              Open {group.path}
            </button>
          </Row>
        ))}

        {/* The stack, on the node that is about it: what each service is, what of it the
            daemon is running, and the five fields a person changes while building. The dot
            beside a service is a container's state and is never a verdict — nothing in a
            test run proves a Postgres. */}
        {node.id === "docker" ? (
          <Docker
            project={project}
            running={deploying}
            onUp={onDeploy}
            onDown={onUndeploy}
            onLogs={onLogs}
          />
        ) : null}

        {/* `Start` and `Stop`, where a container is what provides this dependency. Drawn by
            `Service` only in that case, and silent otherwise: nobody starts Anthropic from a
            panel, and a button whose only outcome is an error is worse than no button. The
            status above is re-asked afterwards, because a container going up or down is
            exactly what makes a connection made a minute ago stale. */}
        {node.kind === "dependency" ? (
          <Service project={project} node={node.id} onChanged={() => void check()} />
        ) : null}

        {/* The one dependency with panel content of its own, and the plan says why: local
            models are the reason some people will pick this tool, and that claim is answered
            by a list a person can look at. It is not a catalogue — nothing here suggests a
            model or knows what one is for. */}
        {node.id === "ollama" ? <Ollama project={project} /> : null}

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
                  suggest={suggestFor(one)}
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

        {/* A route the project serves, and the page behind it. Not a panel this window
            draws: the chat is `api/routes/chat.py`, ordinary Python that deploys with the
            project, and `Open` sends the person's own browser to their own service. */}
        {node.kind === "chat" ? <ChatRoute project={project} node={node} /> : null}

        {/* What the last run cost. Under `Run` because that is what it is about, and drawn
            only where something was measured — a node nobody has run has no cost rather
            than a zero one. It colours nothing: money spent is not a proof of anything. */}
        {isSystem(node.kind) ? <Usage project={project} node={node.id} /> : null}

        {/* A server is somebody else's program. What the project knows about it is one entry
            in one file — shown here — and the one thing worth pressing is `Connect`, which
            runs that entry's own command where a person can watch it. Adding or changing a
            server is a code edit, which is the chat's job. */}
        {node.kind === "mcp" ? (
          <McpPanel
            project={project}
            node={node}
            onConnected={onConnected}
            onProbed={onProbed}
          />
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
    </Modal>
  );
}
