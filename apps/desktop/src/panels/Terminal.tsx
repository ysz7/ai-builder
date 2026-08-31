/**
 * The terminal drawer: the shells the person opened, as tabs.
 *
 * A shell is not a verb on any node, which is exactly why it may run what a node's buttons
 * refuse: it makes no claim about the graph, colours nothing and is read by nothing. See
 * `shell.py`.
 *
 * There were process tabs here too -- the application's log, the worker's -- and they went
 * with the verbs that started those processes. `Run` and `Deploy` come back in Phase 5, and
 * their output belongs beside them rather than in a tab strip that is a list of things that
 * are usually not running.
 *
 * Everything here is **polled with an offset the caller keeps** (P13), and only while there
 * is something to read: a terminal that asked forever would be a push loop with extra steps.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  shellClose,
  shellList,
  shellOpen,
  shellRead,
  shellWrite,
} from "../core/client";
import type { ShellRef } from "../core/client";
import { Notice } from "./Notice";

const POLL_MS = 700;

type Props = {
  project: string;
};

export function Terminal({ project }: Props) {
  const [shells, setShells] = useState<ShellRef[]>([]);
  const [tab, setTab] = useState("");
  const [text, setText] = useState("");
  const [typed, setTyped] = useState("");
  const [failed, setFailed] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  const offset = useRef(0);
  const timer = useRef<number | null>(null);
  /**
   * A read is in flight.
   *
   * Two loops polling one log is not merely wasteful -- both advance the same offset, so
   * each of them gets half the output and the panel prints an interleaving of the two. The
   * nudge after typing is exactly when a second one would start.
   */
  const reading = useRef(false);
  const tail = useRef<HTMLPreElement | null>(null);
  const field = useRef<HTMLInputElement | null>(null);

  const isShell = shells.some((shell) => shell.id === tab);

  const stop = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  // The shells this project has open. Asked for rather than remembered: they belong to the
  // sidecar, and a panel that kept its own list would offer tabs for terminals that had
  // gone when it reconnected.
  useEffect(() => {
    void shellList(project)
      .then((answer) => setShells(answer.shells))
      .catch(() => undefined);
  }, [project]);

  const read = useCallback(async () => {
    if (reading.current) return;
    reading.current = true;
    try {
      if (!shells.some((shell) => shell.id === tab)) {
        stop();
        return;
      }
      const answer = await shellRead(project, tab, offset.current);
      if (!answer.ok) {
        // The shell has gone -- closed here, or exited on its own. Its tab goes with it.
        setShells((previous) => previous.filter((shell) => shell.id !== tab));
        stop();
        return;
      }
      offset.current = answer.offset;
      if (answer.output) setText((previous) => previous + answer.output);
      setFailed(null);
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
      stop();
      return;
    } finally {
      reading.current = false;
    }
    timer.current = window.setTimeout(() => void read(), POLL_MS);
  }, [project, tab, shells, stop]);

  // A different tab is a different shell: read it from the top rather than appending one
  // terminal's output to another's.
  useEffect(() => {
    offset.current = 0;
    setText("");
    void read();
    return stop;
    // `read` changes with the tab, which is the whole trigger. Shells changing must not
    // restart a read that is already going, so it is deliberately not in the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, tab]);

  // A tab that goes away takes the selection with it -- to the first shell still open, or
  // to nothing at all, which is what an empty drawer looks like.
  useEffect(() => {
    const known = shells.map((shell) => shell.id);
    if (!known.includes(tab)) setTab(known[0] ?? "");
  }, [shells, tab]);

  useEffect(() => {
    if (tail.current) tail.current.scrollTop = tail.current.scrollHeight;
  }, [text]);

  async function openOne() {
    setOpening(true);
    try {
      const answer = await shellOpen(project);
      if (!answer.ok) {
        setFailed(answer.detail);
        return;
      }
      setShells(answer.shells);
      setTab(answer.shell);
      window.setTimeout(() => field.current?.focus(), 0);
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setOpening(false);
    }
  }

  async function closeOne(shell: string) {
    try {
      const answer = await shellClose(project, shell);
      setShells(answer.shells);
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    }
  }

  /** Type into the shell. **Verbatim**: the newline is ours to send, and so is `\x03`. */
  async function send(line: string) {
    try {
      const answer = await shellWrite(project, tab, line);
      if (!answer.ok) setFailed(answer.detail);
      // The answer to a command arrives in the log like everything else, so the poll is
      // nudged rather than waited on -- otherwise the line sits there for up to a tick.
      if (timer.current === null) void read();
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="bp-term">
      <div className="bp-term-bar">
        {shells.map((shell, index) => (
          // A tab and its ✕ are two actions, so they are two buttons -- one nested in the
          // other would make every close a switch as well.
          <span
            key={shell.id}
            className={`bp-term-pick is-shell${tab === shell.id ? " is-on" : ""}`}
          >
            <button className="bp-term-open" onClick={() => setTab(shell.id)}>
              {shell.name || `shell ${index + 1}`}
            </button>
            <button
              className="bp-term-x"
              title="Close this terminal, and what is running in it"
              onClick={() => void closeOne(shell.id)}
            >
              ✕
            </button>
          </span>
        ))}

        <button
          className="bp-term-pick bp-term-add"
          disabled={opening}
          onClick={() => void openOne()}
          title="Open a terminal in the project's directory"
        >
          {opening ? "…" : "+"}
        </button>

        <span className="bp-term-state">
          {isShell ? "your shell, in the project's directory" : "no terminal open"}
        </span>
      </div>

      {failed ? (
        <Notice
          tone="failed"
          label="failed"
          text={failed}
          onClose={() => setFailed(null)}
        />
      ) : null}

      <pre className="bp-term-out" ref={tail} onClick={() => field.current?.focus()}>
        {text || (isShell ? "" : "Open a terminal with +.")}
      </pre>

      {/* Only an open shell has somewhere for this to go. */}
      {isShell ? (
        <div className="bp-term-in">
          <span className="bp-term-caret">›</span>
          <input
            ref={field}
            className="bp-term-field"
            value={typed}
            spellCheck={false}
            autoCapitalize="off"
            autoComplete="off"
            placeholder="type a command"
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void send(`${typed}\n`);
                setTyped("");
              } else if (event.key === "c" && event.ctrlKey) {
                // What ctrl-c means to a terminal, sent as what it is: a byte on the way in,
                // not a verb of ours. It is the only way to stop what is running in there.
                event.preventDefault();
                void send("\x03");
                setTyped("");
              } else if (event.key === "d" && event.ctrlKey) {
                event.preventDefault();
                void send("\x04");
              }
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
