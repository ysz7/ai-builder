/**
 * The selection's panel, in the reference's configuration chrome (P18.4).
 *
 * Four flat sections with a heading and a chevron, replacing the `Details` / `Code` tab pair
 * that put a node's *buttons* inside its *details* for no reason anybody could state. What
 * each section is, and where it came from:
 *
 *   - **Knobs** -- every knob, with the control its declared type implies (Q3). The same
 *     control the card draws and the same `knob.set` behind it: there is one write path.
 *   - **Code** -- the editor from Q15, generated zones read-only.
 *   - **Actions** -- every verb the kind offers, asked of the registry and never listed
 *     here (§5.6).
 *   - **Evidence** -- what proved this node, what was skipped and why, and what
 *     reconciliation says diverged. New as a surface; the information existed already,
 *     spread across a tooltip, a dock face and another dock face.
 *
 * **No selection, no panel.** The canvas keeps the window, which is the reference's own
 * behaviour and the opposite of the column of nothing this replaced.
 */

import { useState } from "react";

import type { Environment, GraphNode, GraphRead, Provider } from "../core/types";
import { Actions } from "./Actions";
import { Code } from "./Code";
import { NodeEvidence } from "./Evidence";
import { KnobBlock } from "./Knob";
import { MODEL_KNOBS, ModelPicker, namesAModel } from "./Model";
import { Notice } from "./Notice";
import { Repairs } from "./Repairs";

type Props = {
  project: string;
  graph: GraphRead;
  node: GraphNode;
  busy: boolean;
  refused: string | null;
  running: boolean;
  services: Environment | null;
  /** Providers a person saved. Offered on a node that names a model; never a constraint. */
  providers: Provider[];
  onKnob: (node: string, knob: string, value: unknown) => void;
  onDismiss: () => void;
  onActed: () => void;
  onWritten: () => void;
  onHandOver: (request: string) => void;
  onClose: () => void;
};

function Section({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count?: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className={`bp-sect${open ? " is-open" : ""}`}>
      <button className="bp-sect-head" onClick={onToggle}>
        <span className="bp-sect-title">{title}</span>
        {count !== undefined ? <span className="bp-sect-n">{count}</span> : null}
        <span className="bp-sect-chev">{open ? "⌃" : "⌄"}</span>
      </button>
      {open ? <div className="bp-sect-body">{children}</div> : null}
    </section>
  );
}

export function Inspector({
  project,
  graph,
  node,
  busy,
  refused,
  running,
  services,
  providers,
  onKnob,
  onDismiss,
  onActed,
  onWritten,
  onHandOver,
  onClose,
}: Props) {
  // Which sections are open is a fact about this reader and this minute -- not about the
  // project, and not something worth a round trip. It resets with the window, which is
  // right: it is the least consequential state in the application.
  const [open, setOpen] = useState<Record<string, boolean>>({
    knobs: true,
    evidence: true,
  });
  const toggle = (id: string) =>
    setOpen((now) => ({ ...now, [id]: !now[id] }));

  return (
    <aside className="bp-inspector">
      <header className="bp-inspector-head">
        <div>
          <div className="bp-inspector-title">{node.title ?? node.id}</div>
          <div className="bp-inspector-kind">{node.kind}</div>
        </div>
        <button className="bp-icon" onClick={onClose} title="Close" aria-label="Close">
          ✕
        </button>
      </header>

      {node.summary ? <p className="bp-inspector-desc">{node.summary}</p> : null}

      <Section
        title="Knobs"
        count={node.knobs.length}
        open={open.knobs ?? false}
        onToggle={() => toggle("knobs")}
      >
        {node.knobs.length === 0 ? (
          <div className="bp-empty">This node declares no knobs.</div>
        ) : (
          <>
            {/* Where a node names a model, its three model knobs are one control -- the
                duplication a person sees between the providers panel and the node was in
                the presentation, never in the code. See `Model.tsx`. */}
            {namesAModel(node) ? (
              <ModelPicker node={node} providers={providers} onKnob={onKnob} />
            ) : null}
            {node.knobs
              .filter((knob) => !(namesAModel(node) && MODEL_KNOBS.includes(knob.name)))
              .map((knob) => (
                <KnobBlock
                  key={knob.name}
                  knob={knob}
                  onChange={(value) => onKnob(node.id, knob.name, value)}
                />
              ))}
          </>
        )}
        {busy ? <div className="bp-block-note">writing…</div> : null}
        {refused ? (
          // A refusal is a normal answer to a normal question -- out of bounds, wrong type,
          // a locked signature -- and the value stays what it was.
          <Notice tone="refused" label="refused" text={refused} onClose={onDismiss} />
        ) : null}
      </Section>

      <Section
        title="Evidence"
        open={open.evidence ?? false}
        onToggle={() => toggle("evidence")}
      >
        <NodeEvidence graph={graph} node={node.id} />
        <Repairs
          project={project}
          node={node.id}
          onDone={onWritten}
          onHandOver={onHandOver}
        />
      </Section>

      <Section
        title="Actions"
        open={open.actions ?? false}
        onToggle={() => toggle("actions")}
      >
        <Actions
          project={project}
          node={node}
          running={running}
          services={services}
          onActed={onActed}
        />
      </Section>

      <Section title="Code" open={open.code ?? false} onToggle={() => toggle("code")}>
        {/* Mounted only while the section is open: it reads the node's source from disk,
            and doing that for a section nobody has unfolded is a read per selection. */}
        {open.code ? (
          <Code project={project} node={node.id} onWritten={onWritten} />
        ) : null}
      </Section>

      <div className="bp-inspector-addr">
        {node.location.file}:{node.location.start_line} · {node.location.object}
      </div>
    </aside>
  );
}
