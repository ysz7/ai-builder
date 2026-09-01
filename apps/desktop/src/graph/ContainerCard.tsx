/**
 * A service the project's compose file declares, drawn as a node.
 *
 * **Never coloured, and this is a different component so that it cannot become so.** Nothing
 * in a test run executes a Postgres, so nothing can prove one; a card that merely omitted the
 * mark would grow one the first time somebody wanted a badge on it — which is how a node
 * comes to be green because it exists.
 *
 * It is also **not read out of `compose.yaml`.** The name came from
 * `docker compose config --services`, asked of the program that owns the format. There is no
 * YAML reader in this codebase and this node is the most tempting reason there has ever been
 * to add one: a parser for somebody else's format is a second opinion about a thing that
 * already has a first one, and it is wrong in ways that look right.
 *
 * So the card says a name and what declared it, and nothing else. Everything a person can do
 * with these lives on the `compose.yaml` node, because that is the thing they are written in.
 */

import { type NodeProps } from "@xyflow/react";

import { glyphOf, labelOf, tintBgOf, tintOf } from "./kinds";

export type ContainerData = { name: string };

export function ContainerCard({ data, selected }: NodeProps) {
  const { name } = data as unknown as ContainerData;

  return (
    <div
      className={`bp-card-wrap${selected ? " is-selected" : ""}`}
      style={{
        ["--tint" as string]: tintOf("container"),
        ["--tint-bg" as string]: tintBgOf("container"),
      }}
    >
      <div className="bp-card-tab">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d={glyphOf("container")}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {labelOf("container")}
      </div>

      <div className="bp-card bp-card-container">
        <div className="bp-card-head">
          <svg
            className="bp-card-glyph"
            viewBox="0 0 24 24"
            width="15"
            height="15"
            aria-hidden="true"
          >
            <path
              d={glyphOf("container")}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="bp-card-title">{name}</span>
        </div>
        <div className="bp-card-desc">compose.yaml</div>
      </div>
    </div>
  );
}
