/**
 * Everything about the application rather than about the project.
 *
 * **An account is not part of a conversation.** It was shown in the chat's header, above every
 * turn, which put somebody's email address on a screen they may well be sharing — and it is
 * not something a person reads while talking to an agent. It belongs behind a dialog they
 * open when they want it.
 *
 * Only what this application has. A settings screen is where invented options accumulate:
 * every row here corresponds to something the core can actually answer or change, and a row
 * with nothing behind it is a promise the application does not keep.
 */

import { useEffect, useState } from "react";

import { agentAccount, agentSignIn, agentSignOut } from "../core/client";
import type { Account } from "../core/client";
import { Notice } from "./Notice";

type Props = {
  project: string;
  theme: "dark" | "light";
  onTheme: (theme: "dark" | "light") => void;
  onCloseProject: () => void;
  onClose: () => void;
};

export function Settings({ project, theme, onTheme, onCloseProject, onClose }: Props) {
  const [who, setWho] = useState<Account | null>(null);
  const [busy, setBusy] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  const ask = (run: () => Promise<Account>, label: string) => {
    setBusy(label);
    setFailed(null);
    run()
      .then(setWho)
      .catch((error: unknown) =>
        setFailed(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => setBusy(""));
  };

  useEffect(() => ask(agentAccount, "reading"), []);

  return (
    <div className="bp-modal" onClick={onClose}>
      <div className="bp-sheet is-settings" onClick={(event) => event.stopPropagation()}>
        <div className="bp-sheet-head">
          <span className="bp-detail-title">Settings</span>
          <button className="bp-icon" onClick={onClose} title="Close">
            ✕
          </button>
        </div>

        <div className="bp-set">
          <div className="bp-cap">Account</div>
          {/* Read from the agent, never held here: the credential belongs to the CLI, which
              put it on this machine through its own browser flow. */}
          <div className="bp-set-row">
            <div className="bp-set-label">
              Claude
              <span className="bp-set-help">
                {who?.signed_in
                  ? `${who.email || "signed in"} · ${who.method}${who.plan ? ` · ${who.plan}` : ""}`
                  : (who?.detail ?? "asking…")}
              </span>
            </div>
            {who?.signed_in ? (
              <button
                className="bp-btn"
                disabled={busy !== ""}
                onClick={() => ask(agentSignOut, "out")}
              >
                {busy === "out" ? "…" : "Sign out"}
              </button>
            ) : (
              <button
                className="bp-btn"
                disabled={busy !== ""}
                onClick={() => ask(() => agentSignIn(), "in")}
                title="opens the agent's own sign-in page in your browser"
              >
                {busy === "in" ? "Waiting for the browser…" : "Sign in"}
              </button>
            )}
          </div>

          <div className="bp-cap">Appearance</div>
          <div className="bp-set-row">
            <div className="bp-set-label">
              Theme
              <span className="bp-set-help">how the workspace is lit</span>
            </div>
            <div className="bp-set-pick">
              {(["dark", "light"] as const).map((which) => (
                <button
                  key={which}
                  className={`bp-term-pick${theme === which ? " is-on" : ""}`}
                  onClick={() => onTheme(which)}
                >
                  {which}
                </button>
              ))}
            </div>
          </div>

          <div className="bp-cap">Project</div>
          <div className="bp-set-row">
            <div className="bp-set-label">
              {project || "none open"}
              <span className="bp-set-help">
                closing leaves everything on disk; nothing is written by closing
              </span>
            </div>
            <button className="bp-btn" disabled={!project} onClick={onCloseProject}>
              Close
            </button>
          </div>
        </div>

        {failed ? (
          <Notice tone="failed" label="failed" text={failed} onClose={() => setFailed(null)} />
        ) : null}
      </div>
    </div>
  );
}
