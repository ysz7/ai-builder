/**
 * The agent asking a person to decide (Q37).
 *
 * Every other thing that stops a turn is the agent asking to **do** something, and yes/no
 * fits it exactly. This one is different in kind: `AskUserQuestion` asks the person to
 * choose, and answering it with `Allow` allows the question to be *asked* without ever
 * saying what the answer was — so the turn carried on with the agent picking for itself.
 * That is not a cosmetic gap. It cost a real decision about a vector store, in a panel that
 * showed the options as a wall of JSON beside two buttons that did not fit them.
 *
 * The options come from the request as **data** — the core hands them over structured, so
 * nothing here parses prose back into a form. What is sent back is the label the person
 * chose, keyed by the question, which is what the agent's own tool declares `answers` to be.
 *
 * **`Other` is deliberately here and deliberately free text.** The tool guarantees it, and a
 * form that only offered the agent's four options would make a person pick the nearest wrong
 * one rather than say the true thing.
 */

import { useState } from "react";

import type { AgentQuestion } from "../core/client";

type Props = {
  questions: AgentQuestion[];
  busy: boolean;
  onAnswer: (answers: Record<string, string>) => void;
  onDecline: () => void;
};

export function Question({ questions, busy, onAnswer, onDecline }: Props) {
  /** Chosen label per question, and the free-text one kept apart until it is used. */
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [other, setOther] = useState<Record<string, string>>({});
  /** Which questions are on `Other`, so an empty box does not read as "nothing chosen". */
  const [othering, setOthering] = useState<Record<string, boolean>>({});

  const keyOf = (question: AgentQuestion, index: number) =>
    question.question || question.header || `question-${index}`;

  const valueOf = (key: string) => (othering[key] ? (other[key] ?? "").trim() : picked[key]);
  const ready = questions.every((question, index) => Boolean(valueOf(keyOf(question, index))));

  return (
    <div className="bp-ask is-waiting">
      <div className="bp-ask-h">Question</div>

      {questions.map((question, index) => {
        const key = keyOf(question, index);
        return (
          <div className="bp-q" key={key}>
            {question.header ? <div className="bp-q-tag">{question.header}</div> : null}
            <div className="bp-q-text">{question.question}</div>

            <div className="bp-q-options">
              {(question.options ?? []).map((option) => {
                const label = option.label ?? "";
                const on = !othering[key] && picked[key] === label;
                return (
                  <button
                    className={`bp-q-option${on ? " is-on" : ""}`}
                    key={label}
                    disabled={busy}
                    onClick={() => {
                      setPicked((previous) => ({ ...previous, [key]: label }));
                      setOthering((previous) => ({ ...previous, [key]: false }));
                    }}
                  >
                    <span className="bp-q-label">{label}</span>
                    {option.description ? (
                      <span className="bp-q-why">{option.description}</span>
                    ) : null}
                  </button>
                );
              })}

              {/* The tool guarantees this, and it earns its place: without it a person
                  picks the nearest wrong option instead of saying the true thing. */}
              <button
                className={`bp-q-option${othering[key] ? " is-on" : ""}`}
                disabled={busy}
                onClick={() => setOthering((previous) => ({ ...previous, [key]: true }))}
              >
                <span className="bp-q-label">Other</span>
              </button>
            </div>

            {othering[key] ? (
              <input
                className="bp-field"
                autoFocus
                value={other[key] ?? ""}
                placeholder="Say what you want instead"
                disabled={busy}
                onChange={(event) =>
                  setOther((previous) => ({ ...previous, [key]: event.target.value }))
                }
              />
            ) : null}
          </div>
        );
      })}

      <div className="bp-ask-acts">
        <button
          className="bp-btn bp-btn-go"
          disabled={busy || !ready}
          onClick={() => {
            const answers: Record<string, string> = {};
            questions.forEach((question, index) => {
              const key = keyOf(question, index);
              const value = valueOf(key);
              if (value) answers[key] = value;
            });
            onAnswer(answers);
          }}
        >
          {busy ? "…" : "Answer"}
        </button>
        {/* Declining is still available, and it is honest about what it does: the agent is
            told the person did not answer, and decides for itself what to do next. */}
        <button className="bp-btn" disabled={busy} onClick={onDecline}>
          Skip
        </button>
        {!ready ? (
          <span className="bp-acts-state">
            {questions.length > 1 ? "Answer each one." : "Pick one."}
          </span>
        ) : null}
      </div>
    </div>
  );
}
