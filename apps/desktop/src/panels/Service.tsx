/**
 * `Start` and `Stop` on a dependency, where a container is what provides it.
 *
 * **The button is drawn because the core can answer for it, and never before.** A dependency
 * is something outside the project, and most of what is outside a project cannot be started
 * from here at all: nobody starts Anthropic, and a Postgres running on somebody's server is
 * not this window's to touch. What *can* be started is the one case where the project itself
 * declares the thing it talks to — a service in `compose.yaml` — so that is the case that
 * gets buttons, and every other dependency gets nothing rather than a control whose only
 * possible outcome is an error.
 *
 * **It says `Start`, not `Run`.** `Run` in this product means calling one system's export,
 * and it colours nothing; this brings a container up. Two mechanisms under one word is how a
 * person stops trusting either of them.
 *
 * The link from a dependency to the service that provides it is `dependencyOf`, which is the
 * same reading that already draws the line between those two boxes on the canvas. One rule,
 * used twice: a card offering to start something the canvas does not join to it would be
 * this panel having an opinion of its own about the stack.
 *
 * **A state is not a status.** What is drawn here is `docker compose ps` on a container; the
 * status row above it is a connection this application made. A running container that
 * refuses connections is an ordinary thing and the panel says both, rather than choosing.
 */

import { useCallback, useEffect, useState } from "react";

import { dependencyOf } from "../graph/services";
import { composeRead, serviceStart, serviceStop } from "../core/client";
import type { ComposeService } from "../core/types";

/** How a container's state reads as a colour. Anything unrecognised is never drawn as up. */
function toneOf(state: string): string {
  if (state === "running") return "reachable";
  if (state === "") return "unknown";
  return "unreachable";
}

export function Service({
  project,
  node,
  onChanged,
}: {
  project: string;
  /** The dependency this panel is on: `postgres`, `redis`, `ollama`. */
  node: string;
  /**
   * Something started or stopped, so whatever else is on screen about this node is stale.
   *
   * The status above is a connection made at a moment, and that moment is now behind a
   * container going up or down. Asked for again rather than adjusted here: this panel knows
   * what it pressed, not what the thing now answers.
   */
  onChanged: () => void;
}) {
  const [service, setService] = useState<ComposeService | null>(null);
  const [available, setAvailable] = useState(true);
  const [busy, setBusy] = useState("");
  const [refused, setRefused] = useState("");

  const read = useCallback(async () => {
    try {
      const answer = await composeRead(project);
      setAvailable(answer.available);
      // The mapping the canvas already uses, asked the other way round: of the services this
      // stack declares, which one *is* this dependency.
      const mine = answer.services.find((one) => dependencyOf(one, [node]) === node);
      setService(mine ?? null);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, [project, node]);

  useEffect(() => {
    void read();
  }, [read]);

  const act = useCallback(
    async (verb: "start" | "stop", name: string) => {
      setBusy(verb);
      setRefused("");
      try {
        const answer = await (verb === "start"
          ? serviceStart(project, name)
          : serviceStop(project, name));
        if (!answer.ok) setRefused(answer.detail);
        // The daemon re-asked, never this panel's own optimism: `up -d` returning is compose
        // saying it asked, and what the container is doing is a separate question.
        await read();
        onChanged();
      } catch (error) {
        setRefused(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy("");
      }
    },
    [project, read, onChanged],
  );

  // No container declares this dependency, so there is nothing here to start. Silent rather
  // than explanatory: a person looking at `anthropic` is not waiting to be told that an API
  // they pay for cannot be launched from a panel.
  if (!service) return null;

  const running = service.state === "running";

  return (
    <div className="bp-run">
      <span className="bp-node-label">Container · {service.name}</span>

      <div className="bp-status">
        <span className={`bp-status-dot is-${toneOf(service.state)}`} />
        {service.state || "not created"}
        {service.published.length > 0 ? ` · ${service.published.join(", ")}` : ""}
      </div>

      {/* Said before anything is pressed, for the same reason the stack's panel says it. */}
      {!available ? (
        <div className="bp-node-why">
          there is no docker on this machine to start it with
        </div>
      ) : (
        <div className="bp-compose-verbs">
          {running ? (
            <button
              className="bp-btn is-primary"
              disabled={busy !== ""}
              onClick={() => void act("stop", service.name)}
            >
              {busy === "stop" ? "Stopping…" : "Stop"}
            </button>
          ) : (
            <button
              className="bp-btn is-primary"
              disabled={busy !== ""}
              onClick={() => void act("start", service.name)}
            >
              {busy === "start" ? "Starting…" : "Start"}
            </button>
          )}
          <button className="bp-btn is-quiet" disabled={busy !== ""} onClick={() => void read()}>
            ↻
          </button>
        </div>
      )}

      {/* The first `Start` of an image pulls it, which is minutes rather than seconds. Said
          here so a button that looks stuck reads as a download instead. */}
      {busy === "start" ? (
        <div className="bp-node-why">the first start pulls the image, which can take a while</div>
      ) : null}

      {refused ? <div className="bp-node-why">{refused}</div> : null}
    </div>
  );
}
