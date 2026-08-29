/**
 * How a kind and a verdict become something you can see.
 *
 * Two rules from the design, and they are the ones a convenience would erode first:
 *
 *   - **Colour identifies the kind, never the state.** In the reference it is the category
 *     tab sitting above the card -- `Input` blue, `Action` amber, `Output` green -- and
 *     ours carries the kind's *family* in that tab, in that geometry (P18.3).
 *   - **The quiet state is the unproven one.** A project nobody has run yet is grey, and
 *     green is spent on what a run earned (Q23).
 *
 * The kind itself comes from the registry (`graph.kinds`), never from a string invented
 * here -- an unregistered kind falls through to the neutral family rather than being
 * guessed at.
 */

import type { Verdict } from "../core/types";

/** The technology a kind belongs to, by its prefix. The registry's own rule. */
export function technologyOf(kind: string): string {
  return kind.split(".")[0] ?? "";
}

/**
 * The families, in the tint pair the reference's category tab wears: an ink and a ground.
 *
 * A pair rather than one colour because the tab is a filled chip and the card's edge is a
 * line, and the same hue cannot do both jobs at the two contrasts they need.
 */
const FAMILIES = new Set([
  "fastapi",
  "mcp",
  "langgraph",
  "rag",
  "queue",
  "docker",
  "db",
  "vector",
]);

/** The family, as a token suffix. Anything unregistered lands on the neutral one. */
export function familyOf(kind: string): string {
  const technology = technologyOf(kind);
  return FAMILIES.has(technology) ? technology : "none";
}

/** The ink: the card's edge, the tab's text, a contract wire leaving this node. */
export function tintOf(kind: string): string {
  const family = familyOf(kind);
  // db and vector have no ground of their own in the token file; they read as the
  // persistence family, which is what a compose file's services are.
  const token = family === "db" || family === "vector" ? "docker" : family;
  return `var(--k-${token})`;
}

/** The ground: the tab's fill, and nothing else. A card is never filled with a family. */
export function tintBgOf(kind: string): string {
  const family = familyOf(kind);
  const token = family === "db" || family === "vector" ? "docker" : family;
  return `var(--k-${token}-bg)`;
}

/** The mark in the corner. A question, never a warning triangle -- unproven is not a fault. */
export const MARKS: Record<Verdict, string> = {
  green: "✓",
  unproven: "?",
  broken: "✕",
};

export function verdictOf(verdicts: Record<string, string>, id: string): Verdict {
  const value = verdicts[id];
  return value === "green" || value === "broken" ? value : "unproven";
}

/** The short kind, for the header. `fastapi.route` reads as `route` beside a tinted rule. */
export function shortKind(kind: string): string {
  const parts = kind.split(".");
  return parts.length > 1 ? parts.slice(1).join(".") : kind;
}

/**
 * The family's name, as the tab says it.
 *
 * The registry's own word, capitalised and nothing else. The reference names a *role*
 * (`Input`, `Action`, `LLM`) because its nodes have roles; ours name the technology,
 * because that is the fact our graph actually holds -- inventing a role would be the
 * front end deciding something the code did not say.
 */
const NAMES: Record<string, string> = {
  fastapi: "FastAPI",
  mcp: "MCP",
  langgraph: "LangGraph",
  rag: "RAG",
  queue: "Queue",
  docker: "Docker",
  db: "Database",
  vector: "Vector store",
  none: "Node",
};

export function familyName(kind: string): string {
  return NAMES[familyOf(kind)] ?? "Node";
}

/**
 * The glyph in a card's header, one per family.
 *
 * Drawn here rather than pulled from an icon set: six paths are less than a dependency,
 * and every one of them has to answer to the same 24-box and the same stroke weight as
 * the rest of this application's marks.
 */
export const GLYPHS: Record<string, string> = {
  // a route: something arriving and being answered
  fastapi: "M4 12h11M11 8l4 4-4 4M17 5h3v14h-3",
  // a socket a foreign program is reached through
  mcp: "M8 4v6a4 4 0 0 0 8 0V4M12 14v6M8 20h8",
  // a state machine: two nodes and the edge between them
  langgraph: "M6 7a2 2 0 1 0 0-.01M18 17a2 2 0 1 0 0-.01M8 8l8 8M17 7l-9 9",
  // a store being read from
  rag: "M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2ZM4 6v12c0 1.1 3.6 2 8 2s8-.9 8-2V6",
  // work waiting in a line
  queue: "M4 7h10M4 12h13M4 17h7M19 10v7M16 14l3 3 3-3",
  // a container
  docker: "M4 10h4v4H4zM9 10h4v4H9zM14 10h4v4h-4zM9 5h4v4H9zM3 14c0 3 3 5 7 5s10-2 11-6",
  db: "M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2ZM4 6v12c0 1.1 3.6 2 8 2s8-.9 8-2V6",
  vector: "M12 3 3 8v8l9 5 9-5V8zM3 8l9 5 9-5M12 13v8",
  none: "M5 5h14v14H5z",
};

export function glyphOf(kind: string): string {
  return GLYPHS[familyOf(kind)] ?? GLYPHS.none;
}
