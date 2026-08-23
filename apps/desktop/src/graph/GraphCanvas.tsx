/**
 * The graph canvas.
 *
 * Scaffold only. The single node below exists to prove React Flow mounts, pans
 * and zooms inside the Tauri window -- it is not a model of anything. Real nodes
 * arrive when the parser does (P2 in docs/roadmap.md), projected from the graph
 * IR the core returns; nothing here should grow into a second source of truth.
 */

import { useCallback } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

const initialNodes: Node[] = [
  {
    id: "scaffold",
    position: { x: 0, y: 0 },
    data: { label: "scaffold node — replaced by the parser in P2" },
    type: "default",
  },
];

const initialEdges: Edge[] = [];

export function GraphCanvas() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  // Edges are derived from data contracts in the code, never drawn by hand
  // (architecture.md §6), so connecting nodes in the canvas does nothing.
  const onConnect = useCallback((_: Connection) => undefined, []);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      fitView
      colorMode="dark"
      proOptions={{ hideAttribution: false }}
    >
      <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
      <Controls />
    </ReactFlow>
  );
}
