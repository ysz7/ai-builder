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

export type Point = { x: number; y: number };
export type Box = Point & { width: number; height: number };

/** Wide enough for a dotted path and a contract line to read without wrapping. */
export const NODE_WIDTH = 268;
/** A file node says a name and nothing else, so it is given no more room than that. */
export const FILE_WIDTH = 176;

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
export function cardHeight(node: GraphNode): number {
  if (node.kind === "file") return 44;
  return (
    22 + // the category tab, above the card and overlapping it
    44 + // the header row and the card's own padding
    20 + // the path line
    (node.reason ? 34 : 0) +
    38 // the contract pill
  );
}

export function cardWidth(node: GraphNode): number {
  return node.kind === "file" ? FILE_WIDTH : NODE_WIDTH;
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
    const id = `${source}->${target}:${edge.kind}:${edge.label}`;
    out.set(id, { ...edge, id, source, target });
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
export function placeAll(graph: Graph, layout: Layout): Record<string, Point> {
  const shown = visible(graph, layout);
  const placed: Record<string, Point> = {};
  const saved = (id: string): Point | null => {
    const entry = layout[id];
    return entry?.x !== undefined && entry.y !== undefined
      ? { x: entry.x, y: entry.y }
      : null;
  };

  const systems = shown.filter((node) => node.kind !== "file" && node.parent === "");
  const files = shown.filter((node) => node.kind === "file");

  let column = 0;
  let deepest = 0;
  for (const system of systems) {
    const x = ORIGIN + column * COLUMN;
    placed[system.id] = saved(system.id) ?? { x, y: ORIGIN };

    let cursor = ORIGIN + cardHeight(system) + GUTTER + FRAME_TOP;
    if (isExpanded(layout, system.id)) {
      for (const child of shown.filter((node) => node.parent === system.id)) {
        placed[child.id] = saved(child.id) ?? { x: x + INDENT, y: cursor };
        cursor += cardHeight(child) + GUTTER;
      }
      cursor += FRAME_PAD;
    }
    deepest = Math.max(deepest, cursor);
    column += 1;
  }

  // The files sit under everything, on one row. They are never coloured and they depend on
  // nothing, so they are the one part of the canvas with no relation to arrange around.
  const row = Math.max(deepest, ORIGIN + 200) + 90;
  files.forEach((file, index) => {
    placed[file.id] =
      saved(file.id) ?? { x: ORIGIN + index * (FILE_WIDTH + 26), y: row };
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
export function frameBox(
  system: GraphNode,
  shown: GraphNode[],
  placed: Record<string, Point>,
): Box | null {
  const members = shown
    .filter((node) => node.parent === system.id)
    .map((node) => ({ at: placed[node.id], node }))
    .filter((member) => member.at !== undefined);
  if (members.length === 0) return null;

  const left = Math.min(...members.map((m) => m.at.x));
  const top = Math.min(...members.map((m) => m.at.y));
  const right = Math.max(...members.map((m) => m.at.x + cardWidth(m.node)));
  const bottom = Math.max(...members.map((m) => m.at.y + cardHeight(m.node)));

  return {
    x: left - FRAME_PAD,
    y: top - FRAME_TOP,
    width: right - left + FRAME_PAD * 2,
    height: bottom - top + FRAME_TOP + FRAME_PAD,
  };
}
