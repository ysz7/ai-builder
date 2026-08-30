/**
 * Integrations: the foreign programs this project reaches, and adding one without a prompt.
 *
 * **Only MCP, and that is a judgement rather than a first instalment.** The obvious shape
 * here is the reference's wall of logos -- two hundred tiles, one per service. In a builder
 * whose runtime interprets the flow, a tile is a connector it already ships. Here it could
 * only ever mean "generate code that talks to Airtable", and a tile with no working code
 * behind it promises something `kinds.REGISTRY` cannot keep: a node of an unknown kind has
 * no observable check, so it is `unproven` for ever (I-5). The catalog that *can* honour
 * that promise already exists and is the blueprint library -- a tile there carries real
 * annotated code that the gate accepts (P20). This panel is for the one integration that is
 * a declaration rather than a library: a server the project consumes (P15).
 *
 * **Nothing here writes code.** Adding a server composes a request and hands it to the
 * agent, which is `handOver`'s existing contract: the words go into the field and are
 * **never sent**, because handing a request over is not the same as deciding to make it.
 * That is not timidity about a small write -- an `mcp.server` node is a class, a `connect()`
 * in a generated zone and an entry in the group's members, and a form that emitted it would
 * be a fourth family of write with a template engine behind it. The agent writes it, the
 * gate judges it, and nothing about this path is privileged.
 *
 * What it reads is the graph, like every other panel: a server is here because the code
 * declares one, never because somebody filled this form in.
 */

import { useEffect, useState } from "react";

import {
  agentBlueprints,
  blueprintInsert,
  blueprintPlan,
  mcpInspect,
  nodeClaim,
} from "../core/client";
import type {
  BlueprintEntry,
  GraphNode,
  GraphRead,
  InspectResult,
} from "../core/types";
import { Notice } from "./Notice";

type Props = {
  project: string;
  graph: GraphRead | null;
  /** Put a request in the agent's field. Never sent -- the person presses send. */
  onHandOver: (request: string) => void;
  onClose: () => void;
  /** A tile wrote code, so the picture is a claim about files that have changed. */
  onInserted: () => void;
};

/**
 * A knob's value, as the graph reports it.
 *
 * `default` and not `value`: the graph reads and writes the **literal default** in the
 * source, which is the single unambiguous write target -- resolving what the environment
 * would override it with would fork the truth for every write (Q5). So this is what the
 * code says, which is also what the person edits.
 */
function knobOf(node: GraphNode, name: string): string {
  return node.knobs.find((one) => one.name === name)?.default ?? "";
}

/**
 * The request the agent is handed.
 *
 * Written as a specification rather than a wish: the annotation rules live in the system
 * prompt and the agent already has them, so what it needs from here is the particulars it
 * cannot guess -- and the one rule it must not get wrong, which is that the credential is
 * named and never pasted (P15).
 */
function requestFor(fields: {
  title: string;
  command: string;
  args: string;
  credential: string;
  tools: string;
}): string {
  const args = fields.args.trim();
  const tools = fields.tools.trim();
  return [
    `Add an mcp.server node for "${fields.title.trim()}" — a server this project consumes.`,
    "",
    `- command: ${fields.command.trim()}`,
    args ? `- arguments: ${args}` : "- arguments: none",
    fields.credential.trim()
      ? `- the credentials env var is named ${fields.credential.trim()} — put the NAME in a knob, never the value`
      : "- no credentials env var",
    tools ? `- allowed remote tools: ${tools}` : "- allowed remote tools: decide after inspecting the server",
    "",
    "Follow the MCP rules in your system prompt: the node is the declaration, not the",
    "server; calls go through the project's own connect(); and add it as a member of the",
    "group that consumes it.",
  ].join("\n");
}

export function Integrations({ project, graph, onHandOver, onClose, onInserted }: Props) {
  const [tab, setTab] = useState("mcp");
  const [offered, setOffered] = useState<Record<string, InspectResult>>({});
  const [busy, setBusy] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  /** The catalog's parts. Asked once: a catalog is data the application shipped with. */
  const [parts, setParts] = useState<BlueprintEntry[]>([]);
  const [title, setTitle] = useState("");
  const [command, setCommand] = useState("npx");
  const [args, setArgs] = useState("");
  const [credential, setCredential] = useState("");
  const [tools, setTools] = useState("");

  useEffect(() => {
    let alive = true;
    void agentBlueprints()
      .then((answer) => {
        if (alive) setParts(answer.blueprints.filter((entry) => entry.part));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const servers = (graph?.graph.nodes ?? []).filter((node) => node.kind === "mcp.server");
  /** Where a landed node can go. Groups, because the top level holds groups only (I-3). */
  const groups = (graph?.graph.nodes ?? []).filter((node) => node.members.length > 0);
  /**
   * Servers nothing claims, which is exactly what the gate reports as
   * `node.top_level_not_group`.
   *
   * Derived from the graph rather than remembered from an insert: a node is unclaimed
   * because nothing claims it, and how it got there — a tile, the agent, a file somebody
   * wrote — is not part of the fact (I-1).
   */
  const unclaimed = servers.filter(
    (server) => !groups.some((group) => group.members.includes(server.id)),
  );

  /**
   * Insert a tile's code, then wait for somebody to say where it belongs.
   *
   * **Two presses and not one** (Q35, Q36). An insert produces code and nothing else, so
   * the claim is not folded in here either -- the node lands, the gate reports the single
   * error a part is defined by, and the next control asks which group takes it. Nothing
   * about which tile was used is written down: the git diff is the record (Q28.6).
   */
  async function add(entry: BlueprintEntry) {
    setBusy(entry.id);
    setFailed(null);
    try {
      const plan = await blueprintPlan(project, entry.id);
      if (plan.refused) {
        setFailed(plan.refused);
        return;
      }
      const written = await blueprintInsert(project, entry.id, plan.identity);
      if (!written.inserted) {
        setFailed(written.refused || "the insert did not happen");
        return;
      }
      // The graph is re-read, and the node that needs a home falls out of it below. Not
      // tracked here: a server is unclaimed because nothing claims it, which is true of one
      // the agent wrote and one a hand-written file left behind, and a panel that only knew
      // about its own inserts would offer the repair for some of them.
      onInserted();
    } catch (error: unknown) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }
  const ready = title.trim() !== "" && command.trim() !== "";

  async function inspect(id: string) {
    setBusy(id);
    setFailed(null);
    try {
      const answer = await mcpInspect(project, id);
      setOffered((previous) => ({ ...previous, [id]: answer }));
    } catch (error: unknown) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="bp-big-back" onClick={onClose} role="presentation">
      <div
        className="bp-big"
        role="dialog"
        aria-label="Integrations"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="bp-big-top">
          <div className="bp-seg" role="tablist" aria-label="Integrations">
            {/* One tab, and the strip still ships: a second is additive, and inventing one
                to fill the row would be drawing a capability that does not exist. */}
            <button
              className={`bp-seg-tab${tab === "mcp" ? " is-on" : ""}`}
              role="tab"
              aria-selected={tab === "mcp"}
              onClick={() => setTab("mcp")}
            >
              MCP
            </button>
          </div>
          <button className="bp-icon" onClick={onClose} title="Close" aria-label="Close">
            ✕
          </button>
        </header>

        <div className="bp-big-body">
          <div className="bp-cap">Consumed by this project {servers.length}</div>
          {servers.length === 0 ? (
            <p className="bp-knob-note">
              None yet. A server is here because the code declares one — add the first below.
            </p>
          ) : (
            <div className="bp-int-grid">
              {servers.map((node) => {
                const seen = offered[node.id];
                return (
                  <section className="bp-int-card" key={node.id}>
                    <h3 className="bp-int-title">{node.title ?? node.id}</h3>
                    <code className="bp-int-cmd">
                      {[knobOf(node, "command"), knobOf(node, "args")]
                        .filter(Boolean)
                        .join(" ")}
                    </code>
                    {node.summary ? <p className="bp-int-why">{node.summary}</p> : null}
                    <div className="bp-acts">
                      <button
                        className="bp-btn"
                        disabled={busy !== ""}
                        onClick={() => void inspect(node.id)}
                      >
                        {busy === node.id ? "…" : "Inspect"}
                      </button>
                      {/* Never written down (Q12): a remote tool has no carrier, so what
                          the server offers is shown and forgotten when this closes. */}
                      {seen ? (
                        <span className="bp-acts-state">
                          {seen.ok ? `offers ${seen.tools.length}` : seen.detail}
                        </span>
                      ) : null}
                    </div>
                    {seen?.ok ? (
                      <ul className="bp-index-files">
                        {seen.tools.map((tool) => (
                          <li
                            className="bp-index-file"
                            key={tool.name}
                            title={tool.description}
                          >
                            {tool.name}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </section>
                );
              })}
            </div>
          )}

          {/* **The claim, offered where the problem is.** A node the top level cannot hold
              is what an insert of a part leaves behind, and the gate says so by name. This
              is the repair, and it is shown for any unclaimed server whatever wrote it. */}
          {unclaimed.length > 0 && groups.length > 0 ? (
            <>
              <div className="bp-cap">Needs a home {unclaimed.length}</div>
              {unclaimed.map((server) => (
                <div className="bp-int-claim" key={server.id}>
                  <p className="bp-knob-note">
                    <b>{server.title ?? server.id}</b> is on the top level, which holds
                    groups only. Claim it into the group that consumes it.
                  </p>
                  <div className="bp-acts">
                    {groups.map((group) => (
                      <button
                        className="bp-btn bp-btn-go"
                        key={group.id}
                        disabled={busy !== ""}
                        onClick={() => {
                          setBusy(server.id);
                          setFailed(null);
                          void nodeClaim(project, group.id, server.id)
                            .then((answer) => {
                              if (answer.refused) setFailed(answer.refused);
                              else onInserted();
                            })
                            .catch((error: unknown) =>
                              setFailed(
                                error instanceof Error ? error.message : String(error),
                              ),
                            )
                            .finally(() => setBusy(""));
                        }}
                      >
                        {busy === server.id ? "…" : `Into ${group.title ?? group.id}`}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </>
          ) : null}

          {/* The tiles. Every one carries real annotated code the gate then judges -- which
              is why there are two of them and not two hundred: a tile with nothing behind
              it promises what `kinds.REGISTRY` cannot keep. */}
          {parts.length > 0 ? (
            <>
              <div className="bp-cap">Add a known server {parts.length}</div>
              <div className="bp-int-grid">
                {parts.map((entry) => (
                  <button
                    className="bp-int-tile"
                    key={entry.id}
                    disabled={busy !== ""}
                    onClick={() => void add(entry)}
                  >
                    <span className="bp-int-title">{entry.title}</span>
                    <span className="bp-int-why">{entry.summary}</span>
                    <span className="bp-int-add">
                      {busy === entry.id ? "…" : `Add · ${entry.carries_code} file`}
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : null}

          <div className="bp-cap">Add another</div>
          <p className="bp-knob-note">
            Not in the tiles above? This writes nothing itself — it composes a request and
            puts it in the agent’s field, and you press send.
          </p>

          <div className="bp-int-form">
            <label className="bp-block">
              <span className="bp-block-label">Name</span>
              <input
                className="bp-field"
                value={title}
                placeholder="Gmail MCP Server"
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label className="bp-block">
              <span className="bp-block-label">Command</span>
              <input
                className="bp-field"
                value={command}
                placeholder="npx"
                onChange={(event) => setCommand(event.target.value)}
              />
            </label>
            <label className="bp-block">
              <span className="bp-block-label">Arguments</span>
              <input
                className="bp-field"
                value={args}
                placeholder="-y @gongrzhe/server-gmail-autoauth-mcp"
                onChange={(event) => setArgs(event.target.value)}
              />
            </label>
            <label className="bp-block">
              <span className="bp-block-label">Credentials env var</span>
              <input
                className="bp-field"
                value={credential}
                placeholder="GMAIL_MCP_CREDENTIALS"
                onChange={(event) => setCredential(event.target.value)}
              />
              {/* The name, and only ever the name. A field here that took a key would put
                  somebody's credential into a knob and then into git (P15). */}
              <p className="bp-knob-note">
                The variable’s <em>name</em>. Its value goes in the Environment panel.
              </p>
            </label>
            <label className="bp-block">
              <span className="bp-block-label">Allowed remote tools</span>
              <input
                className="bp-field"
                value={tools}
                placeholder="search_emails read_email"
                onChange={(event) => setTools(event.target.value)}
              />
            </label>
          </div>

          <div className="bp-acts">
            <button
              className="bp-btn bp-btn-go"
              disabled={!ready}
              onClick={() => {
                onHandOver(requestFor({ title, command, args, credential, tools }));
                onClose();
              }}
            >
              Hand to the agent
            </button>
            {!ready ? <span className="bp-acts-state">A name and a command, at least.</span> : null}
          </div>

          {failed ? (
            <Notice tone="failed" text={failed} onClose={() => setFailed(null)} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
