/**
 * The canvas the graph is drawn on.
 *
 * Everything here is derived from one core answer. This component keeps **no graph state of
 * its own** and never will — a second copy would be a second opinion, and the code is the
 * only source of truth. What it owns is where things are drawn, which is the one fact about
 * a canvas that is genuinely the person's rather than the project's.
 *
 * Three refusals are written into it, and they are the line between this and a
 * flow-document builder:
 *
 *   - **There is no connect gesture.** `nodesConnectable` is off and there is no
 *     `onConnect`, not by omission: an edge exists because an import exists, so dragging
 *     from one node to another has nothing to write. Connecting two systems is a code edit.
 *   - **Position carries no meaning.** Moving a node writes a coordinate to
 *     `.framestack/layout.json` and changes nothing else. Delete that file and the graph is
 *     identical; only the arrangement is lost.
 *   - **Nothing here runs.** There is no run-the-graph button and no traversal of the
 *     canvas. Execution order lives in Python.
 *
 * One consequence of keeping no state: the node array is **re-derived on every render**,
 * including every frame of a drag, because a position is a prop here. React Flow keeps a
 * node's measured size only while the object it was handed stays reference-identical, so a
 * re-derived array arrives with that measurement gone and the drag maths has nothing to work
 * with. The fix is to stop making it measure: `cardWidth` and `cardHeight` are already the
 * sizes `place.ts` lays the graph out with and the sizes the DOM is given, so they are
 * declared on the node rather than rediscovered from the rendered element. What React Flow
 * was measuring was our own arithmetic coming back around.
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

import type { Graph, Layout, Observation } from "../core/types";
import { FileCard } from "./FileCard";
import { Frame } from "./Frame";
import { SystemCard } from "./SystemCard";
import {
  cardHeight,
  cardWidth,
  foldEdges,
  frameBox,
  isExpanded,
  placeAll,
  visible,
} from "./place";

const NODE_TYPES = { system: SystemCard, file: FileCard, frame: Frame };

/**
 * How big a node is, said three times because React Flow reads it in three places.
 *
 * `style` is what the browser draws, `width`/`height` are what layout and `fitView` use, and
 * `measured` is what dragging reads. The last one is normally filled in by React Flow from
 * the rendered element — but only for as long as the node object it was handed keeps its
 * identity, and this canvas derives a fresh one on every frame of a gesture. Declaring it
 * is not a workaround for that: these numbers are where the size comes from in the first
 * place, and measuring the DOM only asks the browser to hand our own arithmetic back.
 */
function sized(width: number, height: number) {
  return { width, height, measured: { width, height }, style: { width, height } };
}

export function GraphCanvas({
  graph,
  layout,
  observation,
  selected,
  onSelect,
  onMove,
  onToggle,
  onTalk,
}: {
  graph: Graph | null;
  layout: Layout;
  /**
   * The last run, or null where there has never been one.
   *
   * Held apart from the graph rather than folded into it, because they answer different
   * questions and go stale at different moments: the graph is what the code says right now,
   * and this is what a run proved at a commit. A node with no entry here has no verdict —
   * never a default one.
   */
  observation: Observation | null;
  selected: string;
  onSelect: (id: string) => void;
  /**
   * One node put somewhere. `settled` is the end of the gesture.
   *
   * Every frame of the drag is reported, because positions are a prop and a canvas that
   * only heard about the last one would leave the card under the cursor instead of moving
   * it. Only the settled one is worth writing down: a hundred versions of one gesture
   * through the wire is a hundred writes of a fact that was true for 16ms.
   */
  onMove: (id: string, at: { x: number; y: number }, settled: boolean) => void;
  onToggle: (id: string) => void;
  /** Open an agent's own chat. Passed through to the card; the canvas has no opinion on it. */
  onTalk: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    if (!graph || !graph.ok) return { nodes: [] as Node[], edges: [] as Edge[] };

    const found = new Map(
      (observation?.verdicts ?? []).map((verdict) => [verdict.node, verdict]),
    );
    const shown = visible(graph, layout);
    const placed = placeAll(graph, layout);
    const drawn = foldEdges(graph, shown);

    // A pin is drawn only where an edge lands on it. Four pins on every card would be a
    // picture of what *could* be connected, and nothing here can be connected.
    const pinned = {
      in: new Set(drawn.filter((e) => e.kind === "import").map((e) => e.target)),
      out: new Set(drawn.filter((e) => e.kind === "import").map((e) => e.source)),
      up: new Set(drawn.filter((e) => e.kind === "mcp").map((e) => e.target)),
      down: new Set(drawn.filter((e) => e.kind === "mcp").map((e) => e.source)),
    };

    const flow: Node[] = [];

    // The frames first, so they sit behind the cards they wrap. React Flow paints in array
    // order and a region drawn over its own members would swallow every click on them.
    for (const system of shown) {
      if (system.parent !== "" || !isExpanded(layout, system.id)) continue;
      const box = frameBox(system, shown, placed);
      if (!box) continue;
      flow.push({
        id: `frame:${system.id}`,
        type: "frame",
        position: { x: box.x, y: box.y },
        ...sized(box.width, box.height),
        draggable: false,
        selectable: false,
        data: {
          system: system.id,
          name: system.name,
          kind: system.kind,
          count: system.children.length,
          verdict: found.get(system.id)?.verdict ?? "",
          onToggle,
        },
      });
    }

    for (const node of shown) {
      flow.push({
        id: node.id,
        type: node.kind === "file" ? "file" : "system",
        position: placed[node.id] ?? { x: 0, y: 0 },
        ...sized(cardWidth(node), cardHeight(node)),
        selected: node.id === selected,
        data:
          node.kind === "file"
            ? { node, pinned: pinned.up.has(node.id), onOpen: onSelect }
            : {
                node,
                // File nodes are never coloured, and they never reach here: nothing runs
                // them, so nothing can prove them.
                verdict: found.get(node.id)?.verdict ?? "",
                reason: found.get(node.id)?.reason ?? "",
                pins: {
                  in: pinned.in.has(node.id),
                  out: pinned.out.has(node.id),
                  up: pinned.up.has(node.id),
                  down: pinned.down.has(node.id),
                },
                expanded: isExpanded(layout, node.id),
                onOpen: onSelect,
                onToggle,
                onTalk,
              },
      });
    }

    const wires: Edge[] = drawn.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.kind === "mcp" ? "down" : "out",
      targetHandle: edge.kind === "mcp" ? "up" : "in",
      type: "smoothstep",
      // An MCP server is somebody else's process, reached over a protocol rather than
      // imported, so its line is dashed: the same relation drawn in the same weight would
      // claim the project contains it.
      animated: false,
      label: edge.label || undefined,
      className: edge.kind === "mcp" ? "bp-edge-contract" : undefined,
      style: {
        stroke: edge.kind === "mcp" ? "var(--k-mcp)" : "var(--line-strong)",
        strokeWidth: 1.5,
        strokeDasharray: edge.kind === "mcp" ? "4 4" : undefined,
      },
    }));

    return { nodes: flow, edges: wires };
  }, [graph, layout, observation, selected, onSelect, onToggle, onTalk]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      for (const change of changes) {
        if (change.type === "position" && change.position) {
          onMove(change.id, change.position, change.dragging === false);
        }
      }
    },
    [onMove],
  );

  return (
    <div className="bp-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onPaneClick={() => onSelect("")}
        /* No connect handler, and not by omission: an edge exists because an import exists,
           so dragging from one node to another has nothing to write. Connecting two systems
           is a code edit, made through the chat. */
        nodesConnectable={false}
        edgesFocusable={false}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
