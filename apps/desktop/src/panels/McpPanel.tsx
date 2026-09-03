/**
 * One MCP server: what the file declares, how it is authorised, and what it turned out to
 * offer.
 *
 * ## `Connect` means two different things, because there are two kinds of entry
 *
 * A **`command`** entry is a stdio server, and `Connect` runs the server's own command in the
 * terminal where the person watches it happen. The ones that need an account open a browser
 * themselves on first run and keep their own token; nothing is orchestrated and nothing is
 * intercepted, which is the only version of that which is honest about who is doing what.
 *
 * A **`url`** entry is an HTTP server, and there the authorization spec does apply.
 * `Connect` runs path one: the person registers an OAuth app in the provider's own console,
 * pastes the client id and secret into the fields below, the system browser opens on the
 * consent screen, and the token lands in `.env`. **There is no Framestack OAuth app** — every
 * user under one registration is one revocation away from everybody stopping at once.
 *
 * ## The tick is earned, and nothing else produces it
 *
 * `Check` asks the server: `initialize`, then `tools/list`. `connected · 8 tools` means a
 * server answered, at a time, and the tools are what it named. An entry existing produces
 * nothing, a command on `PATH` produces nothing, a token in `.env` produces nothing — the
 * same rule the verdicts follow, applied to somebody else's program.
 *
 * ## What never crosses this boundary
 *
 * **A value.** The fields write one way: what comes back is which keys `.env` now sets, by
 * name. Nothing here reads a secret back, and there is no field it would go in.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  editorOpen,
  mcpAuthorized,
  mcpCancel,
  mcpConnect,
  mcpProbe,
  mcpRead,
  mcpSecret,
} from "../core/client";
import type { GraphNode, McpAuth, McpProbe, McpServer } from "../core/types";

/** The two credentials a person pastes. The token is not among them: it is never typed. */
const CREDENTIALS = [
  { field: "client_id", label: "Client ID" },
  { field: "client_secret", label: "Client secret" },
];

export function McpPanel({
  project,
  node,
  onConnected,
  onProbed,
}: {
  project: string;
  node: GraphNode;
  /** It is running in this terminal. The workspace opens the drawer on it. */
  onConnected: (shell: string) => void;
  /**
   * What the server answered, handed up so the card on the canvas can say it too.
   *
   * The panel is where the reason goes; the card gets the one word. Both come from the same
   * probe, so neither can say something the other does not.
   */
  onProbed: (probe: McpProbe) => void;
}) {
  const [server, setServer] = useState<McpServer | null>(null);
  const [refused, setRefused] = useState("");
  const [busy, setBusy] = useState(false);
  /** When `Connect` was last pressed on a stdio server. What we did, never what it achieved. */
  const [ran, setRan] = useState("");
  const [probe, setProbe] = useState<McpProbe | null>(null);
  const [asking, setAsking] = useState(false);
  /** The browser exchange, while one is out there with somebody in front of it. */
  const [auth, setAuth] = useState<McpAuth | null>(null);
  /** What has been typed into the credential fields but not yet written. */
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const polling = useRef(false);

  const read = useCallback(async () => {
    try {
      setServer(await mcpRead(project, node.id));
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  }, [project, node.id]);

  useEffect(() => {
    setServer(null);
    setRefused("");
    setRan("");
    setProbe(null);
    setAuth(null);
    setDrafts({});
    void read();
  }, [read]);

  /**
   * Ask the server what it offers.
   *
   * Never on open: a probe starts the server's own process, and a panel that started
   * somebody's program because it was looked at would be starting things implicitly.
   */
  const check = useCallback(async () => {
    setAsking(true);
    setRefused("");
    try {
      const answer = await mcpProbe(project, node.id);
      setProbe(answer);
      onProbed(answer);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    } finally {
      setAsking(false);
    }
  }, [project, node.id, onProbed]);

  // Only while a browser is open. The offset-less twin of every other poll here: what is
  // being waited for is a person, and the core answers `running` until they are done.
  useEffect(() => {
    if (!auth?.running || polling.current) return;
    polling.current = true;
    const timer = window.setInterval(async () => {
      try {
        const answer = await mcpAuthorized(project, node.id);
        if (!answer.running) {
          window.clearInterval(timer);
          polling.current = false;
          setAuth(answer);
          void read();
          // A token that was just written is worth proving. The tick that follows is the
          // server's answer, not the exchange's — those are different claims.
          if (answer.ok) void check();
        }
      } catch {
        window.clearInterval(timer);
        polling.current = false;
      }
    }, 900);
    return () => {
      window.clearInterval(timer);
      polling.current = false;
    };
  }, [auth, project, node.id, read, check]);

  const connect = async () => {
    setBusy(true);
    setRefused("");
    try {
      const answer = await mcpConnect(project, node.id);
      if (!answer.ok) {
        setRefused(answer.detail);
        return;
      }
      if (server?.transport === "http") {
        setAuth(await mcpAuthorized(project, node.id));
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

  const store = async (field: string, value: string) => {
    setRefused("");
    try {
      const answer = await mcpSecret(project, node.id, field, value);
      // The entry re-read: which keys are set now comes from the file, never from this
      // panel's memory of what it just sent.
      setServer(answer);
      setDrafts((held) => ({ ...held, [field]: "" }));
      if (!answer.ok) setRefused(answer.detail);
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  };

  if (!server) {
    return refused ? <div className="bp-node-why">{refused}</div> : null;
  }

  const http = server.transport === "http";

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

        {http ? (
          <pre className="bp-run-json">{server.url}</pre>
        ) : server.command ? (
          <pre className="bp-run-json">{[server.command, ...server.args].join(" ")}</pre>
        ) : (
          <div className="bp-node-why">
            {`${server.name} declares neither a command nor a url.`}
          </div>
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

      {/* What the server itself said. Absent until somebody asked: a state nobody checked is
          drawn as nothing, never as `not connected` — those are different claims. */}
      <div className="bp-run">
        <span className="bp-node-label">What it offers</span>
        {probe ? (
          <>
            <div className={`bp-status is-${probe.connected ? "reachable" : "unreachable"}`}>
              <span className="bp-status-dot" />
              {probe.connected
                ? `connected · ${probe.tools.length} tool${probe.tools.length === 1 ? "" : "s"}`
                : "not connected"}
            </div>
            <div className="bp-node-when">
              {probe.detail}
              {probe.server ? ` · ${probe.server}` : ""}
            </div>
            {/* Named rather than counted, for the reason the tests behind a verdict are:
                a number is a claim, and the names are what a person recognises it by.
                **Nothing here can call one of them.** */}
            {probe.tools.length > 0 ? (
              <div className="bp-run-docs">
                {probe.tools.map((tool) => (
                  <code key={tool}>{tool}</code>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <div className="bp-node-quiet">nothing has been asked yet</div>
        )}
        <button
          className="bp-run-second"
          disabled={asking || !server.transport}
          onClick={() => void check()}
        >
          {asking ? "Asking…" : "Check"}
        </button>
        <div className="bp-run-note">
          Starts the server and asks it for its tools, then stops it again.
        </div>
      </div>

      {/* Path one. The credentials are the person's own, registered in the provider's own
          console — there is no Framestack OAuth app and there will not be one. */}
      {http ? (
        <div className="bp-run">
          <span className="bp-node-label">Authorisation</span>
          {CREDENTIALS.map(({ field, label }, index) => {
            const key = server.keys[index] ?? "";
            const set = server.given.includes(key);
            return (
              <label className="bp-compose-field" key={field}>
                <span className="bp-compose-key">
                  {label} · {key} {set ? "· set" : ""}
                </span>
                <input
                  className="bp-field"
                  type="password"
                  value={drafts[field] ?? ""}
                  spellCheck={false}
                  placeholder={set ? "•••••••• (replace)" : "paste it here"}
                  onChange={(event) =>
                    setDrafts((held) => ({ ...held, [field]: event.target.value }))
                  }
                  onBlur={() => {
                    const typed = drafts[field] ?? "";
                    if (typed) void store(field, typed);
                  }}
                />
              </label>
            );
          })}

          {auth?.running ? (
            <>
              <button className="bp-btn is-quiet" onClick={() => void mcpCancel(project, node.id)}>
                Stop waiting
              </button>
              <div className="bp-run-note">
                Waiting for the browser. Register <code>{auth.redirect}</code> as the redirect
                URL in the provider's console, or the callback has nowhere to land.
              </div>
            </>
          ) : (
            <>
              <button
                className="bp-run-go bp-run-wide"
                disabled={busy}
                onClick={() => void connect()}
              >
                {busy ? "Opening…" : `Connect ${server.name}`}
              </button>
              <div className="bp-run-note">
                Opens your browser on the provider's consent screen. The token is written to
                <code> .env</code>; <code>mcp.json</code> never holds a secret.
              </div>
            </>
          )}
          {auth && !auth.running && auth.at ? (
            <div className="bp-node-when">
              {auth.detail}
            </div>
          ) : null}
        </div>
      ) : server.command ? (
        <div className="bp-run">
          <span className="bp-node-label">Connect</span>
          <button className="bp-run-go bp-run-wide" disabled={busy} onClick={() => void connect()}>
            {busy ? "Starting…" : `Connect ${server.name}`}
          </button>
          <div className="bp-run-note">
            Runs the server's own command in the terminal. If it needs an account it opens a
            browser itself and keeps its own token — Framestack stores nothing.
          </div>
          {/* What we did, with a time on it. Never "connected": that word belongs to the
              probe above, which is the only thing here that asked the server anything. */}
          {ran ? <div className="bp-run-when">started at {ran}</div> : null}
        </div>
      ) : null}

      {refused ? <div className="bp-node-why">{refused}</div> : null}
    </>
  );
}
