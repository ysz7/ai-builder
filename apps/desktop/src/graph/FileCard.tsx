/**
 * One of the four root files, drawn as a node.
 *
 * `.env`, `compose.yaml`, `Dockerfile`, `mcp.json`. They are shown, opened and edited — and
 * **never coloured**, which is why this is a different component rather than a card with
 * its verdict hidden. Nothing runs them, so nothing can prove them, and a component that
 * merely omitted the mark would grow one the first time somebody wanted a badge on it.
 *
 * Smaller than a system card on purpose: it carries a name and nothing else, and giving it
 * the same width would make four files look like four systems.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { GraphNode } from "../core/types";
import { glyphOf, tintBgOf, tintOf } from "./kinds";

export type FileData = {
  node: GraphNode;
  /** Whether an MCP edge lands here. `mcp.json` is the only one that ever has a pin. */
  pinned: boolean;
  onOpen: (id: string) => void;
};

export function FileCard({ data, selected }: NodeProps) {
  const { node, pinned, onOpen } = data as unknown as FileData;

  return (
    <div
      className={`bp-card-wrap${selected ? " is-selected" : ""}`}
      style={{
        ["--tint" as string]: tintOf("file"),
        ["--tint-bg" as string]: tintBgOf("file"),
      }}
      onClick={() => onOpen(node.id)}
    >
      <div className="bp-card bp-card-file">
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
              d={glyphOf("file")}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="bp-card-title">{node.name}</span>
        </div>
      </div>
    </div>
  );
}
