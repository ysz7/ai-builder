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

import type { GraphNode, Layout, Placement } from "../core/types";

/** Somewhere on the canvas. Not a `Placement` -- that one also carries collapsed state. */
export type Point = { x: number; y: number };

/**
 * The reference's cards are wide enough for a sentence of description and a field block to
 * read as prose rather than as a column of fragments, and ours carry the same things. 300
 * is where a docstring line stops wrapping every three words.
 */
export const NODE_WIDTH = 300;
const COLUMN = 396;
const FRAME_PAD = 26;
const FRAME_TOP = 52;
/** The gap between two stacked cards. Constant; what varies is the card, not the gap. */
const GUTTER = 26;

/**
 * How tall a card will be, derived from what it will draw.
 *
 * An estimate and not a measurement, because this file runs **before** anything is drawn:
 * it answers "where does the next one go?" and "how big is the frame around these?", and
 * both questions are asked while the cards are still a list of nodes. Deriving it from the
 * card's own anatomy is what keeps the two in step -- the old constant was written for a
 * two-line node, and the reference's card is not one, so a group's frame stopped short of
 * its own members the moment the card grew (P18.3).
 *
 * It is deliberately structural: knobs, a description line, the pill row. Nothing here
 * depends on a verdict or an observation, so the same graph lays out the same way before
 * and after somebody presses Observe -- a frame that resized itself when a test passed
 * would move the person's canvas as a side effect of running their tests.
 */
export function cardHeight(node: GraphNode, placement?: Placement): number {
  const shown = placement?.expanded ? node.knobs.length : Math.min(node.knobs.length, 3);
  return (
    22 + // the category tab, above the card and overlapping it
    46 + // the header row and the card's own padding
    (node.summary ? 22 : 0) +
    shown * 82 + // a field block: its label chip, its control, its margin
    (node.knobs.length > 3 ? 22 : 0) + // "n more"
    38 // the pill row
  );
}

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
    let cursor = 60 + FRAME_TOP;
    for (const memberId of group.members) {
      const member = byId.get(memberId);
      if (!member) continue;
      placed[memberId] = at(memberId) ?? { x: x + FRAME_PAD, y: cursor };
      // Stepped by the card's own height rather than by a fixed row: cards differ by
      // several field blocks now, and a constant stride either overlaps the tall ones or
      // strands the short ones in whitespace.
      cursor += cardHeight(member, saved[memberId]) + GUTTER;
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
  nodes: GraphNode[] = [],
  saved: Layout = {},
): { x: number; y: number; width: number; height: number } {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const members = group.members
    .map((id) => {
      const point = placed[id];
      const member = byId.get(id);
      return point ? { ...point, height: member ? cardHeight(member, saved[id]) : 150 } : null;
    })
    .filter(Boolean) as (Point & { height: number })[];
  const own = placed[group.id] ?? { x: 60, y: 60 };

  if (members.length === 0) {
    return { x: own.x, y: own.y, width: NODE_WIDTH + FRAME_PAD * 2, height: 84 };
  }

  const left = Math.min(...members.map((p) => p.x));
  const top = Math.min(...members.map((p) => p.y));
  const right = Math.max(...members.map((p) => p.x + NODE_WIDTH));
  // Each member's own height, so the frame ends below the tallest card rather than below a
  // constant somebody chose when cards were two lines.
  const bottom = Math.max(...members.map((p) => p.y + p.height));

  return {
    x: left - FRAME_PAD,
    y: top - FRAME_TOP,
    width: right - left + FRAME_PAD * 2,
    height: bottom - top + FRAME_TOP + FRAME_PAD,
  };
}
