/**
 * The rail's environment panel: two views of the same subject.
 *
 * `.env` is the file, verbatim, and stays the truth -- a text box, because the core does not
 * parse it (§5.8). `Providers` is the guided way in: it fills in the endpoint and variable
 * name for a well-known provider, appends the value to that same file, and writes the three
 * knobs onto whichever node is being pointed somewhere. Neither tab holds any state of its
 * own, which is why they can sit beside each other without disagreeing.
 */

import { useState } from "react";

import type { GraphRead } from "../core/types";
import { Env } from "./Env";
import { Providers } from "./Providers";

export function EnvPanel({
  project,
  graph,
  onWrote,
}: {
  project: string;
  graph: GraphRead | null;
  onWrote: () => void;
}) {
  const [tab, setTab] = useState<"providers" | "env">("providers");

  return (
    <div className="bp-envtabs">
      <div className="bp-envtabs-bar">
        <button
          className={`bp-envtab${tab === "providers" ? " is-on" : ""}`}
          onClick={() => setTab("providers")}
        >
          Providers
        </button>
        <button
          className={`bp-envtab${tab === "env" ? " is-on" : ""}`}
          onClick={() => setTab("env")}
        >
          .env
        </button>
      </div>
      {tab === "providers" ? (
        <Providers project={project} graph={graph} onWrote={onWrote} />
      ) : (
        <Env project={project} />
      )}
    </div>
  );
}
