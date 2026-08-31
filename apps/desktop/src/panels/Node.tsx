/**
 * What a node is, in full.
 *
 * Everything that is not the graph itself lives on a node: click it and this opens. In
 * Phase 1 that is the reading — its name, where it is, what its kind requires and whether
 * it has it, what it contains and what it is made of. Its settings arrive in Phase 3, its
 * verdict in Phase 2 and its Run controls in Phase 5, each **beside the capability that can
 * answer for it**: a button whose only possible outcome is an error is worse than no button.
 *
 * It reads the graph it was handed and holds nothing. A panel with its own copy of a node
 * would be a second source of truth the moment the agent edited a file.
 */

import type { Graph, GraphNode } from "../core/types";
import { Flyout } from "../shell/Flyout";
import { labelOf } from "../graph/kinds";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bp-node-row">
      <span className="bp-node-label">{label}</span>
      <div className="bp-node-value">{children}</div>
    </div>
  );
}

export function NodePanel({
  graph,
  id,
  onClose,
  onSelect,
}: {
  graph: Graph;
  id: string;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const node = graph.nodes.find((item) => item.id === id);
  if (!node) return null;

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
