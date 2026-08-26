/**
 * What you see before there is a project.
 *
 * **A project is a folder you chose**, and there is one way in. It used to ask for a name and
 * then make a directory, which is this application deciding what a project is called and
 * where it goes — a decision that belongs to the person and to their disk, not here. An empty
 * folder opens exactly as well as a full one: the graph is empty because the code is, which
 * is what I-1 means, and the agent writes the first of it.
 *
 * `project.create` stays in the core for a caller that wants it. Nothing here reaches for it.
 */

import { open as openDialog } from "@tauri-apps/plugin-dialog";

type Props = {
  onOpen: (path: string) => void;
  recent: string | null;
};

export function Welcome({ onOpen, recent }: Props) {
  async function choose() {
    // The native picker is the shell's, not a core method: a folder chooser is a window, and
    // the core has no window. It is the one capability that could not be a verb.
    const chosen = await openDialog({ directory: true, multiple: false });
    if (typeof chosen === "string") onOpen(chosen);
  }

  return (
    <div className="bp-welcome">
      <div className="bp-welcome-glow" />
      <div className="bp-welcome-inner">
        <h1 className="bp-welcome-title">
          The graph is the code.
          <br />
          <em>The code is the truth.</em>
        </h1>

        <div className="bp-welcome-acts">
          <button className="bp-cta" onClick={() => void choose()}>
            Open a folder
            <span className="bp-cta-sub">
              one that holds a project, or an empty one to start in
            </span>
          </button>
        </div>

        {recent ? (
          <button className="bp-recent" onClick={() => onOpen(recent)}>
            <span className="bp-recent-cap">Last opened</span>
            {recent}
          </button>
        ) : null}
      </div>
    </div>
  );
}
