/**
 * The chat node: a route the project serves, and the page behind it.
 *
 * **It is not a panel this application draws.** `api/routes/chat.py` is ordinary Python in
 * the project — it is why there is a node at all — and `Open` sends the person's own browser
 * to the address their own service answers on. A chat rendered inside this window would be a
 * panel with code behind it, which is one honest step from a panel with nothing behind it,
 * and it would stop existing the moment the builder was closed.
 *
 * Everything shown here is **derived**: the verbs and paths come from the same reader that
 * fills the service's own route list, filtered to this file, and the address comes from the
 * port the daemon actually published for the api service. Where nothing is up there is no
 * address, and the panel says that rather than offering a link to nowhere.
 */

import { useEffect, useState } from "react";

import { composeRead, editorBrowse, editorOpen, routesRead } from "../core/client";
import type { GraphNode, RoutesResult } from "../core/types";

/** The parent service, from the node id: `api.routes.chat` belongs to `api`. */
function serviceOf(node: GraphNode): string {
  return node.parent || node.id.split(".")[0];
}

export function ChatRoute({ project, node }: { project: string; node: GraphNode }) {
  const [routes, setRoutes] = useState<RoutesResult | null>(null);
  /** Where the service answers, from the port the daemon published. `""` while nothing is up. */
  const [where, setWhere] = useState("");

  useEffect(() => {
    let live = true;
    setRoutes(null);
    setWhere("");

    void routesRead(project, serviceOf(node))
      .then((answer) => live && setRoutes(answer))
      .catch(() => undefined);

    // The published port, not the one the file asks for: a `ports:` line is a request and a
    // published port is what happened. No port means nothing is running, and no link.
    void composeRead(project)
      .then((stack) => {
        if (!live) return;
        const service = stack.services.find(
          (one) => one.name === serviceOf(node) && one.state === "running",
        );
        const port = service?.published[0];
        if (port) setWhere(`http://localhost:${port}`);
      })
      .catch(() => undefined);

    return () => {
      live = false;
    };
  }, [project, node]);

  const mine = (routes?.routes ?? []).filter((route) => route.file === node.path);

  return (
    <div className="bp-run">
      <span className="bp-node-label">Serves</span>

      {mine.length > 0 ? (
        <div className="bp-routes">
          {mine.map((route) => (
            <button
              key={`${route.method} ${route.path}`}
              className="bp-route"
              onClick={() => void editorOpen(project, route.file, 1)}
            >
              <span className="bp-route-verb">{route.method}</span>
              <span className="bp-route-path">{route.path}</span>
              <span className="bp-route-to">
                {route.unsure ? "→ ?" : route.targets.length > 0 ? `→ ${route.targets.join(", ")}` : ""}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="bp-node-quiet">
          no route is declared in this file yet — it is a node because the file is there
        </div>
      )}

      {where ? (
        <>
          <button
            className="bp-run-go bp-run-wide"
            onClick={() => void editorBrowse(`${where}/chat`)}
          >
            Open the chat
          </button>
          <div className="bp-run-note">
            {where}/chat — your own browser, on the address your service published. The same
            page deploys with the project; nothing here is needed to serve it.
          </div>
        </>
      ) : (
        <div className="bp-run-note">
          Bring the stack up to open it: the page is served by this project's own api, not by
          this window.
        </div>
      )}
    </div>
  );
}
