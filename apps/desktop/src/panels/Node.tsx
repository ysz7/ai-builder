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

import { editorOpen, settingsRead, settingsWrite } from "../core/client";
import type {
  Graph,
  GraphNode,
  Observation,
  SettingsResult,
} from "../core/types";
import { Flyout } from "../shell/Flyout";
import { labelOf } from "../graph/kinds";
import { known, markOf, wordsFor } from "../graph/verdicts";
import { Deploy } from "./Deploy";
import { Knob } from "./Knob";
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

  useEffect(() => {
    let live = true;
    setSettings(null);
    setRefused("");
    void settingsRead(project, id)
      .then((answer) => live && setSettings(answer))
      .catch((error: unknown) =>
        live && setRefused(error instanceof Error ? error.message : String(error)),
      );
    return () => {
      live = false;
    };
  }, [project, id]);

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

        {/* A file node promises nothing, so it is asked for nothing. The absence is the
            same one that keeps it uncoloured: there is no contract here to satisfy. */}
        {node.kind === "file" ? null : (
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

        {/* The knobs, and only where the convention puts them: one `BaseSettings` subclass
            in the system's own `settings.py`. A system with none shows none and says so —
            nothing here creates the file, because a `settings.py` written because a panel was
            opened would be the toolchain deciding a system has knobs. */}
        {settings && node.kind !== "file" ? (
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

        {/* One node, one export, no traversal. The graph is a projection and this is the
            proof of it: there is nothing here that could mean "and then the next node". */}
        {node.kind === "file" ? null : <Run project={project} node={node} />}

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
