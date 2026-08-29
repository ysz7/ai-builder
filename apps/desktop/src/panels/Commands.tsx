/**
 * The commands the project already has, one the person wrote, and one of them running
 * (P17.6, P17.7 as amended by Q22).
 *
 * **Nothing here is on the graph** (Q20). A front end is run, not modelled: it has no claim
 * this toolchain could prove, and a node that cannot be red is decoration. So there are no
 * nodes, no knobs and no verdict — a list the tool itself produced, and a choice.
 *
 * **The list is npm's own answer** about npm's own file. Nothing here reads `package.json`:
 * a parser for somebody else's format is a second opinion about a thing that already has a
 * first one (§5.8), and the core asks `npm pkg get scripts` instead.
 *
 * **The field beside it runs what is typed.** P17.7 refused that — a verb running an
 * arbitrary string would be a shell with a button on it — and Q22 removed the rule: this
 * application has a real shell in it on purpose, nothing this verb starts goes on the graph,
 * and the refusal only ever stopped a person running their own test suite from the panel
 * listing their commands. A declared name still means the project's command, so the list and
 * the field cannot be made to disagree.
 *
 * **Each process is started on its own.** There is no button that brings the application up:
 * the order and the readiness of somebody else's topology is knowledge we do not have, and
 * one fallen link would redden all of it.
 *
 * Output is polled with an offset this side keeps, and only while something is running (P13).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  commandList,
  commandLogs,
  commandStart,
  commandState,
  commandStop,
} from "../core/client";
import type { CommandList, RunState } from "../core/types";
import { Notice } from "./Notice";

const POLL_MS = 900;

type Props = { project: string };

export function Commands({ project }: Props) {
  const [listed, setListed] = useState<CommandList | null>(null);
  const [directory, setDirectory] = useState("");
  /** A command of the person's own. Never remembered: it is a thing they are doing now. */
  const [own, setOwn] = useState("");
  const [state, setState] = useState<RunState>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  const offset = useRef(0);
  const timer = useRef<number | null>(null);
  const tail = useRef<HTMLPreElement | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const read = useCallback(async () => {
    try {
      const answer = await commandLogs(project, offset.current);
      offset.current = answer.offset;
      setState(answer.state);
      if (answer.logs) setText((previous) => previous + answer.logs);
      // Nothing running means nothing more will be printed, so the asking stops.
      if (answer.state === null) {
        stopPolling();
        return;
      }
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
      stopPolling();
      return;
    }
    timer.current = window.setTimeout(() => void read(), POLL_MS);
  }, [project, stopPolling]);

  const ask = useCallback(async () => {
    setBusy("list");
    try {
      const answer = await commandList(project, directory);
      setListed(answer);
      if (!answer.ok) setFailed(answer.detail);
      const running = await commandState(project);
      setState(running.state);
      if (running.state !== null) void read();
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }, [project, directory, read]);

  // Asked when the face is opened, because asking npm what a project declares changes
  // nothing — unlike starting one of them, which is why that stays a press (P11).
  useEffect(() => {
    void ask();
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the directory is applied on
    // its own button, so that typing into the field does not run npm on every keystroke.
  }, [project]);

  useEffect(() => {
    if (tail.current) tail.current.scrollTop = tail.current.scrollHeight;
  }, [text]);

  async function start(name: string) {
    setBusy(name);
    setFailed(null);
    try {
      const answer = await commandStart(project, name, directory);
      setState(answer.state);
      if (!answer.ok) setFailed(answer.detail || "it did not start");
      offset.current = 0;
      setText(answer.logs);
      if (answer.state !== null) void read();
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  async function stop() {
    setBusy("stop");
    try {
      await commandStop(project);
      stopPolling();
      setState(null);
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="bp-term">
      <div className="bp-term-bar">
        <input
          className="bp-field bp-field-slim"
          value={directory}
          placeholder="project root"
          spellCheck={false}
          title="a directory inside the project to ask in"
          onChange={(event) => setDirectory(event.target.value)}
        />
        <button className="bp-term-pick" disabled={busy !== ""} onClick={() => void ask()}>
          ↻
        </button>
        {/* The same slot the Terminal uses to say what a tab is. "nothing running" was
            true and told nobody what this panel was for, which is a poor trade for the one
            line of prose the surface gets. */}
        <span className="bp-term-state">
          {state
            ? `pid ${state.pid} · ${state.target}`
            : "the commands this project declares, and one of your own"}
        </span>
        {state ? (
          <button className="bp-term-pick" disabled={busy !== ""} onClick={() => void stop()}>
            {busy === "stop" ? "…" : "Stop"}
          </button>
        ) : null}
      </div>

      {failed ? (
        <Notice
          tone="refused"
          text={failed}
          onClose={() => setFailed(null)}
        />
      ) : null}

      {/* One line, and it is the same verb as the buttons below it: what the project
          declares and what the person wants are two ways to name a command, not two
          mechanisms. */}
      <div className="bp-cmd-own">
        <span className="bp-term-caret">›</span>
        <input
          className="bp-term-field"
          value={own}
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          placeholder="a command to run here — pytest -q, make build, git status"
          onChange={(event) => setOwn(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && own.trim() && state === null) void start(own);
          }}
        />
        <button
          className="bp-btn bp-btn-go"
          disabled={busy !== "" || state !== null || own.trim() === ""}
          onClick={() => void start(own)}
        >
          {busy === own ? "…" : "Run"}
        </button>
      </div>

      <div className="bp-cmds">
        {(listed?.commands ?? []).map((entry) => (
          <div className="bp-cmd" key={entry.name}>
            <button
              className="bp-btn"
              disabled={busy !== "" || state !== null}
              onClick={() => void start(entry.name)}
            >
              {busy === entry.name ? "…" : entry.name}
            </button>
            <span className="bp-cmd-line">{entry.command}</span>
          </div>
        ))}
        {listed && listed.commands.length === 0 ? (
          <div className="bp-empty">{listed.detail}</div>
        ) : null}
      </div>

      <pre className="bp-term-out" ref={tail}>
        {text ||
          (state
            ? "Running, and it has printed nothing yet."
            : "Nothing is running. Press one of the project's own commands, or type one.")}
      </pre>
    </div>
  );
}
