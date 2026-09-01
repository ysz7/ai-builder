/**
 * How a kind becomes something you can see.
 *
 * One rule, and it is the one a convenience would erode first: **colour identifies the
 * kind, never the state.** In the reference it is the category tab above the card, and ours
 * carries the kind in that tab, in that geometry. A verdict — when there is one to have —
 * gets a mark of its own rather than a hue that fights the tab for the same pixels.
 *
 * There are six entries and there is no registry behind them. Five are what the core returns
 * for a node — one of the four conventions, or `file` — and the sixth is `container`, which
 * is not a kind at all: it is a service the project's compose file declares, held beside the
 * graph and drawn in the same visual language. Anything else falls through to the neutral
 * tint rather than being guessed at. The old version of this file mapped twenty-seven
 * registry kinds onto framework families, and mapping a node to a framework is precisely the
 * claim the convention removed.
 *
 * `container` is called that and not "service", because `api` is already called Service on
 * this canvas and two different things under one word is how a person stops trusting either.
 */

/** What the category tab says. The kind as a person names it, not as the payload spells it. */
const LABELS: Record<string, string> = {
  agent: "Agent",
  api: "Service",
  rag: "RAG",
  worker: "Worker",
  file: "File",
  container: "Container",
};

/**
 * A path in a 24-box, stroked. Two of these is less than an icon dependency, and an icon
 * set is a thing to keep in step with a design that is already ported by hand.
 */
const GLYPHS: Record<string, string> = {
  // A figure: the thing that is asked and answers.
  agent: "M12 3a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM5 21v-1.5A4.5 4.5 0 0 1 9.5 15h5a4.5 4.5 0 0 1 4.5 4.5V21",
  // A server that answers over a wire.
  api: "M4 5h16v5H4zM4 14h16v5H4zM7.5 7.5h.01M7.5 16.5h.01",
  // Stacked documents with a query going in.
  rag: "M4 6c0-1.4 3.6-2.5 8-2.5s8 1.1 8 2.5-3.6 2.5-8 2.5S4 7.4 4 6zM4 6v6c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V6M4 12v6c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-6",
  // A queue of jobs waiting to be handled.
  worker: "M5 4h14v4H5zM5 10h14v4H5zM5 16h14v4H5z",
  // A page with a folded corner.
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  // A box, stacked and shipped. What compose brings up.
  container: "M12 3l8 4.5-8 4.5-8-4.5zM4 7.5v9l8 4.5 8-4.5v-9M12 12v9",
};

/** A kind the core actually names. Anything else lands on the neutral tint. */
function known(kind: string): boolean {
  return kind in LABELS;
}

export function labelOf(kind: string): string {
  return LABELS[kind] ?? kind;
}

export function glyphOf(kind: string): string {
  return GLYPHS[kind] ?? GLYPHS.file;
}

/** The ink: the tab's text, and the ring on a pin an edge lands on. */
export function tintOf(kind: string): string {
  return `var(--k-${known(kind) ? kind : "none"})`;
}

/** The ground: the tab's fill, and nothing else. A card is never filled with a kind. */
export function tintBgOf(kind: string): string {
  return `var(--k-${known(kind) ? kind : "none"}-bg)`;
}

/**
 * What the kind requires, as one line for the card's pill.
 *
 * The export **is** the node's identity, so it is on the face of the card rather than
 * hidden in a panel: `agent/` is an Agent because it exports `run`, and a person reading
 * the canvas should be able to see the reason a thing is there.
 */
export function contractOf(exports: string[]): string {
  return exports.join(", ");
}
