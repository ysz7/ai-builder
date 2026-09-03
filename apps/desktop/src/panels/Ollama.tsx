/**
 * What this machine has pulled, and a way to pull another.
 *
 * The one dependency with panel content of its own, and the plan says why: Ollama is what
 * makes "no data leaves this machine" literally true, and that claim is answered by a list a
 * person can look at rather than by a paragraph on a website.
 *
 * **It is not a catalogue and must never become one.** Nothing here suggests a model, ranks
 * one or knows what any of them is for — the list is whatever the daemon says is on this
 * machine, and the field is a name a person types. A gallery of models we curated would be
 * stale the week after it shipped, and it is the catalogue the plan puts out of scope.
 *
 * A pull takes minutes, so it is polled with an offset this component keeps and the progress
 * is the core's own sentences. **Nothing is pulled because the panel was opened**: the list
 * is a read, and only the button fetches.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ollamaModels, ollamaPull, ollamaRead, ollamaStop } from "../core/client";
import type { OllamaResult } from "../core/types";

/** Bytes as a person reads them. The daemon reports bytes; nobody thinks in them. */
function size(bytes: number): string {
  if (bytes <= 0) return "";
  const giga = bytes / 1_000_000_000;
  if (giga >= 1) return `${giga.toFixed(giga >= 10 ? 0 : 1)}GB`;
  return `${Math.max(1, Math.round(bytes / 1_000_000))}MB`;
}

export function Ollama({ project }: { project: string }) {
  const [state, setState] = useState<OllamaResult | null>(null);
  const [wanted, setWanted] = useState("");
  const [progress, setProgress] = useState("");
  const [running, setRunning] = useState(false);
  const [refused, setRefused] = useState("");
  /** Where the log was last read to. The caller keeps the offset; nothing is pushed. */
  const offset = useRef(0);

  const list = useCallback(async () => {
    try {
      setState(await ollamaModels(project));
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, [project]);

  useEffect(() => {
    void list();
  }, [list]);

  // Only while a pull is going. A poll that outlived it would be this panel asking a
  // question whose answer stopped changing.
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const answer = await ollamaRead(project, offset.current);
        offset.current = answer.offset;
        if (answer.output) setProgress((at) => at + answer.output);
        if (!answer.running) {
          setRunning(false);
          // The list is what changed: a finished pull is a model that is now here.
          void list();
        }
      } catch {
        setRunning(false);
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [running, project, list]);

  const pull = useCallback(async () => {
    setRefused("");
    setProgress("");
    offset.current = 0;
    try {
      const answer = await ollamaPull(project, wanted);
      if (!answer.ok) {
        setRefused(answer.detail);
        return;
      }
      setRunning(true);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, [project, wanted]);

  return (
    <div className="bp-ollama">
      <span className="bp-node-label">Models on this machine</span>

      {state && !state.ok ? (
        <div className="bp-node-quiet">{state.detail}</div>
      ) : state && state.models.length === 0 ? (
        <div className="bp-node-quiet">nothing is pulled here yet</div>
      ) : (
        <div className="bp-routes">
          {(state?.models ?? []).map((model) => (
            <div className="bp-route" key={model.name}>
              <span className="bp-route-path">{model.name}</span>
              <span className="bp-route-to">{size(model.size)}</span>
            </div>
          ))}
        </div>
      )}

      {/* A name a person types, never a list this application curated. */}
      <div className="bp-ollama-pull">
        <input
          className="bp-field"
          value={wanted}
          placeholder="llama3.1:8b"
          spellCheck={false}
          disabled={running}
          onChange={(event) => setWanted(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && wanted.trim() && !running) void pull();
          }}
        />
        {running ? (
          <button className="bp-btn is-quiet" onClick={() => void ollamaStop(project)}>
            Stop
          </button>
        ) : (
          <button
            className="bp-btn is-primary"
            disabled={!wanted.trim()}
            onClick={() => void pull()}
          >
            Pull model
          </button>
        )}
      </div>

      {/* The core's own sentences, in order. This panel does no arithmetic on a stream: a
          caller that did would be a caller reimplementing the thing it polls. */}
      {progress ? <pre className="bp-ollama-log">{progress.trimEnd()}</pre> : null}
      {refused ? <div className="bp-node-why">{refused}</div> : null}
    </div>
  );
}
