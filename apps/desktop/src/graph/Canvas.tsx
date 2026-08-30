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
 *
 * They can also be **hidden**, and that is a view preference and nothing more: a dense
 * agent draws an arrow per pair of nodes a test walked, which is a lot of ink over the one
 * thing a person is reading at the time. Hiding them changes nothing about the run -- the
 * evidence is still there, the marks are unmoved, and `Observe` is untouched -- so the
 * control belongs beside zoom rather than in the cluster the project's verbs live in.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyNodeChanges,
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import { TalkCard } from "./TalkCard";

import type { GraphNode, GraphRead, Layout, Placement } from "../core/types";
import { BpGroup } from "./BpGroup";
import { BpNode } from "./BpNode";
import { FlowEdge } from "./FlowEdge";
import { tintOf } from "./kinds";
import { descendants, frameBox, NODE_WIDTH, placeAll, TALK_WIDTH, topLevel } from "./place";

const nodeTypes = { bpNode: BpNode, bpGroup: BpGroup, bpTalk: TalkCard };
//: Flow arrows are drawn by their own component, which puts the arrowhead at the midpoint
//: rather than at the pin -- see `FlowEdge`. Contract edges keep the library's default.
const edgeTypes = { bpFlow: FlowEdge };

/**
 * A frame is drawn as a React Flow node, so it needs an id -- and it must not be the
 * group's, or the frame and the group would be the same element to every handler here.
 * The prefix is that separation, and these two are the only places it is spelled.
 */
const FRAME = "frame:";
const groupOf = (id: string): string | null => (id.startsWith(FRAME) ? id.slice(FRAME.length) : null);

/**
 * The chat card attached to a node (Q34). A prefix and not an id: nothing the core has ever
 * heard of, so it must be impossible to mistake for one -- both when a click asks what was
 * selected and when a drag asks what to store.
 */
const TALK = "talk:";
const talkOf = (id: string): string | null => (id.startsWith(TALK) ? id.slice(TALK.length) : null);

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
  /** Show one node in the Problems panel -- the mark on a card that is not green. */
  onProblems: (id: string) => void;
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
  /** Draw flow arrows, or leave them out. A view preference (Q13), never graph state. */
  showFlow: boolean;
  onToggleFlow: () => void;
  /**
   * The kinds a person can talk to, from `NodeKind.converses` (Q34).
   *
   * A set of kind names and **not a list of nodes**: which nodes get a chat card is the
   * registry's rule applied to the graph, the same derivation that used to decide whether
   * the button appeared. A list here would be a second opinion about the registry.
   */
  conversableKinds: Set<string>;
  /** The project, needed because the card holds a live conversation rather than a link. */
  project: string;
  /** A conversation is evidence while it is open (P17.4), so an answer re-reads the graph. */
  onAnswered: () => void;
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
  onProblems,
  onConnect,
  compositions,
  showFlow,
  onToggleFlow,
  conversableKinds,
  project,
  onAnswered,
}: Props) {
  const nodes = graph.graph.nodes;

  const placed = useMemo(() => placeAll(nodes, layout), [nodes, layout]);

  /**
   * A member of a collapsed group is not drawn -- but its group still carries its mark.
   *
   * The **whole subtree**, for the same reason the frame wraps one: folding a service left
   * its routers' routes on the canvas with nothing around them, which is not what folding
   * a region means.
   */
  const hidden = useMemo(() => {
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const set = new Set<string>();
    for (const group of nodes) {
      if (!layout[group.id]?.collapsed) continue;
      for (const { node } of descendants(group, byId)) set.add(node.id);
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
      const flow = (showFlow ? graph.flow : []).filter(
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
        // `|| conversable`: the dashed line from a chat card arrives at this pin, and an
        // edge whose handle was never rendered is dropped in silence -- the same trap the
        // frame's anchor exists for. Both conversable kinds happen to be groups today; this
        // is here so the first one that is not does not lose its line without saying so.
        dataIn:
          contract.some((edge) => edge.target === id) || canArrive || conversableKinds.has(kind),
        dataOut: contract.some((edge) => edge.source === id) || canLeave,
        execIn: flow.some((arrow) => arrow.target === id),
        execOut: flow.some((arrow) => arrow.source === id),
      };
    },
    [graph, hidden, placed, nodes, compositions, showFlow, conversableKinds],
  );

  /**
   * For each node, the top-level node it lives under -- itself, when it is top-level.
   *
   * A chat card is placed clear of *that* node's frame rather than of its subject's own
   * box, so a card never lands inside the region it is talking to no matter how deep the
   * subject sits. Which is the whole of "always to the right of the frame".
   */
  const topOwner = useMemo(() => {
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const map = new Map<string, GraphNode>();
    for (const top of topLevel(nodes)) {
      map.set(top.id, top);
      for (const { node } of descendants(top, byId)) map.set(node.id, top);
    }
    return map;
  }, [nodes]);

  /** For each group, every id under it. Held so a frame drag knows what it carries. */
  const subtreeOf = useMemo(() => {
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const map = new Map<string, string[]>();
    for (const node of nodes) {
      map.set(node.id, descendants(node, byId).map((entry) => entry.node.id));
    }
    return map;
  }, [nodes]);

  const flowNodes = useMemo<Node[]>(() => {
    const byId = new Map(nodes.map((node) => [node.id, node]));
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
        id: `${FRAME}${group.id}`,
        type: "bpGroup",
        position: { x: box.x, y: box.y },
        style: { width: box.width, height: box.height },
        // Draggable, and what moves is **its members**. A frame has no geometry of its
        // own -- it is the bounding box of what it contains -- so there is nothing about
        // it to store; dragging one is a way of moving a whole subtree at once, and the
        // frame arrives at the new place because its members did.
        draggable: true,
        // Not React Flow's own selection: the frame is behind everything and must not
        // swallow a click meant for a member. Its **bar** selects, and that is a button.
        selectable: false,
        // Behind the **edges** as well as behind the cards. React Flow puts its edges in a
        // sibling layer with no z-index of its own, so a frame at 0 won the tie on DOM
        // order and painted its background over every wire that crossed it. Negative is
        // what puts it under that layer; it stays above the pane, so its bar still takes a
        // click.
        zIndex: -1,
        data: {
          node: group,
          verdict: (graph.verdicts[group.id] ?? "unproven") as never,
          reason: reasonFor(group.id),
          collapsed,
          // What the frame draws around, which is the subtree and not one generation.
          memberCount: descendants(group, byId).length,
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
          lit: litFiles.has(node.location.file),
          running: runningKinds.has(node.kind),
          expanded: layout[node.id]?.expanded ?? false,
          onExpand: onToggleExpand,
          onKnob,
          onMenu,
          onProblems,
          pins: pinsOf(node.id),
        },
      });
    }

    // The chat cards (Q34). Derived from the registry's `converses` and from nothing else,
    // which is what keeps this a projection rather than a second graph: a kind that stops
    // naming a way in stops drawing one, and no gesture here can make or unmake one.
    for (const node of nodes) {
      if (hidden.has(node.id)) continue;
      if (!conversableKinds.has(node.kind)) continue;
      const key = `${TALK}${node.id}`;
      // **To the left of the frame, and always clear of it, whatever the subject is.**
      // Measuring from the node put a card on top of its own region whenever the subject
      // was a member rather than the group, and which of those it is depends on the
      // technology -- an agent is a group, a pipeline's stage is not. The region a card
      // must not overlap is the same one either way, so it is measured from the top-level
      // frame and never from the node. Left, because the graph grows rightwards from its
      // first column and a card on that side ends up in the path of everything added next.
      const owner = topOwner.get(node.id) ?? node;
      const box =
        owner.members.length > 0
          ? frameBox(owner, placed, nodes, layout)
          : { ...(placed[owner.id] ?? { x: 0, y: 0 }), width: NODE_WIDTH };
      const saved = layout[key];
      result.push({
        id: key,
        type: "bpTalk",
        position:
          saved?.x !== undefined && saved?.y !== undefined
            ? { x: saved.x, y: saved.y }
            : { x: box.x - TALK_WIDTH - 60, y: box.y },
        style: { width: TALK_WIDTH },
        // Not selectable: selecting it would put an id the core never issued into the
        // inspector. A click reaches the subject instead, see `onNodeClick`.
        selectable: false,
        zIndex: 2,
        data: { node: node.id, title: node.title, kind: node.kind, project, onAnswered },
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
    onProblems,
    conversableKinds,
    project,
    onAnswered,
    topOwner,
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

    for (const arrow of showFlow ? graph.flow : []) {
      if (!drawn(arrow.source) || !drawn(arrow.target)) continue;
      const observed = arrow.origin === "observed";
      edges.push({
        id: `flow:${arrow.source}->${arrow.target}`,
        source: arrow.source,
        target: arrow.target,
        sourceHandle: "exec-out",
        targetHandle: "exec-in",
        type: "bpFlow",
        // Read by the edge to colour its arrowhead. The line's own colour is below; the
        // mark cannot take it from a CSS variable it is not inside.
        data: { origin: arrow.origin },
        className: `bp-edge-flow${observed ? " is-observed" : " is-wiring"}`,
        style: {
          stroke: observed ? "var(--exec)" : "var(--exec-dim)",
          // Thinner and softened: after a run these are the loudest thing on the canvas,
          // and at the density of a real project near-black lines read as a wiring diagram
          // of something other than this graph.
          strokeWidth: 1.8,
          opacity: observed ? 0.5 : 0.4,
        },
        markerEnd: { type: "arrowclosed", color: observed ? "var(--exec)" : "var(--exec-dim)" } as never,
      });
    }
    // Card to subject. **Not a contract edge and not a flow arrow** -- it carries no type
    // and describes no order, it just says who is answering -- so it is drawn as neither:
    // dashed, unlabelled, and with no arrowhead to suggest a direction of execution.
    // A group is drawn as its frame, so the element to attach to is `frame:<id>` and not
    // the id itself -- an edge naming a node React Flow never rendered is dropped in
    // silence, which is how a line to an agent (the one kind that is always a group)
    // would have been simply absent.
    const groupIds = new Set(topLevel(nodes).filter((n) => n.members.length > 0).map((n) => n.id));
    for (const node of nodes) {
      if (hidden.has(node.id) || !conversableKinds.has(node.kind)) continue;
      // The card sits to the **left** of its subject, so the line runs card -> subject and
      // the pins swap ends: the card's is on its right, the subject's on its left. Drawn in
      // the direction the geometry actually goes, because a line doubling back around a
      // frame to reach a pin on the far side is unreadable however correct it is.
      edges.push({
        id: `talkline:${node.id}`,
        source: `${TALK}${node.id}`,
        sourceHandle: "talk-out",
        target: groupIds.has(node.id) ? `${FRAME}${node.id}` : node.id,
        targetHandle: groupIds.has(node.id) ? "talk-in" : "data-in",
        type: "smoothstep",
        className: "bp-edge-talk",
        style: { stroke: "var(--muted-3)", strokeWidth: 1.2, strokeDasharray: "3 4" },
      });
    }
    return edges;
  }, [graph, hidden, placed, nodes, showFlow, conversableKinds]);

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
  /**
   * The same list, readable synchronously.
   *
   * A frame drag needs the position the frame had **one event ago** to know how far it has
   * come, and a state variable read inside the handler is the one from the last render.
   */
  const drawnRef = useRef<Node[]>(flowNodes);
  const put = useCallback((next: Node[]) => {
    drawnRef.current = next;
    setDrawn(next);
  }, []);

  // The graph is the source of truth, so whenever it or the stored layout changes, what is
  // drawn is replaced rather than merged: a drag's leftovers must never outlive the drag.
  useEffect(() => put(flowNodes), [flowNodes, put]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const now = drawnRef.current;
      const at = new Map(now.map((node) => [node.id, node.position]));

      // A frame carries what is inside it. React Flow moves the frame element; the members
      // are moved here, on the same event, so the region and its contents never come apart
      // mid-drag -- and the frame's own position is thrown away at the next render, since
      // `frameBox` recomputes it from where the members ended up.
      const shifted = new Map<string, { x: number; y: number }>();
      for (const change of changes) {
        if (change.type !== "position" || !change.position) continue;
        const group = groupOf(change.id);
        const before = at.get(change.id);
        if (!group || !before) continue;
        const dx = change.position.x - before.x;
        const dy = change.position.y - before.y;
        if (dx === 0 && dy === 0) continue;
        for (const id of subtreeOf.get(group) ?? []) {
          const member = at.get(id);
          if (member) shifted.set(id, { x: member.x + dx, y: member.y + dy });
        }
      }

      // Applied on every frame -- this is what makes the node follow the pointer -- but
      // **kept** only when the drag has finished. A file write behind the mouse would be a
      // write per frame, and a position mid-drag is not yet something the person chose.
      const next = applyNodeChanges(changes, now);
      put(
        shifted.size === 0
          ? next
          : next.map((node) =>
              shifted.has(node.id) ? { ...node, position: shifted.get(node.id)! } : node,
            ),
      );

      const moved: Record<string, Placement> = {};
      for (const change of changes) {
        if (change.type !== "position" || change.dragging || !change.position) continue;
        const group = groupOf(change.id);
        if (group === null) {
          moved[change.id] = { ...layout[change.id], ...change.position };
          continue;
        }
        // The frame itself is never stored: it has no position of its own to keep, and an
        // entry for one would be a coordinate nothing reads (Q13). What is stored is where
        // its members ended up -- **all** of them, including the ones a collapsed frame is
        // hiding, which is why the total is measured against the derived box rather than
        // read off the drawn elements. Nothing is drawn for a member that is not shown.
        const origin = flowNodes.find((one) => one.id === change.id)?.position;
        if (!origin) continue;
        const dx = change.position.x - origin.x;
        const dy = change.position.y - origin.y;
        for (const id of subtreeOf.get(group) ?? []) {
          const base = placed[id];
          if (base) moved[id] = { ...layout[id], x: base.x + dx, y: base.y + dy };
        }
      }
      if (Object.keys(moved).length > 0) onMove(moved);
    },
    [flowNodes, layout, onMove, placed, put, subtreeOf],
  );

  return (
    <div className="bp-canvas">
      <ReactFlow
        nodes={drawn}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        // A frame opens its group. It is drawn as a region and it *is* a node -- the
        // service, the pipeline, the queue -- so a click anywhere on it has to reach the
        // same inspector its bar does. Passing the element's id straight through selected
        // `frame:api`, which is nothing the graph has ever heard of, so the panel came up
        // empty and the frame read as unclickable.
        // A chat card selects **nothing**. Reaching the subject was the obvious mapping and
        // it was wrong: the card is a place a person is typing, and a click inside it that
        // threw the inspector open over the canvas moved the thing they were looking at.
        // It is not a node, so there is nothing here for a selection to mean.
        onNodeClick={(_, node) =>
          talkOf(node.id) === null ? onSelect(groupOf(node.id) ?? node.id) : undefined
        }
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
        {/* The reference's ground: a tight dot field on near-white, fine enough to read as a
            texture rather than as a grid somebody is meant to align to. 22px apart the dots
            were sparse enough to look like a measurement. */}
        <Background
          variant={BackgroundVariant.Dots}
          gap={15}
          size={1.4}
          color="var(--grid-coarse)"
        />
        <Controls showInteractive={false} position="bottom-right">
          {/* A view control, beside zoom rather than in the cluster: hiding an arrow says
              nothing about the project, and a switch that lived next to `Observe` would
              read as one that changes what a run means. */}
          <ControlButton
            onClick={onToggleFlow}
            title={showFlow ? "Hide flow arrows" : "Show flow arrows"}
            aria-label={showFlow ? "Hide flow arrows" : "Show flow arrows"}
            aria-pressed={showFlow}
          >
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <path
                d="M4 12h13m0 0-4-4m4 4-4 4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {showFlow ? null : (
                <path
                  d="M3 21 21 3"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                />
              )}
            </svg>
          </ControlButton>
        </Controls>
      </ReactFlow>
    </div>
  );
}
