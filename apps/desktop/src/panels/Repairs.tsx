/**
 * What diverged, and what may be done about it.
 *
 * **The toolchain does not choose.** §9's second case has two non-equivalent answers -- the
 * code is right and the graph is stale, or the graph is right and the code was edited by
 * hand -- and only a person knows which. So `repair.apply` takes `resolution` with no default,
 * and this dialog is where that decision is actually made: one button per resolution, and no
 * button that means "do the sensible thing".
 *
 * A resolution the toolchain cannot carry out is not hidden -- it is handed to the agent as
 * the request text the core wrote, which is the same text a person would have had to write.
 */

import { useEffect, useState } from "react";

import { repairApply, repairList } from "../core/client";
import type { Repair } from "../core/types";
import { Notice } from "./Notice";

type Props = {
  project: string;
  onDone: () => void;
  /** Handing a repair to the agent is the chat's job; this only supplies the words. */
  onHandOver: (request: string) => void;
  /**
   * Only this node's divergences, where a node is what is being looked at.
   *
   * The list itself is still the project's -- `repair.list` is asked one question and
   * answers it about the whole project -- and this narrows what is *shown*, not what is
   * asked. Repairs are a node's business now (P18.4): the dock face that used to hold them
   * is gone, and a divergence in code the reader is not looking at is not their problem
   * this second.
   */
  node?: string;
  /** Whether there is anything to show, told to whoever draws the section around it. */
  onHas?: (has: boolean) => void;
};

export function Repairs({ project, onDone, onHandOver, node, onHas }: Props) {
  const [repairs, setRepairs] = useState<Repair[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState("");

  const reload = () => {
    setNote(null);
    repairList(project)
      .then((answer) => setRepairs(answer.repairs))
      .catch((error: unknown) =>
        setNote(error instanceof Error ? error.message : String(error)),
      );
  };

  useEffect(reload, [project]);

  async function apply(repair: Repair, resolution: string) {
    setBusy(`${repair.code}:${resolution}`);
    setNote(null);
    try {
      const answer =
        await // The divergence is addressed by its node where it has one, and by the object it is
        // at where it does not -- which is what `repair.apply` matches on.
        repairApply(
          project,
          repair.code,
          repair.node ?? repair.location.object,
          resolution,
        );
      if (!answer.applied) setNote(answer.refused ?? "the repair was refused");
      else {
        // Repairing changes the code, so the graph is asked again -- and a repair that left
        // nodes without evidence says so, rather than letting silence read as a pass.
        setNote(
          answer.unproven.length > 0
            ? `applied — unproven now: ${answer.unproven.join(", ")}`
            : "applied",
        );
        reload();
        onDone();
      }
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  const shown =
    node === undefined
      ? repairs
      : (repairs ?? []).filter((repair) => repair.node === node);

  // Told after render, never during. `null` is "still reading", which is not the same as
  // "none" -- a section that appeared and then vanished would be worse than one that waits.
  useEffect(() => onHas?.((shown?.length ?? 0) > 0), [onHas, shown?.length]);

  return (
    <div className="bp-repairs">
      <div className="bp-observe-bar">
        <button className="bp-btn" onClick={reload}>
          Check again
        </button>
        <span className="bp-observe-note">
          divergence is detected against the snapshot, never by watching files
          (I-6)
        </span>
      </div>

      {repairs === null ? <div className="bp-empty">Reading…</div> : null}
      {shown !== null && shown.length === 0 ? (
        <div className="bp-empty">
          Nothing has diverged from the last valid state.
        </div>
      ) : null}

      {(shown ?? []).map((repair) => (
        <div
          className="bp-repair"
          key={`${repair.code}:${repair.location.object}`}
        >
          <div className="bp-repair-head">
            <span className="bp-repair-code">{repair.code}</span>
            <span className="bp-fault">{repair.fault}</span>
          </div>
          <div className="bp-repair-msg">{repair.message}</div>
          <div className="bp-detail-addr">
            {repair.location.file}:{repair.location.start_line} ·{" "}
            {repair.location.object}
          </div>
          <div className="bp-repair-rule">{repair.rule}</div>

          <div className="bp-acts">
            {repair.resolutions.map((resolution) =>
              repair.mechanical.includes(resolution) ? (
                <button
                  className="bp-btn"
                  key={resolution}
                  disabled={busy !== ""}
                  onClick={() => void apply(repair, resolution)}
                >
                  {busy === `${repair.code}:${resolution}` ? "…" : resolution}
                </button>
              ) : (
                // Not something this toolchain can carry out. Handing it over is honest;
                // a greyed-out button that looked mechanical would not be.
                <button
                  className="bp-btn bp-btn-hand"
                  key={resolution}
                  title="this one is the agent's to do"
                  onClick={() => onHandOver(repair.request)}
                >
                  {resolution} → agent
                </button>
              ),
            )}
          </div>
        </div>
      ))}

      {note ? (
        <Notice tone="said" text={note} onClose={() => setNote(null)} />
      ) : null}
    </div>
  );
}
