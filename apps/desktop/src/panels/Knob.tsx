/**
 * A knob, and the control its declared type implies.
 *
 * **The control comes from the type** (Q3): a bounded int is a slider, a `choices` is a
 * select, a bool is a switch. `widget` only refines where the type does not decide.
 *
 * **The default is shown as a default** (Q5). What is drawn is the literal in the source --
 * the single unambiguous write target -- never a resolved effective value, because
 * resolving would be accurate for one reading and fork the truth for every write.
 *
 * It lives in its own file because two surfaces draw knobs now: the node card, which shows
 * the first few without being opened, and the inspector, which shows all of them. **One
 * control and one write verb** -- a card with its own field would be a second write path,
 * and the second one is always the one that forgets to validate.
 */

import { useEffect, useState } from "react";

import type { Knob } from "../core/types";

/** The literal default, as the parser read it out of the source. */
export function literal(knob: Knob): string {
  return (knob.default ?? "").replace(/^["']|["']$/g, "");
}

export function KnobControl({
  knob,
  onChange,
}: {
  knob: Knob;
  onChange: (value: unknown) => void;
}) {
  const source = literal(knob);
  const [draft, setDraft] = useState(source);
  const declared = knob.type.trim();

  // The source is the truth, and a write re-reads the project: when the literal comes back
  // different from what is in the field -- because the write landed, or because the agent
  // rewrote the line -- the field follows it. Without this the control would keep showing
  // what somebody typed after the code stopped saying it.
  useEffect(() => setDraft(source), [source]);

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
        <span className="bp-switch-knob" />
        <span className="bp-switch-word">{on ? "True" : "False"}</span>
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
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
      }}
    />
  );
}

/**
 * One knob as the reference draws a field block: a small uppercase label chip over its
 * content, in an inset panel.
 *
 * The reference's blocks carry a prompt and a model; ours carry the thing that is actually
 * addressable in this architecture -- a knob with a literal the writer can reach through
 * the syntax tree. The geometry is theirs; what fills it is ours.
 */
export function KnobBlock({
  knob,
  onChange,
}: {
  knob: Knob;
  onChange: (value: unknown) => void;
}) {
  return (
    <div className="bp-block">
      <span className="bp-block-label">{knob.label ?? knob.name}</span>
      <KnobControl knob={knob} onChange={onChange} />
      {knob.location === null ? (
        <div className="bp-block-note">
          no literal default — it can be shown, never written
        </div>
      ) : null}
      {knob.help ? <div className="bp-block-note">{knob.help}</div> : null}
    </div>
  );
}
