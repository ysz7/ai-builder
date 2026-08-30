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
 *
 * **Every control carries `nodrag`**, which is React Flow's opt-out from the node drag. It
 * is not decoration: without it the library takes the `mousedown` to start dragging the card
 * and calls `preventDefault` on it, so a native control never gets the press it needs to set
 * up -- and a range input, which holds the pointer for the length of a drag, is left holding
 * it with nothing to release it. The window then follows the mouse forever and nothing else
 * in the application can be clicked. The class is harmless in the inspector, where there is
 * no drag to opt out of, which is why it lives on the control rather than at either surface.
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
  suggestions,
}: {
  knob: Knob;
  onChange: (value: unknown) => void;
  /**
   * Values worth offering for a free-text knob — the models a person saved (`providers.*`).
   *
   * **A suggestion, never a constraint.** A `choices` knob is a select because the *type*
   * says so (Q3), and the declaration is the only thing allowed to close a set of values. A
   * list drawn from tooling state that could not be departed from would make a knob mean
   * something the code does not say, so this is a datalist: it types faster and forbids
   * nothing.
   */
  suggestions?: string[];
}) {
  const source = literal(knob);
  const [draft, setDraft] = useState(source);
  /** Whether the saved-model list is showing. Nothing else in the application cares. */
  const [open, setOpen] = useState(false);

  /**
   * **A typed value that has not landed looks exactly like one that has, and that is a bug.**
   *
   * A free-text knob writes on blur, so somebody who types a model and then closes the
   * panel, presses Observe, or quits has changed nothing: the field showed their model, the
   * source still said the old one, and the value "disappeared" on the next start. It never
   * existed. The field cannot commit on its own -- a write into somebody's Python because a
   * component unmounted is not an edit anybody asked for (I-6) -- so it says so instead.
   */
  const dirty = draft !== source;
  const declared = knob.type.trim();

  // The source is the truth, and a write re-reads the project: when the literal comes back
  // different from what is in the field -- because the write landed, or because the agent
  // rewrote the line -- the field follows it. Without this the control would keep showing
  // what somebody typed after the code stopped saying it.
  useEffect(() => setDraft(source), [source]);

  if (knob.choices) {
    return (
      <select
        className="bp-field nodrag"
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
        className={`bp-switch nodrag${on ? " is-on" : ""}`}
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
      <label className="bp-slider nodrag">
        {/* The track is its own element so the fill's percentage is a percentage **of the
            track** and not of the row, which also carries the value's column. Computing
            around that column in CSS worked until the column changed width. */}
        <span className="bp-slider-track">
          <span
            className="bp-slider-fill"
            style={{ width: `${Math.max(0, Math.min(100, fill))}%` }}
          />
        </span>
        <span className="bp-slider-value">{value}</span>
        <input
          type="range"
          min={knob.min}
          max={knob.max}
          step={knob.step ?? 1}
          value={value}
          onChange={(event) => setDraft(event.target.value)}
          // `pointerup` rather than `mouseup`: the input holds the pointer for the length of
          // the drag, so this arrives even when the release happens well outside the track.
          // With `mouseup` a value chosen by dragging past the end was simply never written.
          onPointerUp={() => onChange(Number(draft))}
          onKeyUp={() => onChange(Number(draft))}
        />
      </label>
    );
  }

  // **A visible list, not a `datalist`.** The first version of this was `<input list>`,
  // which is the right element and the wrong one here: this window is WKWebView, where a
  // datalist offers nothing until somebody types a prefix -- so a person who had just saved
  // a model saw a plain text field and concluded, correctly from what was in front of them,
  // that nothing had been saved. A control whose only affordance is knowing it is there is
  // not an affordance.
  //
  // It stays a text field with a button beside it rather than becoming a select, for the
  // reason the type rule gives (Q3): only the declaration may close a set of values, and a
  // model this list has never heard of has to stay typeable.
  if (suggestions && suggestions.length > 0) {
    return (
      <span className={`bp-combo nodrag${dirty ? " is-dirty" : ""}`}>
        <input
          className="bp-field"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => onChange(draft)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
        <button
          type="button"
          className="bp-combo-open"
          aria-label="Saved models"
          onClick={() => setOpen((was) => !was)}
        >
          ⌄
        </button>
        {dirty ? <span className="bp-unsaved">unsaved — press Enter</span> : null}
        {open ? (
          <span className="bp-combo-list">
            {suggestions.map((one) => (
              <button
                key={one}
                type="button"
                className="bp-combo-item"
                // `onMouseDown`: the input's `blur` fires first otherwise and writes the
                // half-typed draft over the value being picked.
                onMouseDown={(event) => {
                  event.preventDefault();
                  setDraft(one);
                  setOpen(false);
                  onChange(one);
                }}
              >
                {one}
              </button>
            ))}
          </span>
        ) : null}
      </span>
    );
  }

  return (
    <>
      <input
        className={`bp-field nodrag${dirty ? " is-dirty" : ""}`}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => onChange(draft)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      {dirty ? <span className="bp-unsaved">unsaved — press Enter</span> : null}
    </>
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
  suggestions,
}: {
  knob: Knob;
  onChange: (value: unknown) => void;
  suggestions?: string[];
}) {
  return (
    <div className="bp-block">
      <span className="bp-block-label">{knob.label ?? knob.name}</span>
      <KnobControl knob={knob} onChange={onChange} suggestions={suggestions} />
      {knob.location === null ? (
        <div className="bp-block-note">
          no literal default — it can be shown, never written
        </div>
      ) : null}
      {knob.help ? <div className="bp-block-note">{knob.help}</div> : null}
    </div>
  );
}
