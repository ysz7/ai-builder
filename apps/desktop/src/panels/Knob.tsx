/**
 * One control, drawn from one field's annotation.
 *
 * The control is chosen by the **core**, from the type the author declared, and this
 * component only renders what it was told. That division matters: a front end that inferred
 * a control from a type string would be a second reader of Python, and the moment the two
 * disagreed the panel would offer to write something the writer would refuse.
 *
 * Two behaviours are deliberate.
 *
 * **A toggle and a select commit at once; a number and a text field commit when you leave
 * them.** Every commit is a write through libcst into somebody's file, and writing on every
 * keystroke would put `4`, `48`, `489` into a git history because a person typed 489.
 *
 * **Every knob points at its own line.** A person can always leave the panel and look at the
 * code it is talking about, which is the only honest way to claim the file is the truth.
 */

import { useEffect, useState } from "react";

import type { SettingField } from "../core/types";

export function Knob({
  field,
  busy,
  onChange,
  onOpen,
}: {
  field: SettingField;
  /** A write is in flight. The control stays put rather than snapping back and forth. */
  busy: boolean;
  onChange: (value: number | string | boolean) => void;
  onOpen: () => void;
}) {
  // What is being typed, before it is a value. Reset whenever the file says something else,
  // so an edit made elsewhere — by the agent, or by the person in their editor — wins.
  const [draft, setDraft] = useState(String(field.value ?? ""));
  useEffect(() => {
    setDraft(String(field.value ?? ""));
  }, [field.value]);

  const head = (
    <span className="bp-block-label">
      {field.name}
      <button className="bp-knob-open" onClick={onOpen} title={`Open at line ${field.line}`}>
        {field.annotation}
      </button>
    </span>
  );

  // Shown and not editable, with the reason said. Hiding it would be worse: a knob nobody
  // can see is one nobody knows they have, and the reason is what makes it fixable.
  if (field.control === "none") {
    return (
      <div className="bp-block">
        {head}
        <div className="bp-field is-locked">{String(field.value ?? "—")}</div>
        <div className="bp-knob-note">{field.reason}</div>
      </div>
    );
  }

  if (field.control === "toggle") {
    const on = field.value === true;
    return (
      <div className="bp-block">
        {head}
        <button
          className={`bp-switch${on ? " is-on" : ""}`}
          disabled={busy}
          onClick={() => onChange(!on)}
        >
          <span className="bp-switch-knob" />
          <span className="bp-switch-word">{on ? "True" : "False"}</span>
        </button>
      </div>
    );
  }

  if (field.control === "select") {
    return (
      <div className="bp-block">
        {head}
        <select
          className="bp-field"
          value={String(field.value ?? "")}
          disabled={busy}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      </div>
    );
  }

  const numeric = field.control === "integer" || field.control === "number";
  const commit = () => {
    if (!numeric) {
      if (draft !== field.value) onChange(draft);
      return;
    }
    const parsed = field.control === "integer" ? Number.parseInt(draft, 10) : Number(draft);
    // A field left in a state that is not a number is not a write. It snaps back to what the
    // file says, because the file is what is true and the draft was only ever on screen.
    if (!Number.isFinite(parsed)) {
      setDraft(String(field.value ?? ""));
      return;
    }
    if (parsed !== field.value) onChange(parsed);
  };

  return (
    <div className="bp-block">
      {head}
      <input
        className="bp-field"
        type={numeric ? "number" : "text"}
        step={field.control === "number" ? "any" : 1}
        value={draft}
        disabled={busy}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setDraft(String(field.value ?? ""));
        }}
      />
    </div>
  );
}
