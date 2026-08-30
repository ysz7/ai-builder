/**
 * The conversation, as a card on the canvas (Q34, amending Q18).
 *
 * Q18 settled that a chat is an action on a node and never a node of its own, and the
 * reason it gave still holds: a chat surface has no carrier, so by I-3 it is not a node,
 * and a node the canvas drew rather than the code declared would be the second source of
 * truth I-1 forbids. What changed is not the reasoning but what is being drawn.
 *
 * **This is not a node and the core has never heard of it.** It is the same affordance the
 * `Talk` button was, derived from the same single fact -- `NodeKind.converses` -- and drawn
 * as a card because a two-line button in a panel is a poor place to hold a conversation.
 * Everything that made a canvas-drawn node dangerous is absent here by construction:
 *
 *   - it is **derived, never stored**: no id in `graph.read`, nothing in the snapshot,
 *     nothing the parser could disagree with;
 *   - a person **cannot add, remove or rename one**. It appears because a kind named a way
 *     in and it disappears when that kind stops naming one, exactly as the button did;
 *   - it **wears no verdict**. A mark is a claim about a carrier proving itself under I-5,
 *     and this has no carrier to prove. A chat card that could go green would be a node
 *     with evidence it cannot have -- which is the actual thing Q18 was protecting.
 *
 * What a conversation *does* prove is unchanged and lives where it always did: `talk.*`
 * reaches the project's interpreter, and `probe.run_plan` decides what that is worth
 * (P17.4). Held open, it is evidence on **the node it is attached to**, and the mark that
 * changes is that node's.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { Talk } from "../panels/Talk";
import { glyphOf } from "./kinds";

export type TalkCardData = {
  /** The node being talked to. The card's whole identity is borrowed from it. */
  node: string;
  title: string;
  kind: string;
  project: string;
  onAnswered: () => void;
};

/**
 * The card wears the node card's own furniture -- a tab above and inset from the left, a
 * header with a glyph and a title, a labelled block -- because it stands among node cards
 * and anything else would read as a different application's element pasted onto the canvas.
 *
 * What it deliberately does **not** wear is the two things that make a node card a claim: a
 * kind pill and a verdict mark. The tab says `Chat` rather than a family, and there is no
 * mark at all -- see the note above for why a chat card that could go green would be a lie.
 * The identity pill carries the subject's id, which is the honest answer to "what is this
 * attached to" and the only thing about the card that is not its own.
 */
export function TalkCard({ data }: NodeProps) {
  const { node, title, kind, project, onAnswered } = data as unknown as TalkCardData;
  return (
    <div className="bp-talkcard-wrap">
      <div className="bp-talkcard-tab">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d="M20 12a7 7 0 0 1-7 7H8l-4 3v-4.6A7 7 0 0 1 6 6h7a7 7 0 0 1 7 6z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Chat
      </div>

      <div className="bp-talkcard">
        {/* One pin, on the side the subject is on. The line says *who is answering*; it
            carries nothing, which is why there is no pin on the other edge to balance it. */}
        <Handle type="source" position={Position.Right} id="talk-out" className="bp-pin-talk" />

        {/* The drag handle. Everything below it takes a caret or a click, and a card whose
            body dragged the canvas is a card nobody can type in. */}
        <div className="bp-talkcard-h">
          <svg className="bp-talkcard-glyph" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path
              d={glyphOf(kind)}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="bp-talkcard-title">{title}</span>
          {/* The reference's `in-0`: what this is attached to, said plainly. */}
          <span className="bp-talkcard-id" title={node}>
            {node}
          </span>
        </div>

        <p className="bp-talkcard-why">
          Ask it a question. A real process runs the real code, and what comes back is
          evidence on the node above.
        </p>

        <div className="bp-talkcard-body nodrag nowheel">
          <Talk project={project} node={node} onAnswered={onAnswered} />
        </div>
      </div>
    </div>
  );
}
