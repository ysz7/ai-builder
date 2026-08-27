/**
 * Take one piece of text somewhere else.
 *
 * An **icon and not the word**, because of where this goes: beside every line of a log, one
 * per row. The word "copy" repeated down a column is a column of the word "copy" — it reads
 * as content, competes with the thing it is next to, and pushes the text it belongs to
 * sideways. Two overlapping sheets say the same thing in the space of a character.
 *
 * It copies **what was shown and nothing more**: no timestamp bolted on, no label, no node
 * id. What the reader saw is what lands on their clipboard, and anything else would be this
 * panel deciding what somebody's message should say.
 */

import { useState } from "react";

type Props = {
  text: string;
  /** What it is offering to copy, for the tooltip. "this line" where nothing better fits. */
  what?: string;
};

export function Copy({ text, what = "this" }: Props) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      className={`bp-copy${copied ? " is-copied" : ""}`}
      title={copied ? "copied" : `Copy ${what}`}
      aria-label={`Copy ${what}`}
      onClick={(event) => {
        // The row this sits in may be a button of its own -- selecting, opening. Copying is
        // not that, and a copy that also navigated would be two actions on one press.
        event.stopPropagation();
        // A clipboard that refuses is a fact worth showing: silence here reads as a copy
        // that worked, and the person finds out it did not when they paste nothing.
        navigator.clipboard
          .writeText(text)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
        window.setTimeout(() => setCopied(false), 1400);
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width="12"
        height="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {copied ? (
          <polyline points="20 6 9 17 4 12" />
        ) : (
          <>
            <rect x="9" y="9" width="12" height="12" rx="2" />
            <path d="M5 15V5a2 2 0 0 1 2-2h10" />
          </>
        )}
      </svg>
    </button>
  );
}
