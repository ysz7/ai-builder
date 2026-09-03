/**
 * Where to draw a node that has no saved position, and what shape the canvas takes.
 *
 * Two rules govern everything here.
 *
 * **Position carries no meaning.** It does not set execution order and moving a node
 * changes nothing in the project — the graph is a projection of the code, not a document
 * that runs. So this file answers one question, "where do I draw this?", and it is allowed
 * no others.
 *
 * **It must be deterministic.** Opening the same project twice without touching anything
 * has to put everything in the same place, or the canvas moves under a person for reasons
 * they did not cause. A saved position always wins: they put it there on purpose.
 *
 * The frame around a system's children is deliberately absent from the layout it produces.
 * A frame has no geometry of its own — it is the box around what it contains, computed at
 * render — which is why it can never disagree with its members.
 */

import type { Graph, GraphEdge, GraphNode, Layout } from "../core/types";
import { isSystem } from "./kinds";

export type Point = { x: number; y: number };
export type Box = Point & { width: number; height: number };

/** Wide enough for a dotted path and a contract line to read without wrapping. */
export const NODE_WIDTH = 268;
/** One port row: the pin, the name, and the space between rows. Mirrors `.bp-card-port`. */
const PORT_ROW = 20;
/** The gap above the first row, where the pill's `margin-top` would otherwise be. */
const PORTS_TOP = 8;
/** Between rows. `.bp-card-ports` is a column with this gap. */
const PORT_GAP = 2;

/**
 * Does this card draw its ports as rows, or is its single entry point the card itself?
 *
 * **Asked in one place because four files have to agree on it**: the height arithmetic, the
 * card that draws the rows, the canvas that picks a handle, and the fold that rewrites an
 * edge. A second copy of this test is a card whose edges land somewhere it has no pin.
 *
 * One port is the node. An edge landing on `agent.run` and an edge landing on `agent` say
 * the same thing, and a row that restates the title is a second name for one thing — which
 * is why the plan grants an agent "a single port, drawn as before".
 */
export function hasPorts(node: GraphNode | undefined): boolean {
  return (node?.ports?.length ?? 0) > 1;
}

/** How much taller a card is for drawing its ports. Zero where it draws none. */
export function portsHeight(node: GraphNode): number {
  if (!hasPorts(node)) return 0;
  return PORTS_TOP + node.ports.length * PORT_ROW + (node.ports.length - 1) * PORT_GAP;
}

/** A file node says a name and nothing else, so it is given no more room than that. */
export const FILE_WIDTH = 176;
/** A container says a name and where it was declared. Between the two. */
export const CONTAINER_WIDTH = 200;
/** The tab, the header and the one line under it. Declared, as every size here now is. */
export const CONTAINER_HEIGHT = 22 + 44 + 20 + 12;

const COLUMN = 372;
const GUTTER = 30;
/** How far a child is set in from its parent. Containment, drawn as position. */
const INDENT = 24;
const FRAME_PAD = 22;
/** Room for the frame's bar, which is what carries the parent's name and its fold. */
const FRAME_TOP = 34;
const ORIGIN = 60;

/**
 * How tall a card will be, derived from what it will draw.
 *
 * An estimate rather than a measurement, because this runs *before* anything is drawn: it
 * answers "where does the next one go?" while the cards are still a list of nodes. It is
 * structural on purpose — the tab, the header, the path line, the reason where there is
 * one, the contract pill — so nothing that Observe will later add can move a person's
 * canvas as a side effect of running their tests.
 */
/**
 * How tall a card is, in the arithmetic the canvas draws with.
 *
 * **This is the size, not a guess at it.** `GraphCanvas` declares it on the node rather than
 * letting React Flow measure the rendered element, so a number here that disagrees with the
 * stylesheet is a layout that overlaps rather than a layout that self-corrects. Every term
 * matches a rule in `styles.css`; change one there and change it here.
 */
/** Nothing measured. The default, and the shape of a first look at a project. */
const EMPTY: ReadonlySet<string> = new Set<string>();

export function cardHeight(node: GraphNode, costed: ReadonlySet<string> = EMPTY): number {
  if (node.kind === "file") return 44;
  if (node.kind === "mcp") return CONTAINER_HEIGHT;
  // A dependency is the server's card plus its status row: the dot, the word and the
  // refresh. 6 above and 18 for the line, and those numbers are in `styles.css` too.
  if (node.kind === "dependency") return CONTAINER_HEIGHT + 24;
  return (
    22 + // the category tab, above the card and overlapping it
    44 + // the header row and the card's own padding
    20 + // the path line
    (node.reason ? 34 : 0) +
    // The syntax-error line. Its own row rather than sharing the reason's: they are
    // different claims — one is "this package does not export what its kind requires", the
    // other is "this file did not parse just now" — and a node can be in both states.
    (node.broken ? 18 : 0) +
    // What the last run cost, where a run has been measured. Drawn only then: a row that
    // always existed would invite a default to be put in it, and a node nobody has run has
    // no cost rather than a zero one.
    (costed.has(node.id) ? 18 : 0) +
    // The `Chat` action, drawn only on an agent that has the export to call, and the
    // repair action, drawn only where something is missing. Never both: an agent with a
    // missing `run` has nothing to chat with, which is why one of them is there instead.
    ((node.kind === "agent" && node.missing.length === 0) || node.missing.length > 0 ? 27 : 0) +
    // The ports, or the contract pill — never both. They would say the same thing twice on
    // a rag, whose ports *are* its contract, and a card says what it offers once. A tool has
    // no contract to state, so where it draws no rows it draws nothing at all.
    (hasPorts(node)
      ? portsHeight(node)
      : node.exports.length > 0
      ? 38
      : 0)
  );
}

export function cardWidth(node: GraphNode): number {
  if (node.kind === "file") return FILE_WIDTH;
  if (node.kind === "mcp" || node.kind === "dependency") return CONTAINER_WIDTH;
  return NODE_WIDTH;
}

/** Is this system showing its children, or a count? View state, and only ever that. */
export function isExpanded(layout: Layout, id: string): boolean {
  return layout[id]?.expanded === true;
}

/** The nodes the canvas draws: every top-level one, and a child only inside an open parent. */
export function visible(graph: Graph, layout: Layout): GraphNode[] {
  return graph.nodes.filter(
    (node) => node.parent === "" || isExpanded(layout, node.parent),
  );
}

/**
 * The visible node an edge should land on.
 *
 * A collapsed parent stands in for its children. Dropping the edge instead would make a
 * dependency disappear because somebody folded a card — the import is still there, and a
 * view state must not be able to contradict the code. Two children importing the same
 * system collapse to one line, which is what a folded parent is claiming.
 */
function stand(id: string, byId: Map<string, GraphNode>, drawn: Set<string>): string {
  let at: GraphNode | undefined = byId.get(id);
  while (at && !drawn.has(at.id)) at = at.parent ? byId.get(at.parent) : undefined;
  return at?.id ?? "";
}

/** The edges the canvas draws, each rerouted onto whatever is actually on screen. */
export function foldEdges(graph: Graph, shown: GraphNode[]): GraphEdge[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const drawn = new Set(shown.map((node) => node.id));
  const out = new Map<string, GraphEdge>();

  for (const edge of graph.edges) {
    const source = stand(edge.source, byId, drawn);
    const target = stand(edge.target, byId, drawn);
    if (!source || !target || source === target) continue;
    // A port belongs to the node the core named. Rerouted onto a collapsed parent it would
    // be a claim about a pin that parent does not have — and a card whose ports are drawn as
    // one line loses the distinction anyway, so the honest edge is the one to the package.
    const port =
      target === edge.target && hasPorts(byId.get(target)) ? edge.port : "";
    const id = `${source}->${target}:${edge.kind}:${edge.label}:${port}`;
    out.set(id, { ...edge, id, source, target, port });
  }
  return [...out.values()];
}

/**
 * A position for every visible node: saved ones kept, the rest placed.
 *
 * Systems take a column each in the order the core returned them, an open system's children
 * stack under it, and the four file nodes take a row along the bottom. The arrangement is
 * arbitrary and says nothing — what matters is that it is the same every time and that a
 * person can move any of it.
 */
export function placeAll(
  graph: Graph,
  layout: Layout,
  services: string[] = [],
  costed: ReadonlySet<string> = EMPTY,
): Record<string, Point> {
  const shown = visible(graph, layout);
  const placed: Record<string, Point> = {};
  const saved = (id: string): Point | null => {
    const entry = layout[id];
    return entry?.x !== undefined && entry.y !== undefined
      ? { x: entry.x, y: entry.y }
      : null;
  };

  // Named families, never "everything that is not a file": that negation meant "a package"
  // only while `file` was the sole exception to it, and an MCP server would have silently
  // joined the systems and taken a column of its own.
  const systems = shown.filter((node) => isSystem(node.kind) && node.parent === "");
  const files = shown.filter((node) => node.kind === "file");
  const servers = shown.filter((node) => node.kind === "mcp");
  // The database sits on the systems' row, to the right of them: it is what their code
  // talks to, and the import edges into it read left to right like every other one.
  const stores = shown.filter((node) => node.kind === "dependency");

  let column = 0;
  let deepest = 0;
  for (const system of systems) {
    const x = ORIGIN + column * COLUMN;
    placed[system.id] = saved(system.id) ?? { x, y: ORIGIN };

    let cursor = ORIGIN + cardHeight(system, costed) + GUTTER + FRAME_TOP;
    if (isExpanded(layout, system.id)) {
      for (const child of shown.filter((node) => node.parent === system.id)) {
        placed[child.id] = saved(child.id) ?? { x: x + INDENT, y: cursor };
        cursor += cardHeight(child, costed) + GUTTER;
      }
      cursor += FRAME_PAD;
    }
    deepest = Math.max(deepest, cursor);
    column += 1;
  }

  stores.forEach((store, index) => {
    placed[store.id] =
      saved(store.id) ?? { x: ORIGIN + (column + index) * COLUMN, y: ORIGIN };
  });

  // The files sit under everything, on one row. They are never coloured and they depend on
  // nothing, so they are the one part of the canvas with no relation to arrange around.
  const row = Math.max(deepest, ORIGIN + 200) + 90;
  files.forEach((file, index) => {
    placed[file.id] =
      saved(file.id) ?? { x: ORIGIN + index * (FILE_WIDTH + 26), y: row };
  });

  // The servers share the containers' row: both are things the project declares and nothing
  // proves, and giving each its own row would claim a distinction that is not there.
  servers.forEach((server, index) => {
    placed[server.id] =
      saved(server.id) ?? { x: ORIGIN + index * (CONTAINER_WIDTH + 26), y: row + 120 };
  });

  // The containers sit on their own row under the files. Below rather than beside, because
  // they are a different kind of fact: the files are the project's, and these are what
  // `docker compose` says the project asks to have running around it.
  services.forEach((name, index) => {
    const id = serviceId(name);
    placed[id] =
      saved(id) ??
      { x: ORIGIN + (servers.length + index) * (CONTAINER_WIDTH + 26), y: row + 120 };
  });

  // Anything the walk above missed — a child whose parent the core did not return, say. It
  // is in the graph, so it is drawn; being unplaceable is not a reason to hide a node.
  let stray = 0;
  for (const node of shown) {
    if (placed[node.id]) continue;
    placed[node.id] = saved(node.id) ?? { x: ORIGIN + stray * COLUMN, y: row + 140 };
    stray += 1;
  }
  return placed;
}

/**
 * The box a frame draws around a system's children. Derived, never stored.
 *
 * `null` when the system has none on screen: there is nothing to wrap, and a frame around
 * nothing is a region claiming a membership that does not exist.
 */
/**
 * A container's id on the canvas.
 *
 * Prefixed, because these are **not graph nodes** and must never be mistaken for one: they
 * are held beside the graph, exactly as the verdict set is, and a bare name could collide
 * with a package called the same thing. What the prefix buys is that the collision is
 * impossible rather than unlikely.
 */
export function serviceId(name: string): string {
  return `container:${name}`;
}

/**
 * Where a node being written would land: the next free column.
 *
 * The same arithmetic `placeAll` uses for a system, so the marker sits where the real node
 * will sit — and then the real one takes that spot when it arrives, which is what makes the
 * marker read as the thing appearing rather than as something else happening beside it.
 *
 * It is computed and never stored. A pending marker has no entry in `layout.json`, because
 * an entry is the first step towards it outliving the turn that drew it.
 */
export function pendingSpot(graph: Graph | null, layout: Layout): Point {
  const systems = graph
    ? visible(graph, layout).filter((node) => isSystem(node.kind) && node.parent === "")
    : [];
  return { x: ORIGIN + systems.length * COLUMN, y: ORIGIN };
}

export function frameBox(
  system: GraphNode,
  shown: GraphNode[],
  placed: Record<string, Point>,
  costed: ReadonlySet<string> = EMPTY,
): Box | null {
  const members = shown
    .filter((node) => node.parent === system.id)
    .map((node) => ({ at: placed[node.id], node }))
    .filter((member) => member.at !== undefined);
  if (members.length === 0) return null;

  const left = Math.min(...members.map((m) => m.at.x));
  const top = Math.min(...members.map((m) => m.at.y));
  const right = Math.max(...members.map((m) => m.at.x + cardWidth(m.node)));
  const bottom = Math.max(...members.map((m) => m.at.y + cardHeight(m.node, costed)));

  return {
    x: left - FRAME_PAD,
    y: top - FRAME_TOP,
    width: right - left + FRAME_PAD * 2,
    height: bottom - top + FRAME_TOP + FRAME_PAD,
  };
}
