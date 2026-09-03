/**
 * Which dependency a container **is**.
 *
 * The `postgres` node and the `postgres` container are the same thing seen from two sides:
 * one is what the project's code talks to, the other is what the compose file asks the
 * daemon to run. Drawing them as two unrelated boxes is how a person ends up wondering why
 * a dependency went red when they stopped a container — so where the two can be matched,
 * a line is drawn between them and the relation is on the canvas rather than in a head.
 *
 * **The match is a literal fact about the entry, never a guess.** Two of them:
 *
 *   - the image's repository names the dependency — `postgres:17-alpine`,
 *     `pgvector/pgvector:pg17`, `redis:7`;
 *   - the container port is the port that dependency listens on.
 *
 * The port table is not a catalogue and must not become one. It holds the published default
 * of the dependencies this build already recognises, and it exists because a compose file
 * frequently pins an image nobody can pattern-match (`bitnami/postgresql`, a private
 * registry) while still mapping 5432. A row here is only ever added beside a dependency the
 * core can already find in the code; nothing is recognised *because* this file names it.
 *
 * Where neither matches, no line is drawn. A container that is somebody's own service is
 * not a dependency of anything, and inventing an edge for it would be the flow-document
 * habit of drawing what looks plausible.
 */

import type { ComposeService } from "../core/types";

/**
 * The port each recognised dependency listens on, inside its container.
 *
 * The **container** port, which is the right-hand side of `"5433:5432"`: the left side is
 * wherever this machine happened to have a free number, and matching on it would make the
 * link depend on somebody's local collision.
 */
const PORTS: Record<string, string> = {
  postgres: "5432",
  redis: "6379",
  ollama: "11434",
};

/** The repository part of an image reference: `pgvector/pgvector:pg17` → `pgvector`. */
function repository(image: string): string {
  const withoutTag = image.split("@")[0].split(":")[0];
  const parts = withoutTag.split("/").filter(Boolean);
  return (parts[parts.length - 1] ?? "").toLowerCase();
}

/** The container side of a `ports:` entry, whichever of compose's short forms it is in. */
function inside(port: string): string {
  const parts = port.split("/")[0].split(":");
  return (parts[parts.length - 1] ?? "").trim();
}

/**
 * Which of `dependencies` this service is, or `""`.
 *
 * `dependencies` is what the graph actually holds, so nothing is ever linked to a node that
 * is not on the canvas: the code has to name a dependency for it to exist at all, and a
 * container for something the project does not talk to is just a container.
 */
export function dependencyOf(service: ComposeService, dependencies: string[]): string {
  const named = repository(service.image);
  // `postgres` recognises `postgres` and `pgvector` alike — pgvector is Postgres with an
  // extension, which is exactly what the database node already calls it.
  const byImage = dependencies.find(
    (id) => named === id || (id === "postgres" && named === "pgvector"),
  );
  if (byImage) return byImage;

  const ports = service.ports.map(inside);
  return dependencies.find((id) => PORTS[id] && ports.includes(PORTS[id])) ?? "";
}
