/**
 * The `docker` node's panel: what the stack is made of, what of it is up, and the five
 * fields a person changes while building.
 *
 * **A state is not a status and neither is a verdict.** The dot beside a service is what
 * `docker compose ps` reports about a container — running, exited, or nothing at all —
 * while the status on the node itself is a connection this application made, and the colours
 * on the canvas are what a test run proved. Three different claims from three different
 * mechanisms, and they are drawn apart so that none can be read as another.
 *
 * `Up`, `Down` and `Logs` are the same three verbs the `compose.yaml` node has, because they
 * are the same stack: this is where a person is when they are looking at containers, and a
 * panel that made them go somewhere else to start one would be a panel that knows better.
 *
 * **The editor changes five fields and refuses the rest by name.** A full compose editor is
 * a second product; these are what come up while building, and the file is one click away
 * for everything else. Every write is a round-trip that leaves the comments, the key order
 * and the quoting exactly as they were — the same promise `settings.py` makes about Python —
 * and what is drawn afterwards is the file re-read, never what this panel hoped it wrote.
 */

import { useCallback, useEffect, useState } from "react";

import { composeRead, composeWrite, editorOpen } from "../core/client";
import type { ComposeResult, ComposeService } from "../core/types";

/** Which of the five carry a list. `image` is the one that carries a string. */
const LISTS = ["ports", "environment", "volumes", "depends_on"];

/** How a state reads as a colour. Anything unrecognised is drawn as unknown, never as up. */
function toneOf(state: string): string {
  if (state === "running") return "reachable";
  if (state === "") return "unknown";
  return "unreachable";
}

/**
 * One editable field.
 *
 * It holds a draft while somebody types and commits on blur, because a write per keystroke
 * would be a file rewritten forty times for one port number. The draft is thrown away and
 * replaced by whatever the core answered — a panel that kept showing what was typed after a
 * refusal would be showing a file that does not exist.
 */
function Field({
  name,
  value,
  busy,
  onCommit,
}: {
  name: string;
  value: string;
  busy: boolean;
  onCommit: (next: string) => void;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const list = LISTS.includes(name);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };

  return (
    <label className="bp-compose-field">
      <span className="bp-compose-key">{name}</span>
      {list ? (
        <textarea
          className="bp-field bp-compose-lines"
          value={draft}
          rows={Math.max(1, draft.split("\n").length)}
          spellCheck={false}
          disabled={busy}
          placeholder="one per line"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
        />
      ) : (
        <input
          className="bp-field"
          value={draft}
          spellCheck={false}
          disabled={busy}
          placeholder="builds its own"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
      )}
    </label>
  );
}

export function Docker({
  project,
  running,
  onUp,
  onDown,
  onLogs,
}: {
  project: string;
  /** Whether a stack this window brought up is still attached. The workspace owns it. */
  running: boolean;
  onUp: () => void;
  onDown: () => void;
  onLogs: () => void;
}) {
  const [state, setState] = useState<ComposeResult | null>(null);
  const [open, setOpen] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState("");

  const read = useCallback(async () => {
    try {
      setState(await composeRead(project));
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, [project]);

  useEffect(() => {
    void read();
    // Asked again whenever the stack goes up or down, because that is when the states move.
    // Not on a timer: a panel that polled would keep a laptop spawning `docker compose ps`
    // for as long as somebody left a flyout open.
  }, [read, running]);

  const change = useCallback(
    async (service: string, field: string, text: string) => {
      setBusy(true);
      setRefused("");
      try {
        const value = LISTS.includes(field)
          ? text
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean)
          : text.trim();
        const answer = await composeWrite(project, service, field, value);
        // The file re-read, refusal included. This panel never draws its own optimism.
        setState(answer);
        if (!answer.ok) setRefused(answer.detail);
      } catch (error) {
        setRefused(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [project],
  );

  if (!state) return null;

  if (!state.present) {
    // A project with no compose file has a `docker` node only because something else names
    // it. Saying so is the whole answer; a button here would have nothing to bring up.
    return (
      <div className="bp-run">
        <span className="bp-node-label">Containers</span>
        <div className="bp-node-quiet">{state.detail}</div>
      </div>
    );
  }

  const up = state.services.filter((service) => service.state === "running").length;

  return (
    <div className="bp-run">
      <span className="bp-node-label">
        Containers · {up} of {state.services.length} running
      </span>

      {/* Said before anything is pressed. A button whose only possible outcome is an error
          is worse than no button, so where there is no docker there is a sentence instead. */}
      {!state.available ? (
        <div className="bp-node-why">
          there is no docker on this machine to ask — the file below is still editable
        </div>
      ) : (
        <div className="bp-compose-verbs">
          {running ? (
            <button className="bp-btn is-primary" onClick={onDown}>
              Down
            </button>
          ) : (
            <button className="bp-btn is-primary" onClick={onUp}>
              Up
            </button>
          )}
          <button className="bp-btn is-quiet" onClick={onLogs}>
            Logs
          </button>
          <button className="bp-btn is-quiet" onClick={() => void read()}>
            ↻
          </button>
        </div>
      )}

      <div className="bp-routes">
        {state.services.map((service: ComposeService) => (
          <div key={service.name}>
            <button
              className="bp-route"
              onClick={() => setOpen(open === service.name ? "" : service.name)}
            >
              <span className={`bp-status-dot is-${toneOf(service.state)}`} />
              <span className="bp-route-path">{service.name}</span>
              <span className="bp-route-to">
                {/* What the daemon published, never what the file asked for: a `ports:` line
                    is a request and a published port is what happened. Falling back to the
                    file would draw a stopped stack as though it were serving. */}
                {service.state || "not created"}
                {service.published.length > 0 ? ` · ${service.published.join(", ")}` : ""}
              </span>
            </button>

            {open === service.name ? (
              <div className="bp-compose-edit">
                <Field
                  name="image"
                  value={service.image}
                  busy={busy}
                  onCommit={(next) => void change(service.name, "image", next)}
                />
                {LISTS.map((field) => (
                  <Field
                    key={field}
                    name={field}
                    value={(service[field as keyof ComposeService] as string[]).join("\n")}
                    busy={busy}
                    onCommit={(next) => void change(service.name, field, next)}
                  />
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {/* Everything else about the stack is edited in the file, which is one click away.
          The five above are what come up while building; the rest is compose's own surface
          and reimplementing it here would be a second product. */}
      <button className="bp-node-open" onClick={() => void editorOpen(project, state.path, 1)}>
        Open {state.path}
      </button>

      {refused ? <div className="bp-node-why">{refused}</div> : null}
    </div>
  );
}
