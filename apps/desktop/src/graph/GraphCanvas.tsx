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

import type {
  ComposeService,
  McpProbe,
  DatabaseResult,
  Graph,
  Layout,
  Observation,
  StatusResult,
} from "../core/types";
import { ContainerCard } from "./ContainerCard";
import { dependencyOf } from "./services";
import { FileCard } from "./FileCard";
import { Frame } from "./Frame";
import { PendingCard } from "./PendingCard";
import { SystemCard } from "./SystemCard";
import {
  CONTAINER_HEIGHT,
  CONTAINER_WIDTH,
  NODE_WIDTH,
  cardHeight,
  cardWidth,
  foldEdges,
  frameBox,
  isExpanded,
  pendingSpot,
  placeAll,
  serviceId,
  visible,
} from "./place";

const NODE_TYPES = {
  system: SystemCard,
  file: FileCard,
  frame: Frame,
  pending: PendingCard,
  container: ContainerCard,
};

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
  pending,
  services,
  composed,
  dockerless,
  database,
  statuses,
  checking,
  onRecheck,
  probes,
  costs,
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
  /**
   * Which kind is being written right now, or `""`.
   *
   * A **progress indicator, not a node**: it is placed rather than laid out, it is never
   * written to `layout.json`, and it carries none of a node's affordances. See
   * `PendingCard` — every one of those absences is what stops it outliving its turn.
   */
  pending: string;
  /**
   * The services this project's compose file declares.
   *
   * **Held beside the graph, never folded into it** — the same decision the verdict set has,
   * and for the same reasons: they answer a different question, they go stale at a different
   * moment, and one of them costs a subprocess. They are never coloured, because nothing in
   * a test run proves a container.
   */
  services: string[];
  /**
   * What the compose file declares about each of them, or `[]` where it could not be read.
   *
   * Only two things on the canvas use it: the state on a container's card, and the line
   * between a container and the dependency it **is**. The names still come from
   * `docker compose config --services`, asked of the program that owns the format.
   */
  composed: ComposeService[];
  /** Why the container list is empty, when it is empty for a reason. `""` otherwise. */
  dockerless: string;
  /**
   * What the project's storage is, or null where it has none.
   *
   * The **node** is in the graph, because the facts come from the project's own Python which
   * the parser already reads. This is the reading of it — how many tables, what it points at
   * — held beside the graph like the verdict set, because it goes stale at a different
   * moment and costs a walk of the project to produce.
   */
  database: DatabaseResult | null;
  /**
   * What a connection last answered for each dependency, and which are in flight.
   *
   * Held beside the graph like the verdict set, and for the same reasons: it answers a
   * different question and goes stale at a different moment. A node with no entry has **no
   * status** rather than a default one.
   */
  statuses: Record<string, StatusResult>;
  checking: string[];
  onRecheck: (node: string) => void;
  /**
   * What each MCP server last answered, where one has been asked.
   *
   * **Only a probe puts an entry here.** A server nobody asked has none, and the card draws
   * nothing rather than "not connected" — a state nobody checked and a state that was checked
   * and came back negative are different claims, and merging them would be a tick nobody
   * verified wearing the other's clothes.
   */
  probes: Record<string, McpProbe>;
  /**
   * What each node's last run cost, already worded, for the nodes where one was measured.
   *
   * Held beside the graph like the verdict set and the statuses, and for the same reason: it
   * comes from a different mechanism and goes stale at a different moment. A node with no
   * entry has no cost — never a zero, which would be a claim.
   */
  costs: Record<string, string>;
}) {
  const { nodes, edges } = useMemo(() => {
    if (!graph || !graph.ok) return { nodes: [] as Node[], edges: [] as Edge[] };

    const found = new Map(
      (observation?.verdicts ?? []).map((verdict) => [verdict.node, verdict]),
    );
    const shown = visible(graph, layout);
    // The cards that carry a cost line are taller by that line, so the layout has to know
    // which ones they are — the same arithmetic in both places or the frames would sit
    // wrong the first time somebody ran something.
    const costed = new Set(Object.keys(costs).filter((id) => costs[id]));
    const placed = placeAll(graph, layout, services, costed);
    const drawn = foldEdges(graph, shown);

    // A container and the dependency it *is*, joined.
    //
    // Not an import and never drawn as one: nothing in the project's Python points at a
    // container, and this line says "these two boxes are one thing" rather than "this calls
    // that". So it is dotted, unlabelled and carries no arrow — and it exists only where the
    // match is a literal fact about the entry, an image repository or a container port. A
    // container the project does not talk to stays unattached.
    const dependencies = shown
      .filter((node) => node.kind === "dependency")
      .map((node) => node.id);
    const sameAs = composed
      .filter((service) => services.includes(service.name))
      .map((service) => ({
        service: service.name,
        dependency: dependencyOf(service, dependencies),
      }))
      .filter((link) => link.dependency !== "");

    // A pin is drawn only where an edge lands on it. Four pins on every card would be a
    // picture of what *could* be connected, and nothing here can be connected.
    //
    // The left pin counts only the edges that land on the **package**: one that lands on a
    // port has its own pin in the port's row, and a body pin nothing arrives at is the same
    // decoration this rule exists to prevent. `foldEdges` has already cleared the port of
    // any edge whose target does not draw rows, so the test here is the port alone.
    const pinned = {
      in: new Set([
        ...drawn.filter((e) => e.kind === "import" && !e.port).map((e) => e.target),
        // A pin an edge *does* use and that is not drawn is worse than a decorative one:
        // React Flow cannot place the line at all, and the relation silently disappears.
        ...sameAs.map((link) => link.dependency),
      ]),
      out: new Set(drawn.filter((e) => e.kind === "import").map((e) => e.source)),
      up: new Set(drawn.filter((e) => e.kind === "mcp").map((e) => e.target)),
      down: new Set(drawn.filter((e) => e.kind === "mcp").map((e) => e.source)),
    };

    const flow: Node[] = [];

    // The frames first, so they sit behind the cards they wrap. React Flow paints in array
    // order and a region drawn over its own members would swallow every click on them.
    for (const system of shown) {
      if (system.parent !== "" || !isExpanded(layout, system.id)) continue;
      const box = frameBox(system, shown, placed, costed);
      if (!box) continue;
      // Counted by kind rather than named after the parent: an agent that contains two
      // sub-agents and a tool is not holding three agents, and the bar has to say what is
      // actually in it or it is a label that disagrees with the cards under it.
      const tally = new Map<string, number>();
      for (const member of shown) {
        if (member.parent !== system.id) continue;
        tally.set(member.kind, (tally.get(member.kind) ?? 0) + 1);
      }
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
          parts: [...tally.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([kind, count]) => ({ kind, count })),
          verdict: found.get(system.id)?.verdict ?? "",
          onToggle,
        },
      });
    }

    for (const node of shown) {
      flow.push({
        id: node.id,
        // A server is not a package: it is drawn as the declared thing it is, beside the
        // containers, rather than as a card with its contract and its verdict left blank.
        type:
          node.kind === "file"
            ? "file"
            : node.kind === "mcp" || node.kind === "dependency"
            ? "container"
            : "system",
        position: placed[node.id] ?? { x: 0, y: 0 },
        ...sized(cardWidth(node), cardHeight(node, costed)),
        selected: node.id === selected,
        data:
          node.kind === "dependency"
            ? {
                name: node.name,
                kind: "dependency",
                status: checking.includes(node.id)
                  ? "checking"
                  : statuses[node.id]?.status ?? "",
                statusDetail: statuses[node.id]?.detail ?? "",
                onRefresh: () => onRecheck(node.id),
                // No file declares it, so the line under the name is the reading instead.
                // The count first: it is what a person came to the node to know, and the
                // connection string is what there is to say when there are no tables.
                where:
                  database && database.tables.length > 0
                    ? `${database.tables.length} table${
                        database.tables.length === 1 ? "" : "s"
                      }`
                    : database?.target ?? "",
                pinned: false,
                inbound: pinned.in.has(node.id),
              }
            : node.kind === "mcp"
            ? {
                name: node.name,
                kind: "mcp",
                // The tool count, where a probe earned it: `8 tools` is the evidence that
                // the connection works, and it replaces the file's name because it is the
                // more useful of the two once there is one.
                where: probes[node.id]?.connected
                  ? `${probes[node.id].tools.length} tool${
                      probes[node.id].tools.length === 1 ? "" : "s"
                    }`
                  : node.path,
                pinned: pinned.up.has(node.id),
                inbound: false,
                // Only the server knows whether it is connected — so this is empty until
                // one has been asked, and what it says then is what the server answered.
                status: probes[node.id]
                  ? probes[node.id].connected
                    ? "reachable"
                    : "unreachable"
                  : "",
                statusDetail: probes[node.id]?.detail ?? "",
                // `connected`, not `reachable`: a server that answered `tools/list` said
                // something a Postgres accepting a socket never did.
                statusLabel: probes[node.id]
                  ? probes[node.id].connected
                    ? "connected"
                    : "not connected"
                  : "",
              }
            : node.kind === "file"
            ? {
                node,
                pinned: pinned.up.has(node.id),
                // Said on the file that declares them, which is where a person would go
                // looking. Nowhere else on the canvas mentions containers at all when there
                // are none, and a banner for it would be noise on every project without one.
                note:
                  node.id !== "compose.yaml"
                    ? ""
                    : dockerless ||
                      (services.length > 0
                        ? `${services.length} container${services.length === 1 ? "" : "s"}`
                        : ""),
                onOpen: onSelect,
              }
            : {
                node,
                // File nodes are never coloured, and they never reach here: nothing runs
                // them, so nothing can prove them.
                verdict: found.get(node.id)?.verdict ?? "",
                reason: found.get(node.id)?.reason ?? "",
                // Never folded into the verdict, and never coloured: a run that cost money
                // is not a run that proved anything.
                cost: costs[node.id] ?? "",
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

    for (const name of services) {
      const id = serviceId(name);
      flow.push({
        id,
        type: "container",
        position: placed[id] ?? { x: 0, y: 0 },
        ...sized(CONTAINER_WIDTH, CONTAINER_HEIGHT),
        // A container is declared and nothing points at it: no import can, and compose's own
        // `depends_on` is a fact inside a file this codebase does not read.
        data: {
          name,
          kind: "container",
          where: "compose.yaml",
          pinned: false,
          inbound: false,
          // Drawn only where the line to a dependency actually leaves this card.
          outbound: sameAs.some((link) => link.service === name),
          // A container's state belongs to the `docker` node, which is the one thing that
          // can be asked. A dot on each service would be the same claim drawn many times.
          status: "",
          statusDetail: "",
        },
      });
    }

    // Last, so it draws over nothing and nothing draws over it. Not selectable and not
    // draggable: a marker a person could move would be a marker with a position, and a
    // position is the first step towards an entry in the layout.
    if (pending) {
      flow.push({
        id: "pending:",
        type: "pending",
        position: pendingSpot(graph, layout),
        // Its own size, not `cardHeight`'s: this card draws a different thing (a pulse and
        // a sentence) and borrowing a node's arithmetic would tie the two together.
        ...sized(NODE_WIDTH, 148),
        draggable: false,
        selectable: false,
        data: { kind: pending },
      });
    }

    const wires: Edge[] = drawn.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.kind === "mcp" ? "down" : "out",
      // An edge attaches to an exported symbol where the card draws one. `foldEdges` keeps
      // `port` only where the target actually has a row for it, so there is no handle named
      // here that the card did not render.
      targetHandle: edge.kind === "mcp" ? "up" : edge.port ? `port:${edge.port}` : "in",
      type: "smoothstep",
      // An MCP server is somebody else's process, reached over a protocol rather than
      // imported, so its line is dashed: the same relation drawn in the same weight would
      // claim the project contains it.
      animated: false,
      // Not on an `mcp` edge any more: the node it lands on is *named* for the server, and
      // the same word twice on one line reads as two facts.
      label: edge.kind === "mcp" ? undefined : edge.label || undefined,
      className: edge.kind === "mcp" ? "bp-edge-contract" : undefined,
      style: {
        stroke: edge.kind === "mcp" ? "var(--k-mcp)" : "var(--line-strong)",
        strokeWidth: 1.5,
        strokeDasharray: edge.kind === "mcp" ? "4 4" : undefined,
      },
    }));

    for (const link of sameAs) {
      wires.push({
        id: `same:${link.service}:${link.dependency}`,
        source: serviceId(link.service),
        target: link.dependency,
        sourceHandle: "same",
        targetHandle: "in",
        type: "smoothstep",
        className: "bp-edge-same",
        style: { stroke: "var(--line-strong)", strokeWidth: 1.5, strokeDasharray: "2 5" },
      });
    }

    return { nodes: flow, edges: wires };
  }, [
    graph,
    layout,
    observation,
    selected,
    onSelect,
    onToggle,
    onTalk,
    pending,
    services,
    composed,
    dockerless,
    database,
    statuses,
    checking,
    onRecheck,
    probes,
    costs,
  ]);

  /**
   * Which ids are real nodes.
   *
   * Membership, not a naming rule. A guard that skipped ids containing `:` would also skip a
   * package somebody legitimately called that — the ids are paths, and a colon in a
   * directory name is nobody's mistake but ours if we assume it away.
   */
  const real = useMemo(
    () =>
      new Set([
        ...(graph?.nodes ?? []).map((node) => node.id),
        // A container is not in the graph, but it *is* in the project — `compose.yaml`
        // declares it — so where a person put it is theirs to keep, like any other card.
        ...services.map(serviceId),
      ]),
    [graph, services],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      for (const change of changes) {
        if (change.type !== "position" || !change.position) continue;
        // **Only a real node's position is ever reported.** Frames and the pending marker are
        // already undraggable, so this should be unreachable — and it is here anyway, because
        // what it prevents is a coordinate for something that is not in the code reaching
        // `layout.json`. A marker with an entry is a marker that can outlive its turn, which
        // is the one way this phase could quietly break invariant 1.
        if (!real.has(change.id)) continue;
        onMove(change.id, change.position, change.dragging === false);
      }
    },
    [onMove, real],
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
