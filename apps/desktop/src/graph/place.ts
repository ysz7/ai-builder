/**
 * Where to draw a node that has no saved position.
 *
 * The layout cache answers "where do I draw this?" for the nodes the person has arranged.
 * This answers it for the rest -- a node the agent has just written, or a project opened
 * for the first time -- and it must be **deterministic**, so that opening the same project
 * twice without touching anything puts everything in the same place.
 *
 * Group frames are deliberately absent from this file. A frame has no geometry of its own:
 * it is the bounding box of what it contains, computed at render. That is why it can never
 * disagree with its members, and why moving a node moves the frame around it.
 */

import type { GraphNode, Layout } from "../core/types";

/** Somewhere on the canvas. Not a `Placement` -- that one also carries collapsed state. */
export type Point = { x: number; y: number };

export const NODE_WIDTH = 220;
const ROW = 132;
const COLUMN = 300;
const FRAME_PAD = 26;
const FRAME_TOP = 44;

/** The nodes no group claims. Top level is groups and artifact nodes only (Q4, Q10). */
export function topLevel(nodes: GraphNode[]): GraphNode[] {
  const claimed = new Set(nodes.flatMap((node) => node.members));
  return nodes.filter((node) => !claimed.has(node.id));
}

/**
 * A position for every node, saved ones kept and the rest placed beside their group.
 *
 * A saved entry always wins, including one whose node has moved to a different group: the
 * person put it there on purpose, and quietly relocating it would be the toolchain having
 * an opinion about their canvas.
 */
export function placeAll(nodes: GraphNode[], saved: Layout): Record<string, Point> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const placed: Record<string, Point> = {};
  const at = (id: string): Point | null => {
    const entry = saved[id];
    return entry && entry.x !== undefined && entry.y !== undefined
      ? { x: entry.x, y: entry.y }
      : null;
  };

  let column = 0;
  for (const group of topLevel(nodes)) {
    const x = 60 + column * COLUMN;
    let row = 0;

    // Deliberately no entry for the group: a frame is derived from what it contains.
    for (const memberId of group.members) {
      if (!byId.has(memberId)) continue;
      placed[memberId] = at(memberId) ?? { x: x + FRAME_PAD, y: 60 + FRAME_TOP + row * ROW };
      row += 1;
    }
    if (row === 0) placed[group.id] = at(group.id) ?? { x, y: 60 };
    column += 1;
  }

  // Anything the walk above missed -- a node whose parent is unresolved, say. It is still
  // in the graph, so it still gets drawn; the gate is what says the containment is wrong.
  let stray = 0;
  for (const node of nodes) {
    if (placed[node.id]) continue;
    placed[node.id] = at(node.id) ?? { x: 60 + stray * COLUMN, y: 640 };
    stray += 1;
  }
  return placed;
}

/** The box a frame draws around its members. Derived, never stored. */
export function frameBox(
  group: GraphNode,
  placed: Record<string, Point>,
): { x: number; y: number; width: number; height: number } {
  const members = group.members.map((id) => placed[id]).filter(Boolean) as Point[];
  const own = placed[group.id] ?? { x: 60, y: 60 };

  if (members.length === 0) {
    return { x: own.x, y: own.y, width: NODE_WIDTH + FRAME_PAD * 2, height: 84 };
  }

  const left = Math.min(...members.map((p) => p.x));
  const top = Math.min(...members.map((p) => p.y));
  const right = Math.max(...members.map((p) => p.x + NODE_WIDTH));
  const bottom = Math.max(...members.map((p) => p.y + 96));

  return {
    x: left - FRAME_PAD,
    y: top - FRAME_TOP,
    width: right - left + FRAME_PAD * 2,
    height: bottom - top + FRAME_TOP + FRAME_PAD,
  };
}
