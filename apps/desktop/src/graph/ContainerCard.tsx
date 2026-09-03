/**
 * Something the project **declares** and can never prove, drawn as a node.
 *
 * Three of them share this card because they are the same sort of thing: a container in
 * `compose.yaml`, an MCP server in `mcp.json`, and the database the project's own code talks
 * to. None has an export, none is a package, and none is ever executed by a test — so none
 * can carry a verdict.
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
 * So the card says a name and one quiet line under it, and nothing else. Everything a person
 * can do with a container lives on the `compose.yaml` node, because that is the thing they
 * are written in; everything about the database lives in its panel, because twelve tables are
 * twelve rows and never twelve boxes.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { glyphOf, labelOf, tintBgOf, tintOf } from "./kinds";

export type ContainerData = {
  name: string;
  /** `container`, `mcp` or `dependency`. Things the project states and can never prove. */
  kind: string;
  /**
   * The one line under the name.
   *
   * For a container and a server it is the file that declares them, which is what a person
   * opens to change one. For the database there is no such file — it is stated in several
   * places at once — so it is the reading instead: how many tables, or what it points at.
   */
  where: string;
  /**
   * Whether an edge actually lands here.
   *
   * A pin nothing uses is decoration — and a pin an edge *does* use and that is not drawn is
   * worse: React Flow cannot place the line at all, and the relation silently disappears off
   * the canvas. A container has no edges; a server has the one from the agent that reaches it.
   */
  pinned: boolean;
  /** Whether an import edge lands on the left. A database has these; the other two do not. */
  inbound: boolean;
  /**
   * Whether the line to the dependency this container **is** leaves here.
   *
   * Only a container has one, and only where the match was a literal fact about its compose
   * entry. It is not an import and is not drawn as one — nothing in the project's Python
   * points at a container; the line says the two boxes are one thing.
   */
  outbound?: boolean;
  /**
   * What a connection last answered, `"checking"` while one is in flight, or `""`.
   *
   * **Never a verdict, and drawn in its own palette so it cannot be read as one.** A
   * reachable Postgres is not a proven one. `""` means nothing has been asked — an absent
   * status reads as absent, never as a hopeful default.
   */
  status: string;
  /** Why, in the check's own words. On hover: a card is not a log. */
  statusDetail: string;
  /**
   * The word to draw instead of the state's own name, where the two differ.
   *
   * A dependency is `reachable`; a server that answered `tools/list` is `connected`. They
   * share a palette because both are claims about something outside the project, and they do
   * **not** share a word: reached is not the same sentence as answered.
   */
  statusLabel?: string;
  /** Ask again, now. Every dependency carries one; the plan asks for it by name. */
  onRefresh?: () => void;
};

export function ContainerCard({ data, selected }: NodeProps) {
  const {
    name,
    kind,
    where,
    pinned,
    inbound,
    outbound,
    status,
    statusDetail,
    statusLabel,
    onRefresh,
  } = data as unknown as ContainerData;

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

      <div className={`bp-card bp-card-container${status ? ` is-${status}` : ""}`}>
        {pinned ? (
          <Handle type="target" position={Position.Top} className="pin pin-data" id="up" />
        ) : null}
        {/* A dependency is imported *into* the project's code, so its lines arrive from the
            side the way every other import edge does. A server is reached over a protocol
            and keeps its own pin above. */}
        {inbound ? (
          <Handle type="target" position={Position.Left} className="pin pin-data" id="in" />
        ) : null}
        {outbound ? (
          <Handle type="source" position={Position.Right} className="pin pin-data" id="same" />
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
        {where ? <div className="bp-card-desc">{where}</div> : null}

        {/* Drawn only once something has been asked. A row that always existed would invite
            a default to be put in it, and a dependency nobody checked has no status. */}
        {status ? (
          <div className={`bp-status is-${status}`} title={statusDetail}>
            <span className="bp-status-dot" />
            {status === "checking" ? "checking…" : statusLabel || status}
            {onRefresh ? (
              <button
                className="bp-status-refresh nodrag"
                title="Check again"
                onClick={(event) => {
                  event.stopPropagation();
                  onRefresh();
                }}
              >
                ↻
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
