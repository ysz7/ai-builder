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
  onClose: () => void;
  /** Handing a repair to the agent is the chat's job; this only supplies the words. */
  onHandOver: (request: string) => void;
};

export function Repairs({ project, onDone, onClose, onHandOver }: Props) {
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

  return (
    <div className="bp-modal" onClick={onClose}>
      <div className="bp-sheet" onClick={(event) => event.stopPropagation()}>
        <div className="bp-sheet-head">
          <span className="bp-detail-title">Repair</span>
          <button className="bp-btn" onClick={onClose}>
            Close
          </button>
        </div>

        {repairs === null ? <div className="bp-empty">Reading…</div> : null}
        {repairs !== null && repairs.length === 0 ? (
          <div className="bp-empty">
            Nothing has diverged from the last valid state.
          </div>
        ) : null}

        {(repairs ?? []).map((repair) => (
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
    </div>
  );
}
