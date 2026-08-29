/**
 * The node-kind registry, asked once and kept for the window's lifetime.
 *
 * **Asked, never listed here.** Which verbs a node has, and which of them start a process,
 * is the registry's answer (§5.6): a kind opts in by naming a way in, and a kind that has
 * not opted in gets no button rather than one that does nothing. A list of kind names in the
 * interface would be a second opinion about the registry, and it would go stale the first
 * time somebody added a kind — which is exactly what happened while `fastapi.service` and
 * `mcp.service` were spelled out inside a panel.
 *
 * One module because two places need it now: the panel that draws the buttons, and the canvas
 * that has to know whether a node is the sort of thing that can be running.
 */

import { graphKinds } from "./client";
import type { GraphKinds, NodeKindInfo } from "./types";

let asked: Promise<GraphKinds> | null = null;

/**
 * The whole answer, not just its kinds.
 *
 * It used to hand back `answer.kinds` alone, which was enough while the only question was
 * "which kinds start a process". The library asks a second one -- what the families are and
 * in what order -- and that is in the same answer for the same reason: a family exists
 * because a kind named it, so a client that kept its own order would have a second opinion
 * about the registry (P19).
 */
export function kindRegistry(): Promise<GraphKinds> {
  asked ??= graphKinds();
  return asked;
}

/**
 * Which verb family starts each kind — `run`, `work`, `env` — for the kinds anything starts.
 *
 * A map rather than the whole registry, because this is the only question the canvas has: is
 * this node the sort of thing that can be running, and if so, whose state says so?
 */
export function startsByKind(kinds: NodeKindInfo[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const kind of kinds) if (kind.starts) map[kind.name] = kind.starts;
  return map;
}
