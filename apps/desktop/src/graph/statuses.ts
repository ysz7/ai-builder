/**
 * Whether the things this project talks to can be reached, and when to ask again.
 *
 * **Background polling is the thing this file exists to prevent.** A window nobody is
 * looking at must not open connections, and a status is worth exactly what it costs to keep
 * fresh — so the policy is written here, in one place, rather than as an interval scattered
 * beside each node:
 *
 *   - On project open, everything is checked once. That is the answer a person came for.
 *   - While the window has focus, a local check runs every 10s and a credential every 60s.
 *     A local check is a socket on this machine; a credential is a file read that only
 *     changes when somebody edits it.
 *   - **When the window loses focus, every timer is cleared.** Not slowed, not batched —
 *     stopped. An idle laptop should be doing nothing at all on this project's behalf.
 *   - Any node can be asked again by hand, which is what the refresh control on the panel is.
 *
 * A status is held here and never folded into the graph. They answer different questions and
 * go stale at different moments: the graph is what the code says right now, and this is what
 * a connection answered a moment ago. A node with no entry has **no status** rather than a
 * default one — the same rule the verdict set follows, for the same reason.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { statusRead } from "../core/client";
import type { StatusResult } from "../core/types";

/** A socket on this machine. Cheap, and the answer changes while somebody is working. */
const LOCAL_MS = 10_000;
/** A file read. It changes when a person edits `.env`, which is not every ten seconds. */
const CREDENTIAL_MS = 60_000;

/**
 * The nodes whose status is a credential rather than a connection.
 *
 * **No check here is ever billable.** A status that costs money is one nobody can afford to
 * poll, and the free question — has this project been given a key — is the useful one. The
 * core decides this too; the list is repeated here only to pick an interval, and picking the
 * slower one for a node the core turns out to check live is a wasted second, never a wrong
 * answer.
 */
const CREDENTIALS = new Set(["anthropic", "openai"]);

export type Statuses = {
  /** What each dependency last answered. Absent means nothing has been asked yet. */
  known: Record<string, StatusResult>;
  /** Which are in flight right now. Drawn as `checking`, which is a state of ours. */
  checking: string[];
  /** Ask one again, now. The manual refresh every dependency node carries. */
  refresh: (node: string) => void;
};

export function useStatuses(project: string, nodes: string[]): Statuses {
  const [known, setKnown] = useState<Record<string, StatusResult>>({});
  const [checking, setChecking] = useState<string[]>([]);

  /**
   * The node list as a stable string.
   *
   * The array is re-derived from the graph on every render, so an effect that depended on
   * it would re-subscribe constantly and re-check the whole project each time — which is
   * the polling this file exists to bound, arriving by the back door.
   */
  const key = nodes.join(",");
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const ask = useCallback(
    async (node: string) => {
      if (!project) return;
      setChecking((at) => (at.includes(node) ? at : [...at, node]));
      try {
        const answer = await statusRead(project, node);
        if (live.current) setKnown((at) => ({ ...at, [node]: answer }));
      } catch {
        // A status that could not be asked is not a status. Leaving the previous answer in
        // place is the honest thing: it says what was true when it was last asked, and the
        // alternative is inventing `unreachable` from a transport failure of ours.
      } finally {
        if (live.current) setChecking((at) => at.filter((one) => one !== node));
      }
    },
    [project],
  );

  // Everything once, when the project opens. Before any timer and regardless of focus:
  // this is the answer the person came for, and it happens exactly once per project.
  useEffect(() => {
    if (!project) return;
    setKnown({});
    for (const node of key ? key.split(",") : []) void ask(node);
  }, [project, key, ask]);

  // And then only while somebody is looking. `focus` and `blur` rather than a poll of
  // `document.hasFocus()`, so the stop is immediate and the started timers are the only
  // ones that exist.
  useEffect(() => {
    if (!project || !key) return;
    let timers: number[] = [];

    const start = () => {
      const all = key.split(",");
      const local = all.filter((node) => !CREDENTIALS.has(node));
      const paid = all.filter((node) => CREDENTIALS.has(node));
      timers = [
        window.setInterval(() => local.forEach((node) => void ask(node)), LOCAL_MS),
        window.setInterval(() => paid.forEach((node) => void ask(node)), CREDENTIAL_MS),
      ];
    };
    const stop = () => {
      timers.forEach((one) => window.clearInterval(one));
      timers = [];
    };

    if (document.hasFocus()) start();
    const wake = () => {
      stop();
      start();
    };
    window.addEventListener("focus", wake);
    window.addEventListener("blur", stop);
    return () => {
      stop();
      window.removeEventListener("focus", wake);
      window.removeEventListener("blur", stop);
    };
  }, [project, key, ask]);

  const refresh = useCallback((node: string) => void ask(node), [ask]);

  return { known, checking, refresh };
}
