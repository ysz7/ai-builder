/**
 * The `Use` tab: the project as something to use, rather than as something to read.
 *
 * `Graph` answers *how is this built* -- shape, connections, verdicts -- and that is the
 * question its author has. Somebody who did not write it has a different one, and the graph
 * is in the way of it: to talk to an agent you first have to find the agent. This tab is the
 * other question, and it holds no diagram at all -- a column of cards, each one a thing the
 * project can be asked to do.
 *
 * **It is the same nodes and the same verbs**, and that is the whole design. A node appears
 * here because `kinds.REGISTRY` gave its kind a way in -- `converses`, `indexes`, `starts` --
 * which is the same derivation the buttons on the canvas already use, so a kind that has not
 * opted in is absent rather than present and broken. Every button is the `Actions` component
 * the inspector draws, unchanged: two renderings of one list, never two lists.
 *
 * What it deliberately is not:
 *
 *   - **not a second graph.** No nodes, no pins, nothing to connect. A gesture here that
 *     wrote a relation would be the flow-document architecture arriving through a side door;
 *   - **not a place data lives.** The reference's screen has a `Documents` tile that *holds*
 *     uploaded files. Ours cannot: a node is a projection of code (I-1), and files parked in
 *     a card would be state living outside it. Handing a pipeline documents stays the verb
 *     it is, and what comes back is what the store said afterwards (P17.5);
 *   - **not a second path to green.** Nothing here proves anything the canvas would not have
 *     proven. A conversation is still evidence by `probe.run_plan` and at the rank it always
 *     had; the mark shown on a card is the one the node already wears (I-5).
 *
 * And nothing starts because this tab was opened (P11) -- the same rule the chat card
 * follows: the surface is here, the process is not, until somebody presses something.
 *
 * **One thing at a time, chosen from a bar across the top.** A column of every usable node
 * was fine at three and stops being fine at fifteen -- and this tab is where a project ends
 * up having fifteen, because everything the code can be asked to do arrives here. Scrolling
 * past four panels to reach the one being used is the shape a person leaves. So the bar
 * carries the choice and the panel carries one node, which also lets that panel be as tall
 * as a conversation needs rather than as short as a list can tolerate.
 */

import { useEffect, useState } from "react";

import { glyphOf } from "../graph/kinds";
import { kindRegistry } from "../core/registry";
import type { Environment, GraphNode, GraphRead, NodeKindInfo } from "../core/types";
import { Actions } from "./Actions";
import { Talk } from "./Talk";

type Props = {
  project: string;
  graph: GraphRead;
  runningKinds: Set<string>;
  services: Environment | null;
  onActed: () => void;
};

/**
 * Is this a node somebody *uses*?
 *
 * Three registry fields and one kind name. The fields are the honest part: a kind is usable
 * because it named a way in, so adding a kind adds a card without touching this. The name is
 * `mcp.server`, and it is here for the same reason `Actions` names it -- reaching a foreign
 * server is a verb the registry has no field for, because the node is a *declaration* of how
 * to reach a program rather than a thing that starts (P15). If that ever gets a field, this
 * loses its one exception.
 */
function usable(node: GraphNode, kind: NodeKindInfo | undefined): boolean {
  return Boolean(kind?.converses || kind?.indexes || kind?.starts) || node.kind === "mcp.server";
}

export function Use({ project, graph, runningKinds, services, onActed }: Props) {
  const [kinds, setKinds] = useState<NodeKindInfo[]>([]);
  /**
   * Which node the panel is showing.
   *
   * Local, and deliberately not stored beside the layout the way the tab itself is (Q13).
   * A selection *inside* a view is a different kind of fact from which view you are in: it
   * has an obviously right default -- the first thing there is -- and a stored one pointing
   * at a node the agent has since renamed would need reconciling against a graph, which is
   * exactly the sort of opinion the layout file refuses to hold.
   */
  const [chosen, setChosen] = useState("");

  useEffect(() => {
    let alive = true;
    void kindRegistry().then((answer) => {
      if (alive) setKinds(answer.kinds);
    });
    return () => {
      alive = false;
    };
  }, []);

  const byName = new Map(kinds.map((kind) => [kind.name, kind]));
  // Graph order, not an order of ours: the code decides what comes first, and a tab that
  // sorted by "importance" would be this application having an opinion about somebody
  // else's project. Members included -- a pipeline's stage may be the thing with the verb.
  const cards = graph.graph.nodes.filter((node) => usable(node, byName.get(node.kind)));

  if (kinds.length === 0) {
    return <div className="bp-empty bp-empty-full">Reading…</div>;
  }

  if (cards.length === 0) {
    return (
      <div className="bp-empty bp-empty-full">
        Nothing here to use yet. A node appears on this tab once its kind has a way in — an
        agent to talk to, a pipeline to index, a service to start.
      </div>
    );
  }

  // Falls back rather than clearing: the agent rewriting a file makes a node vanish and
  // come back, and a screen that emptied itself in between would look broken every time.
  const node = cards.find((one) => one.id === chosen) ?? cards[0];
  const kind = byName.get(node.kind);

  return (
    <div className="bp-use">
      <nav className="bp-usebar" role="tablist" aria-label="What this project can do">
        {cards.map((one) => (
          <button
            key={one.id}
            role="tab"
            aria-selected={one.id === node.id}
            className={`bp-usebar-item${one.id === node.id ? " is-on" : ""}`}
            onClick={() => setChosen(one.id)}
          >
            <svg
              className="bp-usebar-glyph"
              viewBox="0 0 24 24"
              width="17"
              height="17"
              aria-hidden="true"
            >
              <path
                d={glyphOf(one.kind)}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <span className="bp-usebar-text">
              <span className="bp-usebar-title">{one.title ?? one.id}</span>
              {/* The author's own sentence, or the id. Never a label we made up for them:
                  a subtitle invented here would be this application describing somebody
                  else's node, and it would be wrong in a way that reads as authoritative. */}
              <span className="bp-usebar-why">{one.summary || one.id}</span>
            </span>
          </button>
        ))}
      </nav>

      <div className="bp-use-col">
        <section className="bp-use-card">
          <header className="bp-use-head">
            <h2 className="bp-use-title">{node.title ?? node.id}</h2>
            <code className="bp-use-id">{node.id}</code>
          </header>

          {node.summary ? <p className="bp-use-why">{node.summary}</p> : null}

          <Actions
            project={project}
            node={node}
            running={runningKinds.has(node.kind)}
            services={services}
            onActed={onActed}
          />

          {/* Talking is the one verb `Actions` does not draw -- it moved to the canvas
              card (Q34) -- so it is drawn here, from the same `converses` field. */}
          {kind?.converses ? (
            <Talk project={project} node={node.id} onAnswered={onActed} />
          ) : null}
        </section>
      </div>
    </div>
  );
}
