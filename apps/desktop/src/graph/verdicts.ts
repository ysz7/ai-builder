/**
 * How a verdict becomes something you can see.
 *
 * Two rules, and they are the ones a nicer-looking canvas would erode first.
 *
 * **Colour identifies the kind; the verdict is a mark.** The category tab above a card
 * carries the kind and never changes, so a node that goes red is still visibly an Agent.
 * Washing the whole card in a state colour would be two facts fighting over one element,
 * and the one that lost would be the one that says what the node *is*.
 *
 * **The quiet state is the unproven one.** A project nobody has run yet must not read as a
 * screen full of warnings, so grey is quiet and green is spent only on what a run earned.
 * Green still gets *drawn*, faintly: if it were hidden, the absence of a mark would come to
 * mean "proven", and a graph nobody has observed would look much like one that passed.
 *
 * There are five states because the core reports five, and each is a different claim.
 * `grey` is "no test reached it" and `skipped` is "the run did not happen" — a fact about
 * the project and a fact about the attempt. They are never merged.
 */

/** No verdict at all: this project has not been observed, or the node is a file. */
export const UNOBSERVED = "";

const MARKS: Record<string, string> = {
  green: "✓",
  red: "✕",
  // Not a shade of green and not a warning: "everything I could check passed, and something
  // was never checked". A half-filled circle is the only glyph that says a partial answer.
  amber: "◐",
  grey: "?",
  // A dash, because nothing happened. A question mark here would be the same as grey, and
  // the difference between them is the whole reason both exist.
  skipped: "–",
};

const WORDS: Record<string, string> = {
  green: "a passing test ran this code",
  red: "a failing test ran this code",
  amber: "part of this was never reached",
  grey: "no test reached it",
  skipped: "the run did not happen",
};

export function markOf(verdict: string): string {
  return MARKS[verdict] ?? "";
}

export function wordsFor(verdict: string): string {
  return WORDS[verdict] ?? "";
}

export function known(verdict: string): boolean {
  return verdict in MARKS;
}
