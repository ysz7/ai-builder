/**
 * A node's code, in a tab.
 *
 * This is what makes the panel an editor rather than a viewer (Q15), and it loosens nothing:
 * a generated zone is shown read-only because it is written through the graph, a locked
 * signature is shown as locked, and every save goes through `node.set_body` -- addressed by
 * node **and** function, because I-6 says code is edited through a node.
 *
 * The refusals are the core's, not this panel's. It does not pre-judge what will be accepted;
 * it sends the text and shows what came back, so there is exactly one place that decides.
 */

import { useEffect, useState } from "react";

import { tokenize } from "../code/python";
import { bodySet, nodeSource } from "../core/client";
import type { FunctionSource, NodeSource } from "../core/types";
import { Notice } from "./Notice";

type Props = {
  project: string;
  node: string;
  /** A write that landed changes the file, so the graph has to be asked again. */
  onWritten: () => void;
};

function Highlighted({ source }: { source: string }) {
  return (
    <pre className="bp-src">
      {tokenize(source).map((token, index) => (
        <span key={index} className={`t-${token.cls}`}>
          {token.text}
        </span>
      ))}
    </pre>
  );
}

function Body({
  project,
  node,
  fn,
  onWritten,
}: Props & { fn: FunctionSource }) {
  const [draft, setDraft] = useState(fn.source);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // A different function -- or the same one re-read after a write -- replaces the draft. The
  // file is the source of truth, so an edit box that kept its own text would be a second one.
  useEffect(() => {
    setDraft(fn.source);
    setEditing(false);
    setNote(null);
  }, [fn.path, fn.source]);

  const generated = fn.zone === "generated";
  const editable = fn.zone === "editable";

  async function save() {
    setSaving(true);
    setNote(null);
    try {
      const answer = await bodySet(project, node, fn.path, draft);
      if (!answer.written) setNote(answer.refused ?? "the write was refused");
      else {
        setEditing(false);
        onWritten();
      }
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bp-fn">
      <div className="bp-fn-head">
        <span className="bp-fn-name">{fn.path.split(".").pop()}</span>
        <span className={`bp-zone is-${fn.zone ?? "none"}`}>
          {fn.zone ?? "unclassified"}
        </span>
        {fn.signature_locked ? (
          <span
            className="bp-lock"
            title="the signature is the contract an edge binds to"
          >
            signature locked
          </span>
        ) : null}
        {editable ? (
          editing ? (
            <>
              <button
                className="bp-btn bp-btn-go"
                disabled={saving}
                onClick={() => void save()}
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                className="bp-btn"
                disabled={saving}
                onClick={() => {
                  setDraft(fn.source);
                  setEditing(false);
                  setNote(null);
                }}
              >
                Cancel
              </button>
            </>
          ) : (
            <button className="bp-btn" onClick={() => setEditing(true)}>
              Edit
            </button>
          )
        ) : null}
      </div>

      <div className="bp-fn-sig">{fn.signature}</div>

      {editing ? (
        <textarea
          className="bp-editor"
          spellCheck={false}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : (
        <Highlighted source={fn.source} />
      )}

      {generated ? (
        <div className="bp-knob-note">
          generated — written through the graph, so it is read-only here
        </div>
      ) : null}
      {note ? (
        <Notice
          tone="refused"
          label="refused"
          text={note}
          onClose={() => setNote(null)}
        />
      ) : null}
    </div>
  );
}

export function Code({ project, node, onWritten }: Props) {
  const [read, setRead] = useState<NodeSource | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const reload = () => {
    setFailed(null);
    nodeSource(project, node)
      .then(setRead)
      .catch((error: unknown) =>
        setFailed(error instanceof Error ? error.message : String(error)),
      );
  };

  useEffect(reload, [project, node]);

  if (failed) {
    return (
      <Notice
        tone="failed"
        label="failed"
        text={failed}
        onClose={() => setFailed(null)}
      />
    );
  }
  if (!read) return <div className="bp-empty">Reading…</div>;
  // Not dismissible: it is not an event that happened, it is what this node's code panel
  // has to say for as long as the node is selected.
  if (read.refused) return <Notice tone="refused" text={read.refused} />;

  return (
    <div className="bp-code">
      <div className="bp-detail-addr">{read.file}</div>

      {read.functions.length === 0 ? (
        // A group's carrier is a module of declarations; there is no body to edit, and
        // saying so is better than an empty box that looks broken.
        <>
          <div className="bp-cap">Carrier</div>
          <Highlighted source={read.source} />
        </>
      ) : (
        read.functions.map((fn) => (
          <Body
            key={fn.path}
            project={project}
            node={node}
            fn={fn}
            onWritten={() => {
              reload();
              onWritten();
            }}
          />
        ))
      )}
    </div>
  );
}
