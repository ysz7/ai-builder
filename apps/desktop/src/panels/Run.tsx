/**
 * `Run`: call this node's export, once, with input a person typed.
 *
 * **This is not the graph being executed, and the whole shape of the panel says so.** It
 * lives on one node, it offers exactly the exports that node's kind requires, and there is
 * nothing here that could ever mean "and then the next one". Execution order lives in
 * Python; the canvas has no opinion about it and neither does this.
 *
 * **It colours nothing.** A call that returned is not evidence — green is earned by a passing
 * test that executed the code, which is Observe's answer and only Observe's. So the result
 * shows up here, in the panel, beside the button that asked for it, and never on the card.
 *
 * The form for each kind comes from the convention and from nowhere else:
 *
 * | Kind | What you can ask for | Which export answers |
 * | --- | --- | --- |
 * | RAG | upload documents, or run a query | `index`, `search` |
 * | Agent | a message | `run` |
 * | Service | a request on a route | `app` |
 * | Worker | a handler and a payload | `HANDLERS` |
 *
 * There is no request builder, no history and no saved runs. What a call returned is kept
 * until the next one replaces it, because a panel that forgot the moment you looked away
 * would make you press the button twice.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import { runLast, runRead, runStart, runStop } from "../core/client";
import type { GraphNode, RunResult } from "../core/types";

/** How often the call is polled while it runs. Output is polled, never pushed (P13). */
const BEAT = 300;

/** What the file's own name is, for a list that would otherwise be all prefix. */
function nameOf(path: string): string {
  return path.replace(/[/\\]+$/, "").split(/[/\\]/).pop() ?? path;
}

/**
 * What came back, shown as what it is.
 *
 * A string is prose — an agent's reply is meant to be read — and everything else is JSON,
 * because the shape belongs to the person's own code. A renderer that recognised "chunks"
 * or "a response" would be this application deciding what somebody's `search` returns.
 */
function Value({ value }: { value: unknown }) {
  if (typeof value === "string") return <div className="bp-run-reply">{value}</div>;
  return <pre className="bp-run-json">{JSON.stringify(value, null, 2)}</pre>;
}

export function Run({ project, node }: { project: string; node: GraphNode }) {
  /** The last answer, and what it printed. One state, because the core sends one shape. */
  const [state, setState] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState("");
  const [refused, setRefused] = useState("");

  // What is in the form. Held per node id, so moving between nodes does not carry a query
  // from one system into another.
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("/");
  const [body, setBody] = useState("");
  const [handler, setHandler] = useState("");
  const [payload, setPayload] = useState("{}");

  const offset = useRef(0);

  useEffect(() => {
    let live = true;
    setState(null);
    setLog("");
    setRefused("");
    setQuery("");
    setMessage("");
    setMethod("GET");
    setPath("/");
    setBody("");
    setHandler("");
    setPayload("{}");
    offset.current = 0;
    // A read. Opening a panel must never run somebody's code, so this asks what the node
    // last answered and starts nothing.
    void runLast(project, node.id)
      .then((answer) => {
        if (!live) return;
        setState(answer);
        setRunning(answer.running);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [project, node.id]);

  // Polled while it runs, with the offset the core last gave us. It stops on its own: the
  // core reports `running` false only once the answer is written down, so the reply that
  // ends the loop is the reply that carries the result.
  useEffect(() => {
    if (!running) return;
    let live = true;
    const tick = async () => {
      while (live) {
        try {
          const answer = await runRead(project, node.id, offset.current);
          offset.current = answer.offset;
          if (answer.output) setLog((held) => held + answer.output);
          if (!answer.running) {
            setState(answer);
            setRunning(false);
            return;
          }
        } catch (error) {
          setRefused(error instanceof Error ? error.message : String(error));
          setRunning(false);
          return;
        }
        await new Promise((wake) => setTimeout(wake, BEAT));
      }
    };
    void tick();
    return () => {
      live = false;
    };
  }, [running, project, node.id]);

  const start = useCallback(
    async (action: string, input: Record<string, unknown>) => {
      setRefused("");
      setLog("");
      offset.current = 0;
      try {
        const started = await runStart(project, node.id, action, input);
        setRunning(started.running);
        // A call that never started still answered, with the reason. That is a result and it
        // is shown as one rather than as a panel that does nothing.
        if (!started.ok) setRefused(started.detail);
      } catch (error) {
        setRunning(false);
        setRefused(error instanceof Error ? error.message : String(error));
      }
    },
    [project, node.id],
  );

  const upload = useCallback(async () => {
    // The native picker is the shell's, not a core method: a file chooser is a window, and
    // the core has no window. What it hands back is a list of paths for `index`.
    const chosen = await openDialog({ multiple: true, directory: false });
    const paths = Array.isArray(chosen) ? chosen : typeof chosen === "string" ? [chosen] : [];
    if (paths.length > 0) await start("index", { paths });
  }, [start]);

  const kind = node.kind;
  const outcome = state?.outcome ?? null;
  const documents = state?.documents ?? [];

  let form: React.ReactNode = null;

  if (kind === "rag") {
    form = (
      <>
        <div className="bp-run-line">
          <input
            className="bp-field"
            placeholder="What are you looking for?"
            value={query}
            disabled={running}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && query) void start("search", { query });
            }}
          />
          <button
            className="bp-run-go"
            disabled={running || !query}
            onClick={() => void start("search", { query })}
          >
            Search
          </button>
        </div>
        <button className="bp-run-second" disabled={running} onClick={() => void upload()}>
          Upload documents
        </button>
        {/* What was handed to `index` from this window. Said as exactly that: the convention
            gives a RAG package two exports and neither of them lists anything, so this is a
            memory of uploads and never a claim about what the index holds. */}
        {documents.length > 0 ? (
          <div className="bp-run-docs">
            <span className="bp-run-docs-cap">Uploaded from here ({documents.length})</span>
            {documents.map((one) => (
              <code key={one} title={one}>
                {nameOf(one)}
              </code>
            ))}
          </div>
        ) : null}
      </>
    );
  } else if (kind === "agent") {
    form = (
      <div className="bp-run-line">
        <textarea
          className="bp-field"
          rows={2}
          placeholder="Say something to it"
          value={message}
          disabled={running}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button
          className="bp-run-go"
          disabled={running || !message}
          onClick={() => void start("run", { message })}
        >
          Send
        </button>
      </div>
    );
  } else if (kind === "api") {
    form = (
      <>
        <div className="bp-run-line">
          <select
            className="bp-field bp-field-slim"
            value={method}
            disabled={running}
            onChange={(event) => setMethod(event.target.value)}
          >
            {["GET", "POST", "PUT", "PATCH", "DELETE"].map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
          {/* Typed, not chosen from a list. Which routes exist is a question only the
              application can answer, and answering it would mean reading a framework's
              router — the one thing the convention exists to avoid knowing about. */}
          <input
            className="bp-field"
            placeholder="/health"
            value={path}
            disabled={running}
            onChange={(event) => setPath(event.target.value)}
          />
          <button
            className="bp-run-go"
            disabled={running || !path}
            onClick={() => void start("request", { method, path, body })}
          >
            Send
          </button>
        </div>
        {method === "GET" || method === "DELETE" ? null : (
          <textarea
            className="bp-field"
            rows={2}
            placeholder="Request body"
            value={body}
            disabled={running}
            onChange={(event) => setBody(event.target.value)}
          />
        )}
      </>
    );
  } else if (kind === "worker") {
    // The handler names come from a run of `handlers`, which reads `HANDLERS` itself — the
    // export the convention already requires. Nothing static is parsed to guess at them.
    const named = outcome?.action === "handlers" && Array.isArray(outcome.value)
      ? (outcome.value as unknown[]).filter((one): one is string => typeof one === "string")
      : [];
    form = (
      <>
        <div className="bp-run-line">
          {named.length > 0 ? (
            <select
              className="bp-field"
              value={handler}
              disabled={running}
              onChange={(event) => setHandler(event.target.value)}
            >
              <option value="">Pick a handler</option>
              {named.map((one) => (
                <option key={one} value={one}>
                  {one}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="bp-field"
              placeholder="Handler name"
              value={handler}
              disabled={running}
              onChange={(event) => setHandler(event.target.value)}
            />
          )}
          <button
            className="bp-run-go"
            disabled={running || !handler}
            onClick={() => {
              let given: unknown = {};
              try {
                given = payload.trim() ? JSON.parse(payload) : {};
              } catch {
                setRefused("the payload is not JSON, and the handler takes an object");
                return;
              }
              void start("handle", { handler, payload: given });
            }}
          >
            Run
          </button>
        </div>
        <textarea
          className="bp-field"
          rows={2}
          placeholder="{}"
          value={payload}
          disabled={running}
          onChange={(event) => setPayload(event.target.value)}
        />
        <button className="bp-run-second" disabled={running} onClick={() => void start("handlers", {})}>
          List its handlers
        </button>
      </>
    );
  }

  if (form === null) return null;

  return (
    <div className="bp-run">
      <span className="bp-node-label">
        Run
        {running ? (
          <button className="bp-run-stop" onClick={() => void runStop(project, node.id)}>
            Stop
          </button>
        ) : null}
      </span>

      {/* Said before the button is pressed rather than after: a half-written package has no
          export to call, and the way out of that is the sentence the parser already wrote. */}
      {node.missing.length > 0 ? (
        <div className="bp-node-why">{node.reason}</div>
      ) : (
        <div className="bp-run-form">{form}</div>
      )}

      {refused ? <div className="bp-node-why">{refused}</div> : null}

      {/* What the project's own code printed, unedited, while it ran. */}
      {log ? <pre className="bp-run-log">{log}</pre> : null}

      {outcome ? (
        <div className="bp-run-answer">
          <div className="bp-run-when">
            {outcome.action} · {outcome.at}
          </div>
          {/* The traceback verbatim, never repaired into something plausible: it is the way
              out of the state the code is actually in. */}
          {outcome.ok ? (
            <Value value={outcome.value} />
          ) : (
            <pre className="bp-run-json is-error">{outcome.error}</pre>
          )}
        </div>
      ) : null}
    </div>
  );
}
