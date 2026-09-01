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
 * ## Where the blocks come from
 *
 * `chat.choices`, and nowhere else. The kinds are the keys of `stacks`; the stacks are its
 * values; a block for a command the core does not return cannot be drawn. There is no list
 * of blocks in this file, which is what stops the palette and the core drifting apart — the
 * failure that would show up as a button writing a system the prompts have never heard of.
 *
 * ## Why some are disabled
 *
 * The convention allows one system of each kind per level, so a project that has an `agent/`
 * cannot be given a second. The palette **shows that rule rather than enforcing a new one**:
 * the block is drawn, disabled, with the reason, and deleting the package re-enables it. A
 * hidden block would be a rule nobody could see; a block that pretended to work would be a
 * turn spent discovering it.
 */

import { useEffect, useState } from "react";

import { chatChoices } from "../core/client";
import type { ChatChoices, Graph } from "../core/types";
import { glyphOf, labelOf, tintBgOf, tintOf } from "../graph/kinds";
import { Flyout } from "../shell/Flyout";

/** What the select says for "whatever this project already prefers". */
const DEFAULT = "";

function Block({
  kind,
  label,
  hint,
  stacks,
  taken,
  onAdd,
}: {
  kind: string;
  label: string;
  hint: string;
  /** The stacks this kind may be written on. Empty where the command takes none. */
  stacks: string[];
  /** Why it cannot be added, or `""` when it can. */
  taken: string;
  onAdd: (stack: string) => void;
}) {
  const [stack, setStack] = useState(DEFAULT);

  return (
    <div className={`bp-block-card${taken ? " is-taken" : ""}`}>
      <div
        className="bp-block-mark"
        style={{
          ["--tint" as string]: tintOf(kind),
          ["--tint-bg" as string]: tintBgOf(kind),
        }}
      >
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path
            d={glyphOf(kind)}
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
        <span className="bp-block-hint">{taken || hint}</span>

        {/* No stack is a real answer and it is the default: the project records a preference
            in `.env`, and sending no `--stack` is what lets that preference win. Choosing one
            here overrides it for this system only. */}
        {stacks.length > 0 && !taken ? (
          <select
            className="bp-field bp-block-stack"
            value={stack}
            onChange={(event) => setStack(event.target.value)}
          >
            <option value={DEFAULT}>this project's default</option>
            {stacks.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      <button
        className="bp-block-add"
        disabled={taken !== ""}
        title={taken || `Ask the chat to write ${label.toLowerCase()}`}
        onClick={() => onAdd(stack)}
      >
        +
      </button>
    </div>
  );
}

export function Palette({
  graph,
  onAdd,
  onClose,
}: {
  graph: Graph | null;
  /** One command, handed to the chat. The only thing this component emits. */
  onAdd: (command: string) => void;
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

  return (
    <Flyout title="Blocks" onClose={onClose}>
      <div className="bp-palette">
        <div className="bp-palette-lead">
          Each of these asks the chat for ordinary Python. Nothing here draws a node — one
          appears when a package satisfying the convention has been written.
        </div>

        {refused ? <div className="bp-node-why">{refused}</div> : null}

        {choices
          ? Object.entries(choices.stacks).map(([kind, stacks]) => (
              <Block
                key={kind}
                kind={kind}
                label={labelOf(kind)}
                hint={`a ${kind}/ package`}
                stacks={stacks}
                taken={
                  rooted.has(kind)
                    ? `there is already a ${kind}/ here — one of each kind per level`
                    : ""
                }
                onAdd={(stack) =>
                  onAdd(`/add-system ${kind}${stack ? ` --stack ${stack}` : ""}`)
                }
              />
            ))
          : null}

        {/* A tool is not a kind and never becomes a node of its own: it is a function inside
            a system. It is here because it is the other thing the chat can be asked to add,
            and because `chat.choices` says the command exists. */}
        {choices?.commands.includes("add-tool") ? (
          <Block
            kind="file"
            label="Tool"
            hint="a function a system can call"
            stacks={[]}
            taken={rooted.has("agent") ? "" : "a tool goes inside a system — add one first"}
            onAdd={() => onAdd("/add-tool")}
          />
        ) : null}
      </div>
    </Flyout>
  );
}
