/**
 * The canvas: the core's graph, projected.
 *
 * It renders what `graph.read` returned and keeps no second opinion about any of it (I-1).
 * The one thing it owns is **where** things are drawn, and that is a cache the core stores
 * without understanding (Q13).
 *
 * Two relations, told apart by shape rather than hue (Q9):
 *
 *   - a **contract edge** is a type crossing a boundary: thin, coloured by the kind it
 *     leaves, into a round pin;
 *   - a **flow arrow** is one node having run and then another: thick, arrowed, into a
 *     triangular pin, and `observed` (a passing test went this way) is bright where
 *     `wiring` (the framework holds the edge, nothing ran) is dim.
 *
 * A graph with no run has no flow arrows at all. That emptiness is a measurement.
 */

import { useCallback, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import type { GraphRead, Layout, Placement } from "../core/types";
import { BpGroup } from "./BpGroup";
import { BpNode } from "./BpNode";
import { tintOf } from "./kinds";
import { frameBox, NODE_WIDTH, placeAll, topLevel } from "./place";

const nodeTypes = { bpNode: BpNode, bpGroup: BpGroup };

type Props = {
  graph: GraphRead;
  layout: Layout;
  litFiles: Set<string>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onMove: (positions: Record<string, Placement>) => void;
  onToggleCollapse: (id: string) => void;
};

export function Canvas({
  graph,
  layout,
  litFiles,
  selected,
  onSelect,
  onMove,
  onToggleCollapse,
}: Props) {
  const nodes = graph.graph.nodes;

  const placed = useMemo(() => placeAll(nodes, layout), [nodes, layout]);

  /** A member of a collapsed group is not drawn -- but its group still carries its mark. */
  const hidden = useMemo(() => {
    const set = new Set<string>();
    for (const group of nodes) {
      if (layout[group.id]?.collapsed) group.members.forEach((id) => set.add(id));
    }
    return set;
  }, [nodes, layout]);

  const reasonFor = useCallback(
    (id: string) => graph.observations[id]?.detail ?? graph.skipped[id] ?? "",
    [graph],
  );

  const flowNodes = useMemo<Node[]>(() => {
    const groups = new Set(topLevel(nodes).filter((n) => n.members.length > 0).map((n) => n.id));
    const result: Node[] = [];

    // Frames first, and behind: a frame is a region the nodes sit inside, not a container
    // that owns them, so it must never intercept a click meant for a node.
    for (const group of nodes) {
      if (!groups.has(group.id)) continue;
      const collapsed = layout[group.id]?.collapsed ?? false;
      // Collapsed, it keeps the corner its members occupy -- it does not move. A frame
      // that jumped somewhere else when folded would lose the place the person put it.
      const open = frameBox(group, placed);
      const box = collapsed ? { x: open.x, y: open.y, width: 260, height: 27 } : open;

      result.push({
        id: `frame:${group.id}`,
        type: "bpGroup",
        position: { x: box.x, y: box.y },
        style: { width: box.width, height: box.height },
        draggable: false,
        selectable: false,
        zIndex: 0,
        data: {
          node: group,
          verdict: (graph.verdicts[group.id] ?? "unproven") as never,
          reason: reasonFor(group.id),
          collapsed,
          memberCount: group.members.length,
          onToggle: onToggleCollapse,
        },
      });
    }

    for (const node of nodes) {
      if (hidden.has(node.id)) continue;
      if (groups.has(node.id)) continue; // drawn as its frame
      result.push({
        id: node.id,
        type: "bpNode",
        position: placed[node.id] ?? { x: 0, y: 0 },
        style: { width: NODE_WIDTH },
        selected: node.id === selected,
        zIndex: 1,
        data: {
          node,
          verdict: (graph.verdicts[node.id] ?? "unproven") as never,
          reason: reasonFor(node.id),
          lit: litFiles.has(node.location.file),
        },
      });
    }
    return result;
  }, [nodes, placed, layout, hidden, graph, selected, litFiles, reasonFor, onToggleCollapse]);

  const flowEdges = useMemo<Edge[]>(() => {
    const drawn = (id: string) => !hidden.has(id) && Boolean(placed[id]);
    const kindOf = new Map(nodes.map((n) => [n.id, n.kind]));
    const edges: Edge[] = [];

    for (const edge of graph.graph.edges) {
      if (!drawn(edge.source) || !drawn(edge.target)) continue;
      edges.push({
        id: `contract:${edge.source}->${edge.target}`,
        source: edge.source,
        target: edge.target,
        sourceHandle: "data-out",
        targetHandle: "data-in",
        type: "default",
        label: edge.contract,
        className: "bp-edge-contract",
        style: { stroke: tintOf(kindOf.get(edge.source) ?? ""), strokeWidth: 1.4 },
      });
    }

    for (const arrow of graph.flow) {
      if (!drawn(arrow.source) || !drawn(arrow.target)) continue;
      const observed = arrow.origin === "observed";
      edges.push({
        id: `flow:${arrow.source}->${arrow.target}`,
        source: arrow.source,
        target: arrow.target,
        sourceHandle: "exec-out",
        targetHandle: "exec-in",
        type: "smoothstep",
        className: `bp-edge-flow${observed ? " is-observed" : " is-wiring"}`,
        style: {
          stroke: observed ? "var(--exec)" : "var(--exec-dim)",
          strokeWidth: 2.6,
        },
        markerEnd: { type: "arrowclosed", color: observed ? "var(--exec)" : "var(--exec-dim)" } as never,
      });
    }
    return edges;
  }, [graph, hidden, placed, nodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Only positions are kept, and only when a drag has finished. Writing on every frame
      // would put a file write behind the mouse; writing anything else would make this a
      // second store of state.
      const moved: Record<string, Placement> = {};
      for (const change of changes) {
        if (change.type !== "position" || change.dragging || !change.position) continue;
        if (change.id.startsWith("frame:")) continue;
        moved[change.id] = { ...layout[change.id], ...change.position };
      }
      if (Object.keys(moved).length > 0) onMove(moved);
    },
    [layout, onMove],
  );

  return (
    <div className="bp-canvas">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.25}
        maxZoom={1.6}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="var(--grid-coarse)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
