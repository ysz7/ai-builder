/**
 * Something the project **declares** and can never prove, drawn as a node.
 *
 * Two of them share this card because they are the same sort of thing: a container in
 * `compose.yaml`, and an MCP server in `mcp.json`. Neither has an export, neither is a
 * package, and neither is ever executed by a test — so neither can carry a verdict.
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

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { glyphOf, labelOf, tintBgOf, tintOf } from "./kinds";

export type ContainerData = {
  name: string;
  /** `container` or `mcp`. Two things the project declares and can never prove. */
  kind: string;
  /** The file that declares it. What a person opens to change it. */
  where: string;
  /**
   * Whether an edge actually lands here.
   *
   * A pin nothing uses is decoration — and a pin an edge *does* use and that is not drawn is
   * worse: React Flow cannot place the line at all, and the relation silently disappears off
   * the canvas. A container has no edges; a server has the one from the agent that reaches it.
   */
  pinned: boolean;
};

export function ContainerCard({ data, selected }: NodeProps) {
  const { name, kind, where, pinned } = data as unknown as ContainerData;

  return (
    <div
      className={`bp-card-wrap${selected ? " is-selected" : ""}`}
      style={{
        ["--tint" as string]: tintOf(kind),
        ["--tint-bg" as string]: tintBgOf(kind),
      }}
    >
      <div className="bp-card-tab">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d={glyphOf(kind)}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {labelOf(kind)}
      </div>

      <div className="bp-card bp-card-container">
        {pinned ? (
          <Handle type="target" position={Position.Top} className="pin pin-data" id="up" />
        ) : null}
        <div className="bp-card-head">
          <svg
            className="bp-card-glyph"
            viewBox="0 0 24 24"
            width="15"
            height="15"
            aria-hidden="true"
          >
            <path
              d={glyphOf(kind)}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="bp-card-title">{name}</span>
        </div>
        <div className="bp-card-desc">{where}</div>
      </div>
    </div>
  );
}
