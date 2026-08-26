/**
 * What the processes this toolchain started have printed.
 *
 * **Not a shell.** Nothing here runs a command somebody typed: the core spawns exactly three
 * kinds of process -- the application, a worker and the agent -- and this reads the output of
 * the first two. Running arbitrary commands would be a new capability in the core with its
 * own decisions to make, not a thing a panel may quietly acquire.
 *
 * Output is **polled with an offset the caller keeps** (P13), and only while something is
 * running: a terminal that asked every second forever would be a push loop with extra steps.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { runLogs, workLogs } from "../core/client";
import type { RunState } from "../core/types";
import { Notice } from "./Notice";

const POLL_MS = 900;

type Source = "app" | "worker";

type Props = { project: string };

export function Terminal({ project }: Props) {
  const [source, setSource] = useState<Source>("app");
  const [text, setText] = useState("");
  const [state, setState] = useState<RunState>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const offset = useRef(0);
  const timer = useRef<number | null>(null);
  const tail = useRef<HTMLPreElement | null>(null);

  const stop = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const read = useCallback(async () => {
    try {
      const answer =
        source === "app"
          ? await runLogs(project, offset.current)
          : await workLogs(project, offset.current);
      offset.current = answer.offset;
      setState(answer.state);
      if (answer.logs) setText((previous) => previous + answer.logs);
      setFailed(null);
      // Nothing running means nothing more will be printed, so the asking stops. It starts
      // again when the panel is reopened or the source is switched.
      if (answer.state === null) {
        stop();
        return;
      }
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
      stop();
      return;
    }
    timer.current = window.setTimeout(() => void read(), POLL_MS);
  }, [project, source, stop]);

  // A different source is a different log: start it from the top rather than appending one
  // process's output to another's.
  useEffect(() => {
    offset.current = 0;
    setText("");
    setState(null);
    void read();
    return stop;
  }, [read, stop]);

  useEffect(() => {
    if (tail.current) tail.current.scrollTop = tail.current.scrollHeight;
  }, [text]);

  return (
    <div className="bp-term">
      <div className="bp-term-bar">
        {(["app", "worker"] as Source[]).map((which) => (
          <button
            key={which}
            className={`bp-term-pick${source === which ? " is-on" : ""}`}
            onClick={() => setSource(which)}
          >
            {which}
          </button>
        ))}
        <span className="bp-term-state">
          {state
            ? `pid ${state.pid}${state.port ? ` · port ${state.port}` : ""} · ${state.target}`
            : "not running"}
        </span>
        <button
          className="bp-term-pick"
          onClick={() => void read()}
          title="ask again"
        >
          ↻
        </button>
      </div>

      {failed ? (
        <Notice
          tone="failed"
          label="failed"
          text={failed}
          onClose={() => setFailed(null)}
        />
      ) : null}

      <pre className="bp-term-out" ref={tail}>
        {text ||
          (state
            ? "Running, and it has printed nothing yet."
            : "Nothing is running. Start the application from its node.")}
      </pre>
    </div>
  );
}
