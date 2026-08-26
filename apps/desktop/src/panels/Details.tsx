/**
 * The selection's properties. Unreal's Details panel.
 *
 * **The control comes from the declared type** (Q3): a bounded int is a slider, a `choices`
 * is a select, a bool is a switch. `widget` only refines where the type does not decide.
 *
 * **The default is shown as a default** (Q5). What is drawn is the literal in the source --
 * the single unambiguous write target -- never a resolved effective value, because
 * resolving would be accurate for one reading and fork the truth for every write.
 *
 * A refusal is an ordinary answer here, not an error: out of bounds, wrong type, a locked
 * signature. The panel shows the reason and the value stays what it was.
 */

import { useState } from "react";

import type { GraphNode, Knob } from "../core/types";
import { Notice } from "./Notice";

type Props = {
  node: GraphNode | null;
  reason: string;
  busy: boolean;
  refused: string | null;
  onKnob: (node: string, knob: string, value: unknown) => void;
  onDismiss: () => void;
};

/** The literal default, as the parser read it out of the source. */
function literal(knob: Knob): string {
  return (knob.default ?? "").replace(/^["']|["']$/g, "");
}

function KnobControl({
  knob,
  onChange,
}: {
  knob: Knob;
  onChange: (value: unknown) => void;
}) {
  const [draft, setDraft] = useState(literal(knob));
  const declared = knob.type.trim();

  if (knob.choices) {
    return (
      <select
        className="bp-field"
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          onChange(event.target.value);
        }}
      >
        {knob.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  }

  if (declared.startsWith("bool")) {
    const on = draft === "True";
    return (
      <button
        className={`bp-switch${on ? " is-on" : ""}`}
        onClick={() => {
          const next = !on;
          setDraft(next ? "True" : "False");
          onChange(next);
        }}
      >
        {on ? "True" : "False"}
      </button>
    );
  }

  if (declared.startsWith("int") && knob.min !== null && knob.max !== null) {
    const value = Number(draft) || knob.min;
    const fill = ((value - knob.min) / (knob.max - knob.min)) * 100;
    return (
      <label className="bp-slider">
        <span
          className="bp-slider-fill"
          style={{ width: `${Math.max(0, Math.min(100, fill))}%` }}
        />
        <span className="bp-slider-value">{value}</span>
        <input
          type="range"
          min={knob.min}
          max={knob.max}
          step={knob.step ?? 1}
          value={value}
          onChange={(event) => setDraft(event.target.value)}
          onMouseUp={() => onChange(Number(draft))}
          onKeyUp={() => onChange(Number(draft))}
        />
      </label>
    );
  }

  return (
    <input
      className="bp-field"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => onChange(draft)}
    />
  );
}

export function Details({
  node,
  reason,
  busy,
  refused,
  onKnob,
  onDismiss,
}: Props) {
  if (!node) {
    return <div className="bp-empty">Select a node.</div>;
  }

  return (
    <div className="bp-details">
      <div className="bp-detail-head">
        <div className="bp-detail-title">{node.title ?? node.id}</div>
        <div className="bp-detail-kind">{node.kind}</div>
      </div>
      {reason ? <div className="bp-node-why">{reason}</div> : null}

      {node.knobs.length > 0 ? (
        <>
          <div className="bp-cap">
            Knobs {busy ? <span className="bp-cap-n">writing…</span> : null}
          </div>
          {node.knobs.map((knob) => (
            <div className="bp-knob" key={knob.name}>
              <div className="bp-knob-label">
                {knob.label ?? knob.name}
                <span className="bp-knob-default">{literal(knob)}</span>
              </div>
              <KnobControl
                knob={knob}
                onChange={(value) => onKnob(node.id, knob.name, value)}
              />
              {knob.location === null ? (
                <div className="bp-knob-note">
                  no literal default — it can be shown, never written
                </div>
              ) : null}
            </div>
          ))}
          {refused ? (
            <Notice
              tone="refused"
              label="refused"
              text={refused}
              onClose={onDismiss}
            />
          ) : null}
        </>
      ) : null}

      <div className="bp-cap">Carrier</div>
      <div className="bp-detail-addr">
        {node.location.file}:{node.location.start_line} · {node.location.object}
      </div>
    </div>
  );
}
