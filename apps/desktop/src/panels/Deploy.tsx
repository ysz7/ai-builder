/**
 * `Deploy`: the compose stack, brought up from the file node that describes it.
 *
 * It sits on `compose.yaml` rather than in the top bar, because that is what it is about:
 * the file is a node, and deploying is the one thing that file can be asked to do. There is
 * one target and it is compose — not a first target with more to follow, since a second one
 * would need credentials, a remote and a notion of an environment, and none of those is in
 * this plan.
 *
 * **The file is never read here.** Which services exist comes from `docker compose config`,
 * asked of the program that owns the format. A YAML reader in this codebase would be a
 * second opinion about a thing that already has a first one, wrong in ways that look right.
 *
 * The log is not shown here. It goes to the sheet at the bottom of the window, beside the
 * suite's output, because both are a long stream from a process somebody started and a
 * flyout is the wrong shape for one.
 */

import { useEffect, useState } from "react";

import { deployStatus } from "../core/client";
import type { DeployResult } from "../core/types";

export function Deploy({
  project,
  running,
  onUp,
  onDown,
}: {
  project: string;
  /** Whether a stack this window brought up is still up. Owned by the workspace, which polls. */
  running: boolean;
  onUp: () => void;
  onDown: () => void;
}) {
  const [state, setState] = useState<DeployResult | null>(null);

  useEffect(() => {
    let live = true;
    setState(null);
    // A read. It spawns `docker compose config`, which brings nothing up — asking a file
    // what it says is not starting anything.
    void deployStatus(project)
      .then((answer) => live && setState(answer))
      .catch(() => undefined);
    // Asked again whenever the stack goes up or down, because that is when the answer moves.
  }, [project, running]);

  if (state === null) return null;

  return (
    <div className="bp-run">
      <span className="bp-node-label">Deploy</span>

      {/* Said before the button is pressed. A button whose only possible outcome is an error
          is worse than no button, so where there is no docker there is a sentence instead. */}
      {state.available ? (
        <>
          <div className="bp-run-form">
            {running ? (
              <button className="bp-run-go bp-run-wide" onClick={onDown}>
                Stop the stack
              </button>
            ) : (
              <button className="bp-run-go bp-run-wide" onClick={onUp}>
                docker compose up
              </button>
            )}
          </div>

          {state.services.length > 0 ? (
            <div className="bp-run-docs">
              <span className="bp-run-docs-cap">
                Services ({state.services.length}) · compose {state.version}
              </span>
              {state.services.map((one) => (
                <code key={one}>{one}</code>
              ))}
            </div>
          ) : null}

          {/* Stopping runs `down` as well as ending the client, which is what makes the word
              true: `up` is attached to containers the daemon owns, and killing the client on
              its own would leave a database running after the window closed. */}
          <div className="bp-run-note">
            {running
              ? "Stopping takes the containers down, not only this window's attachment."
              : "Runs in this project's directory. Closing the app takes it down again."}
          </div>
        </>
      ) : (
        <div className="bp-node-why">{state.detail}</div>
      )}
    </div>
  );
}
