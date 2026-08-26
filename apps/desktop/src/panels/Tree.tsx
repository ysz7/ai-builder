/**
 * What the project holds, by group. Unreal's "My Blueprint" panel.
 *
 * A tree of what the graph returned and nothing more: the same nodes, the same verdicts,
 * read from the same payload the canvas draws. Two views of one answer, never two answers.
 */

import type { GraphRead } from "../core/types";
import { topLevel } from "../graph/place";
import { verdictOf } from "../graph/kinds";

type Props = {
  graph: GraphRead;
  selected: string | null;
  onSelect: (id: string) => void;
};

export function Tree({ graph, selected, onSelect }: Props) {
  const nodes = graph.graph.nodes;
  const byId = new Map(nodes.map((node) => [node.id, node]));

  return (
    <div className="bp-tree">
      {topLevel(nodes).map((group) => (
        <div key={group.id} className="bp-tree-group">
          <button className="bp-tree-head" onClick={() => onSelect(group.id)}>
            <span
              className={`bp-dot is-${verdictOf(graph.verdicts, group.id)}`}
            />
            {group.title ?? group.id}
            <span className="bp-tree-kind">{group.kind}</span>
          </button>
          {group.members.map((id) => {
            const member = byId.get(id);
            if (!member) return null;
            return (
              <button
                key={id}
                className={`bp-tree-item${id === selected ? " is-on" : ""}`}
                onClick={() => onSelect(id)}
              >
                <span
                  className={`bp-dot is-${verdictOf(graph.verdicts, id)}`}
                />
                {member.title ?? member.id}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
