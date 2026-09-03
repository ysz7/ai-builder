/**
 * The blocks a project can be started from.
 *
 * **A palette that writes code is an accelerator; a palette that puts a node on the canvas
 * is a different product.** That line is the whole design of this file. Nothing here creates,
 * names or positions a node: pressing `+` sends one command to the chat, the agent writes
 * ordinary Python, and the node appears because `graph.read` found a package that satisfies
 * the convention. Every other builder in this category gets this backwards — the flow
 * document is the truth and the code is an export — and that is exactly why a node is green
 * in them because it exists.
 *
 * So this component has **no write path of its own and cannot acquire one**. Its only output
 * is a string handed to the chat.
 *
 * ## It is a renderer, and the list is not in here
 *
 * The blocks come from `chat.choices`, which derives them from the commands this build
 * ships. A palette holding its own list could offer something the prompts have never heard
 * of, and the first symptom would be a button that starts a turn the agent does not
 * understand. Adding a command with a prompt is what adds a block; this file does not
 * change when one arrives.
 *
 * For the same reason there is **no catalogue** — no list of databases, no directory of MCP
 * servers. A block that takes a name takes it as free text, because a catalogue of things
 * somebody could add is a template gallery with the serial numbers filed off.
 *
 * ## Why some are disabled
 *
 * The convention allows one system of each kind per level, and a tool has to go inside an
 * agent. The palette **shows those rules rather than inventing new ones**: the block is
 * drawn, disabled, with the reason, and deleting the package re-enables it. A hidden block
 * would be a rule nobody could see; a block that pretended to work would be a turn spent
 * discovering it.
 */

import { useEffect, useState } from "react";

import { chatChoices } from "../core/client";
import type { Block as BlockSpec, ChatChoices, Graph } from "../core/types";
import { glyphOf, labelOf, tintBgOf, tintOf } from "../graph/kinds";
import { Flyout } from "../shell/Flyout";

/** The select's entry for "whatever this project already prefers". Sends no `--stack`. */
const DEFAULT = "";

function Block({
  spec,
  taken,
  onAdd,
}: {
  spec: BlockSpec;
  /** Why it cannot be added, or `""` when it can. */
  taken: string;
  onAdd: (command: string, kind: string) => void;
}) {
  const [stack, setStack] = useState(DEFAULT);
  const [name, setName] = useState("");

  // A block with a kind is named by the kind, so there is one table of those words and it is
  // the one the canvas draws from. Everything else carries its own label from the core.
  // The block's own label wins where it has one: five dependency blocks share a kind and
  // are not five Databases, and a word that disagrees with the thing under it is worse than
  // no word. The kind's name is the fallback, and it is the canvas's own table.
  const label = spec.label || (spec.kind ? labelOf(spec.kind) : "");
  const ready = taken === "" && (spec.takes !== "name" || name.trim() !== "");

  const press = () => {
    const parts = [`/${spec.command}`];
    if (spec.argument) parts.push(spec.argument);
    if (spec.takes === "name" && name.trim()) parts.push(name.trim());
    if (spec.takes === "stack" && stack) parts.push(`--stack ${stack}`);
    // The kind travels with the command so the canvas can stand something in its place while
    // it is written. `""` for a block that becomes no node, and then nothing is drawn.
    onAdd(parts.join(" "), spec.kind);
    setName("");
  };

  return (
    <div className={`bp-block-card${taken ? " is-taken" : ""}`}>
      <div
        className="bp-block-mark"
        style={{
          ["--tint" as string]: tintOf(spec.kind || "file"),
          ["--tint-bg" as string]: tintBgOf(spec.kind || "file"),
        }}
      >
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path
            d={glyphOf(spec.kind || "file")}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>

      <div className="bp-block-body">
        <span className="bp-block-name">{label}</span>
        {/* The reason, in the convention's own words. It is the way out of the state the
            project is in — delete the package and this block comes back. */}
        <span className="bp-block-hint">{taken || spec.hint}</span>

        {taken ? null : spec.takes === "stack" ? (
          /* No stack is a real answer and it is the default: the project records a
             preference in `.env`, and sending no `--stack` is what lets that preference
             win. Choosing one here overrides it for this system only. */
          <select
            className="bp-field bp-block-stack"
            value={stack}
            onChange={(event) => setStack(event.target.value)}
          >
            <option value={DEFAULT}>this project's default</option>
            {spec.choices.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
        ) : spec.takes === "name" ? (
          /* Free text, never a list. A menu of databases or of MCP servers would be a
             catalogue this application maintained, which is a template gallery by another
             name — and it would be wrong about the world within a month. */
          <input
            className="bp-field bp-block-stack"
            placeholder={spec.command === "add-mcp" ? "gmail" : "postgres"}
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && ready) press();
            }}
          />
        ) : null}
      </div>

      <button
        className="bp-block-add"
        disabled={!ready}
        title={taken || `Ask the chat for ${label.toLowerCase()}`}
        onClick={press}
      >
        +
      </button>
    </div>
  );
}

export function Palette({
  graph,
  busy,
  onAdd,
  onClose,
}: {
  graph: Graph | null;
  /** A turn is already being answered. Every block says so rather than starting a second. */
  busy: boolean;
  /** One command, handed to the chat. The only thing this component emits. */
  onAdd: (command: string, kind: string) => void;
  onClose: () => void;
}) {
  const [choices, setChoices] = useState<ChatChoices | null>(null);
  const [refused, setRefused] = useState("");

  useEffect(() => {
    let live = true;
    void chatChoices()
      .then((answer) => live && setChoices(answer))
      .catch((error: unknown) =>
        live && setRefused(error instanceof Error ? error.message : String(error)),
      );
    return () => {
      live = false;
    };
  }, []);

  /** What is already at the root. Nesting is a separate gesture and not this panel's. */
  const rooted = new Set(
    (graph?.nodes ?? []).filter((node) => node.parent === "").map((node) => node.kind),
  );

  /**
   * Every node there is, by id.
   *
   * `once` is asked of this rather than of the kinds at the root, because the three things
   * it covers sit in three different places: a system at the root, a chat inside the api, a
   * dependency beside the graph. The block says which id it becomes, so this panel enforces
   * the rule while knowing none of it.
   */
  const present = new Set((graph?.nodes ?? []).map((node) => node.id));

  /** Why this block cannot be pressed, in the convention's words, or `""`. */
  const why = (spec: BlockSpec): string => {
    // The core's own sentence for the same situation, so the two agree.
    if (busy) return "a turn is already running — wait for it rather than starting a second";
    if (spec.once && spec.becomes && present.has(spec.becomes)) {
      // One sentence per shape of the rule, because they are different rules: a kind is
      // one per level, and the other two are one per project.
      return spec.kind && rooted.has(spec.kind)
        ? `there is already a ${spec.becomes}/ here — one of each kind per level`
        : `there is already a ${spec.becomes} in this project`;
    }
    if (spec.requires && !rooted.has(spec.requires)) {
      return `it goes inside ${spec.requires}/, and there is not one here yet`;
    }
    return "";
  };

  return (
    <Flyout title="Blocks" onClose={onClose}>
      <div className="bp-palette">
        <div className="bp-palette-lead">
          Each of these asks the chat for ordinary Python. Nothing here draws a node — one
          appears when a package satisfying the convention has been written.
        </div>

        {refused ? <div className="bp-node-why">{refused}</div> : null}

        {choices?.blocks.map((spec) => (
          <Block
            key={`${spec.command}:${spec.argument || spec.label}`}
            spec={spec}
            taken={why(spec)}
            onAdd={onAdd}
          />
        ))}
      </div>
    </Flyout>
  );
}
