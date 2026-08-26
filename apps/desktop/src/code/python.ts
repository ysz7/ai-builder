/**
 * Python, coloured.
 *
 * A **lexer, not a parser**, and deliberately so: the only opinion about what a Python file
 * means that this project is allowed to hold lives in `parser.py`, on the other side of the
 * wire. This one classifies runs of characters so the eye can find its way, and if it gets a
 * corner wrong the result is a mis-tinted word, never a wrong graph.
 *
 * The palette is VS Code's, taken from tokens.css, so the code in a node reads the way the
 * same code reads in the editor the person will open it in next.
 */

const KEYWORDS = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "class",
  "def",
  "del",
  "global",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "type",
]);

/** Control flow is a different colour from other keywords in Dark+, and that is the point. */
const CONTROL = new Set([
  "break",
  "case",
  "continue",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "if",
  "import",
  "match",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);

export type Token = { text: string; cls: string };

const NAME = /[A-Za-z_][A-Za-z0-9_]*/y;
const NUMBER = /\d[\d_]*(\.[\d_]*)?([eE][+-]?\d+)?j?/y;
const STRING = /([rbfu]{0,2})("""|'''|"|')/iy;

function stringAt(source: string, at: number): number {
  STRING.lastIndex = at;
  const opened = STRING.exec(source);
  if (!opened) return -1;

  const quote = opened[2];
  let index = at + opened[0].length;
  while (index < source.length) {
    if (source[index] === "\\") {
      index += 2;
      continue;
    }
    if (source.startsWith(quote, index)) return index + quote.length;
    // A single-quoted string that never closes ends at the line, the way Python's does.
    if (quote.length === 1 && source[index] === "\n") return index;
    index += 1;
  }
  return source.length;
}

export function tokenize(source: string): Token[] {
  const out: Token[] = [];
  const push = (text: string, cls: string) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last && last.cls === cls) last.text += text;
    else out.push({ text, cls });
  };

  let index = 0;
  while (index < source.length) {
    const character = source[index];

    if (character === "#") {
      const end = source.indexOf("\n", index);
      const stop = end === -1 ? source.length : end;
      push(source.slice(index, stop), "cmt");
      index = stop;
      continue;
    }

    if (character === '"' || character === "'" || /[rbfu]/i.test(character)) {
      const end = stringAt(source, index);
      if (end !== -1) {
        push(source.slice(index, end), "str");
        index = end;
        continue;
      }
    }

    if (character === "@") {
      // A decorator is the markup layer's whole surface (I-4), so it is worth seeing at once.
      NAME.lastIndex = index + 1;
      const named = NAME.exec(source);
      if (named) {
        push(source.slice(index, NAME.lastIndex), "fn");
        index = NAME.lastIndex;
        continue;
      }
    }

    if (/[A-Za-z_]/.test(character)) {
      NAME.lastIndex = index;
      const named = NAME.exec(source)!;
      const word = named[0];
      const after = source.slice(index + word.length).match(/^\s*/)![0].length;
      const next = source[index + word.length + after];

      let cls = "var";
      if (CONTROL.has(word)) cls = "ctl";
      else if (KEYWORDS.has(word)) cls = "key";
      else if (next === "(") cls = "fn";
      else if (/^[A-Z]/.test(word)) cls = "type";

      push(word, cls);
      index += word.length;
      continue;
    }

    if (/\d/.test(character)) {
      NUMBER.lastIndex = index;
      const number = NUMBER.exec(source);
      if (number) {
        push(number[0], "num");
        index += number[0].length;
        continue;
      }
    }

    push(character, /[\s]/.test(character) ? "ws" : "punct");
    index += 1;
  }
  return out;
}
