/**
 * How a kind and a verdict become something you can see.
 *
 * Two rules from the design, and they are the ones a convenience would erode first:
 *
 *   - **Colour identifies the kind, never the state.** It is a rule down the node's left
 *     edge, in one of three families: application code, runs elsewhere, carried by a file.
 *   - **Proven has no hue.** A working graph is quiet; colour appears only where something
 *     wants attention. Forty green badges would colour the screen exactly where nobody
 *     needs to look.
 *
 * The kind itself comes from the registry (`graph.kinds`), never from a string invented
 * here -- an unregistered kind falls through to the neutral rule rather than being guessed.
 */

import type { Verdict } from "../core/types";

/** The technology a kind belongs to, by its prefix. The registry's own rule. */
export function technologyOf(kind: string): string {
  return kind.split(".")[0] ?? "";
}

const TINTS: Record<string, string> = {
  fastapi: "var(--k-fastapi)",
  mcp: "var(--k-mcp)",
  langgraph: "var(--k-langgraph)",
  rag: "var(--k-rag)",
  queue: "var(--k-queue)",
  docker: "var(--k-docker)",
};

export function tintOf(kind: string): string {
  return TINTS[technologyOf(kind)] ?? "var(--k-none)";
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
