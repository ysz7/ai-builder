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

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  applyNodeChanges,
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
  /**
   * The kinds whose process is alive right now.
   *
   * Passed in rather than read here, and it is **not part of the graph**: the graph is a
   * projection of code (I-1) and whether a pid is alive is not in the code. A node wears it
   * as a live dot beside its verdict, never instead of one — a service can be up and still
   * have nothing proven about it.
   */
  runningKinds: Set<string>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onMove: (positions: Record<string, Placement>) => void;
  onToggleCollapse: (id: string) => void;
  /** Show every knob on this card, or the first few. Layout state, never graph state. */
  onToggleExpand: (id: string) => void;
  /** The one write verb a card has, and it is the inspector's (P18.3). */
  onKnob: (node: string, knob: string, value: unknown) => void;
  /** The `⋮`. The caller decides what it offers, from the registry. */
  onMenu: (id: string, at: { x: number; y: number }) => void;
  /**
   * A drag from one node to another (P21).
   *
   * **This does not draw an edge.** It asks the core to write the call into the generated
   * zone; an arrow appears in the next read, or in the next run, or not at all -- and the
   * last of those is information rather than a bug (Q9). Nothing here adds a wire to what
   * is drawn, because a wire drawn by a gesture would be the second source of truth I-1
   * forbids, and it is the whole difference between this and a flow-document builder.
   */
  onConnect: (source: string, target: string) => void;
  /**
   * Which kinds may be connected to which, from the core's own table.
   *
   * Held so a drag that could only ever be refused can be declined at the pin. It is the
   * same table the writer uses -- there is no second list here.
   */
  compositions: { source: string; target: string }[];
};

export function Canvas({
  graph,
  layout,
  litFiles,
  runningKinds,
  selected,
  onSelect,
  onMove,
  onToggleCollapse,
  onToggleExpand,
  onKnob,
  onMenu,
  onConnect,
  compositions,
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

  /**
   * Which pins each node actually needs, from the edges that will be drawn.
   *
   * Computed here because this is where both relations are known, and computed **before**
   * the nodes rather than inside them: a pin that exists because an edge lands on it has to
   * be decided by the edge. A node nothing connects to gets none, which is the whole point.
   */
  const pinsOf = useCallback(
    (id: string) => {
      const drawn = (other: string) => !hidden.has(other) && Boolean(placed[other]);
      const contract = graph.graph.edges.filter(
        (edge) => drawn(edge.source) && drawn(edge.target),
      );
      const flow = graph.flow.filter(
        (arrow) => drawn(arrow.source) && drawn(arrow.target),
      );
      const kind = nodes.find((node) => node.id === id)?.kind ?? "";
      // A pin is a socket something is plugged into (§18.6), and P21 adds a second reason
      // for one to exist: a node a connection could be *made* from or to needs somewhere to
      // start and land the drag. Still not unconditional -- a kind the table says nothing
      // about wears no pin, so a gesture that could only be refused cannot be started.
      const canLeave = compositions.some((one) => one.source === kind);
      const canArrive = compositions.some((one) => one.target === kind);
      return {
        dataIn: contract.some((edge) => edge.target === id) || canArrive,
        dataOut: contract.some((edge) => edge.source === id) || canLeave,
        execIn: flow.some((arrow) => arrow.target === id),
        execOut: flow.some((arrow) => arrow.source === id),
      };
    },
    [graph, hidden, placed, nodes, compositions],
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
      const open = frameBox(group, placed, nodes, layout);
      const box = collapsed ? { x: open.x, y: open.y, width: 260, height: 27 } : open;

      result.push({
        id: `frame:${group.id}`,
        type: "bpGroup",
        position: { x: box.x, y: box.y },
        style: { width: box.width, height: box.height },
        draggable: false,
        // Not React Flow's own selection: the frame is behind everything and must not
        // swallow a click meant for a member. Its **bar** selects, and that is a button.
        selectable: false,
        zIndex: 0,
        data: {
          node: group,
          verdict: (graph.verdicts[group.id] ?? "unproven") as never,
          reason: reasonFor(group.id),
          collapsed,
          memberCount: group.members.length,
          selected: group.id === selected,
          running: runningKinds.has(group.kind),
          onToggle: onToggleCollapse,
          onSelect,
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
          observation: graph.observations[node.id] ?? null,
          lit: litFiles.has(node.location.file),
          running: runningKinds.has(node.kind),
          expanded: layout[node.id]?.expanded ?? false,
          onExpand: onToggleExpand,
          onKnob,
          onMenu,
          pins: pinsOf(node.id),
        },
      });
    }
    return result;
  }, [
    nodes,
    placed,
    layout,
    hidden,
    graph,
    selected,
    litFiles,
    runningKinds,
    reasonFor,
    pinsOf,
    onSelect,
    onToggleCollapse,
    onToggleExpand,
    onKnob,
    onMenu,
  ]);

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

  /**
   * Where the nodes are **while they are being moved.**
   *
   * The drawn list comes from the graph and the stored layout, and for everything except a
   * drag that is the whole truth. A drag is the exception: the pointer moves every frame and
   * the position it produces is not a fact about the project yet -- so it lives here, in the
   * canvas, until the person lets go.
   *
   * Without this the node did not follow the pointer at all. Every frame's change was
   * discarded as "not finished yet", the node sat where the layout said, and it appeared at
   * the new place only when the drag ended: a teleport instead of a drag.
   */
  const [drawn, setDrawn] = useState<Node[]>(flowNodes);

  // The graph is the source of truth, so whenever it or the stored layout changes, what is
  // drawn is replaced rather than merged: a drag's leftovers must never outlive the drag.
  useEffect(() => setDrawn(flowNodes), [flowNodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Applied on every frame -- this is what makes the node follow the pointer -- but
      // **kept** only when the drag has finished. A file write behind the mouse would be a
      // write per frame, and a position mid-drag is not yet something the person chose.
      setDrawn((now) => applyNodeChanges(changes, now));

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
        nodes={drawn}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect(null)}
        // Connectable, and **nothing is added to `edges` here**: the handler writes code and
        // the picture catches up from the next read. React Flow would happily keep a wire it
        // was handed, which is exactly the flow-document architecture this project is not.
        nodesConnectable
        onConnect={(connection) => {
          if (connection.source && connection.target) {
            onConnect(connection.source, connection.target);
          }
        }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.25}
        maxZoom={1.6}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--grid-coarse)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
