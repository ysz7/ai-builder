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
import type { NodeKindInfo } from "./types";

let asked: Promise<NodeKindInfo[]> | null = null;

export function kindRegistry(): Promise<NodeKindInfo[]> {
  asked ??= graphKinds().then((answer) => answer.kinds);
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
