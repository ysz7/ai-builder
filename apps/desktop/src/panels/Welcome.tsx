/**
 * What you see before there is a project.
 *
 * Two ways in and no third: open a folder that already holds one, or make an empty one for
 * a project that does not exist yet. The new one really is empty -- a scaffold would put
 * nodes on the graph that nobody asked for, and the first thing in a project should come
 * from a generation rather than from the builder's idea of what a project is.
 */

import { useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import { projectCreate } from "../core/client";
import { Notice } from "./Notice";

type Props = {
  onOpen: (path: string) => void;
  recent: string | null;
};

export function Welcome({ onOpen, recent }: Props) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [refused, setRefused] = useState<string | null>(null);

  async function pick(): Promise<string | null> {
    const chosen = await openDialog({ directory: true, multiple: false });
    return typeof chosen === "string" ? chosen : null;
  }

  async function openExisting() {
    const chosen = await pick();
    if (chosen) onOpen(chosen);
  }

  async function createNew() {
    setRefused(null);
    const parent = await pick();
    if (!parent) return;
    const result = await projectCreate(parent, name);
    // A refusal is an answer: the folder already had something in it, and adopting it
    // quietly would be a surprise with somebody's files inside.
    if (!result.ok) setRefused(result.detail);
    else onOpen(result.detail);
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
          <button className="bp-cta" onClick={() => void openExisting()}>
            Open a project
            <span className="bp-cta-sub">a folder that already holds one</span>
          </button>

          {naming ? (
            <div className="bp-cta is-form">
              <input
                className="bp-field"
                value={name}
                autoFocus
                placeholder="project name"
                spellCheck={false}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void createNew();
                  if (event.key === "Escape") setNaming(false);
                }}
              />
              <span className="bp-cta-sub">then choose where to put it</span>
              <button className="bp-btn" onClick={() => void createNew()}>
                Choose folder
              </button>
            </div>
          ) : (
            <button className="bp-cta" onClick={() => setNaming(true)}>
              New project
              <span className="bp-cta-sub">
                an empty one; the agent writes the first of it
              </span>
            </button>
          )}
        </div>

        {refused ? (
          <Notice tone="refused" label="refused" text={refused} />
        ) : null}

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
