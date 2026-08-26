/**
 * Markdown, as much of it as an answer in a chat actually uses.
 *
 * **Written here rather than depended on.** A Markdown library is a dependency decision, and
 * this is a rendering problem the size of one file: headings, emphasis, code, lists, rules,
 * quotes. The same reasoning as `python.ts` next door, and the same limit -- it is a
 * *formatter*, never a parser of meaning. A corner it gets wrong costs a mis-styled line, and
 * nothing downstream believes anything because of what it produced.
 *
 * Text is placed as text, never as HTML. There is no `dangerouslySetInnerHTML` here and there
 * must never be one: the agent's output is not ours, and a renderer that injected markup
 * would make the transcript a place where a page could be built.
 */

import { tokenize } from "./python";

type Props = { source: string };

/** Inline runs: `code`, **bold**, *italic*. Applied in that order, code first, so that
 *  asterisks inside a code span stay asterisks. */
function inline(text: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(_[^_\n]+_)/g;
  let at = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > at) out.push(text.slice(at, match.index));
    const piece = match[0];
    const id = `${key}-${index++}`;
    if (piece.startsWith("`")) {
      out.push(
        <code key={id} className="bp-md-code">
          {piece.slice(1, -1)}
        </code>,
      );
    } else if (piece.startsWith("**")) {
      out.push(<strong key={id}>{piece.slice(2, -2)}</strong>);
    } else {
      out.push(<em key={id}>{piece.slice(1, -1)}</em>);
    }
    at = match.index + piece.length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

function Fence({ code, language }: { code: string; language: string }) {
  // Python is the language this application is about, so it is the one that gets colour.
  // Anything else is set in the same type without a claim about what its words mean.
  if (language === "python" || language === "py") {
    return (
      <pre className="bp-md-fence bp-src">
        {tokenize(code).map((token, index) => (
          <span key={index} className={`t-${token.cls}`}>
            {token.text}
          </span>
        ))}
      </pre>
    );
  }
  return <pre className="bp-md-fence">{code}</pre>;
}

export function Markdown({ source }: Props) {
  const blocks: React.ReactNode[] = [];
  const lines = source.split("\n");
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];

    const fence = /^```(\w*)/.exec(line);
    if (fence) {
      const language = fence[1];
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1; // the closing fence, or the end of the text if it never came
      blocks.push(
        <Fence key={key++} code={body.join("\n")} language={language} />,
      );
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(
        <div key={key++} className={`bp-md-h is-h${heading[1].length}`}>
          {inline(heading[2], `h${key}`)}
        </div>,
      );
      index += 1;
      continue;
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\s*\d+\./.test(line);
      while (
        index < lines.length &&
        /^\s*([-*+]|\d+\.)\s+/.test(lines[index])
      ) {
        items.push(lines[index].replace(/^\s*([-*+]|\d+\.)\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={key++} className={`bp-md-list${ordered ? " is-ordered" : ""}`}>
          {items.map((item, at) => (
            <li key={at}>{inline(item, `l${key}-${at}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoted: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push(
        <div key={key++} className="bp-md-quote">
          {inline(quoted.join("\n"), `q${key}`)}
        </div>,
      );
      continue;
    }

    if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
      blocks.push(<div key={key++} className="bp-md-rule" />);
      index += 1;
      continue;
    }

    // A paragraph runs to the next blank line. Single newlines inside it are kept, because
    // an agent's answer uses them to mean something and reflowing would lose it.
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() !== "") {
      if (/^(```|#{1,4}\s|\s*>|\s*([-*+]|\d+\.)\s)/.test(lines[index])) break;
      paragraph.push(lines[index]);
      index += 1;
    }
    if (paragraph.length > 0) {
      blocks.push(
        <p key={key++} className="bp-md-p">
          {inline(paragraph.join("\n"), `p${key}`)}
        </p>,
      );
    } else {
      index += 1; // a blank line
    }
  }

  return <div className="bp-md">{blocks}</div>;
}
