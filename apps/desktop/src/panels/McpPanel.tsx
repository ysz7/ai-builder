/**
 * One MCP server: what the file declares, and the way to authorise it.
 *
 * ## What `Connect` is, and what it is not
 *
 * A server in `mcp.json` is a **stdio** server — a command and its arguments. The MCP
 * authorization specification covers the HTTP transports, not this, so there is no handshake
 * here to drive and no protocol for a button to speak. What these servers do is simpler: the
 * ones that need an account open a browser themselves on first run and write their own token
 * wherever they keep it.
 *
 * So `Connect` runs the server's own command in the terminal, where the person watches it
 * happen. Nothing is orchestrated and nothing is intercepted: what happens is what would
 * have happened had they typed the command themselves, which is the only version of this
 * that is honest about who is doing what.
 *
 * ## Two absences that are the design
 *
 * **No credential is stored, anywhere.** Not by this panel, not by the core, not in a
 * keychain. There is no HTTP client to anybody's API in this application and no reason to
 * acquire one — a builder holding somebody's Gmail token would be a liability taken on in
 * exchange for nothing.
 *
 * **There is no "connected" tick.** Only the server knows, and asking it means becoming an
 * MCP client. So this says what was done — a command was run, in a terminal you can read —
 * and never what it achieved. A tick nobody verified is the same defect as a green node
 * nobody ran a test for, and this application exists to not have that defect.
 */

import { useEffect, useState } from "react";

import { editorOpen, mcpConnect, mcpRead } from "../core/client";
import type { GraphNode, McpServer } from "../core/types";

export function McpPanel({
  project,
  node,
  onConnected,
}: {
  project: string;
  node: GraphNode;
  /** It is running in this terminal. The workspace opens the drawer on it. */
  onConnected: (shell: string) => void;
}) {
  const [server, setServer] = useState<McpServer | null>(null);
  const [refused, setRefused] = useState("");
  const [busy, setBusy] = useState(false);
  /** When `Connect` was last pressed here. What we did, never what it achieved. */
  const [ran, setRan] = useState("");

  useEffect(() => {
    let live = true;
    setServer(null);
    setRefused("");
    setRan("");
    void mcpRead(project, node.id)
      .then((answer) => live && setServer(answer))
      .catch((error: unknown) =>
        live && setRefused(error instanceof Error ? error.message : String(error)),
      );
    return () => {
      live = false;
    };
  }, [project, node.id]);

  const connect = async () => {
    setBusy(true);
    setRefused("");
    try {
      const answer = await mcpConnect(project, node.id);
      if (!answer.ok) {
        setRefused(answer.detail);
        return;
      }
      setRan(new Date().toLocaleTimeString());
      if (answer.shell) onConnected(answer.shell);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!server) {
    return refused ? <div className="bp-node-why">{refused}</div> : null;
  }

  return (
    <>
      <div className="bp-run">
        <span className="bp-node-label">Declared in</span>
        <button
          className="bp-run-second"
          onClick={() => void editorOpen(project, node.path, 1)}
        >
          Open {node.path}
        </button>

        {server.command ? (
          <pre className="bp-run-json">{[server.command, ...server.args].join(" ")}</pre>
        ) : (
          <div className="bp-node-why">{`${server.name} declares no command to run.`}</div>
        )}

        {/* Names only. A value would be a secret in a panel, and from there one console log
            from being somewhere permanent — the file it is already in is the right place. */}
        {server.env.length > 0 ? (
          <div className="bp-run-docs">
            <span className="bp-run-docs-cap">
              Environment it is given ({server.env.length}) · names only
            </span>
            {server.env.map((one) => (
              <code key={one}>{one}</code>
            ))}
          </div>
        ) : null}
      </div>

      {server.command ? (
        <div className="bp-run">
          <span className="bp-node-label">Connect</span>
          <button className="bp-run-go bp-run-wide" disabled={busy} onClick={() => void connect()}>
            {busy ? "Starting…" : `Connect ${server.name}`}
          </button>
          <div className="bp-run-note">
            Runs the server's own command in the terminal. If it needs an account it opens a
            browser itself and keeps its own token — Framestack stores nothing.
          </div>
          {/* What we did, with a time on it. Never "connected": only the server knows that,
              and this application does not ask it. */}
          {ran ? <div className="bp-run-when">started at {ran}</div> : null}
        </div>
      ) : null}

      {refused ? <div className="bp-node-why">{refused}</div> : null}
    </>
  );
}
