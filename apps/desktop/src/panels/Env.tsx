/**
 * The `.env` editor: the one place a secret may be typed in this application.
 *
 * It exists because of the rule it complements rather than in spite of it. A knob holds the
 * **name** of an environment variable and never its value (P15) -- `token_env`,
 * `GMAIL_MCP_CREDENTIALS` -- so that a write into the graph can never put somebody's key on
 * its way to git. That rule left the value itself with nowhere to go but a terminal, which
 * is a poor place to keep the one thing standing between a configured server and a working
 * one. This is that place, and it is deliberately *beside* the graph: nothing here is a
 * node, nothing here is parsed, and no check reads a value out of it.
 *
 * **A text box, not a key/value table.** The core does not parse this file (§5.8), so there
 * are no rows to draw -- and a table would have to decide what `export`, a quote and a
 * multi-line value mean, which is the reading program's decision and not ours.
 *
 * The two things it says out loud, because both are how a person loses a key:
 *
 *   - **whether git would carry the file**, asked of git rather than read out of
 *     `.gitignore`, with "nobody could tell" kept distinct from "it is safe";
 *   - **that a running process will not see the change**, because it was handed its
 *     environment when it was spawned. Saying so is this panel's job; restarting it would
 *     be an implicit start, and nothing here starts anything (P11).
 */

import { useCallback, useEffect, useState } from "react";

import { envReadFile, envWriteFile } from "../core/client";
import { Notice } from "./Notice";

export function Env({ project }: { project: string }) {
  const [text, setText] = useState("");
  /** What was last stored. A draft is "changed" only against this, never against "". */
  const [stored, setStored] = useState("");
  const [ignored, setIgnored] = useState<boolean | null>(null);
  const [existed, setExisted] = useState(false);
  const [busy, setBusy] = useState(true);
  const [said, setSaid] = useState<{ ok: boolean; detail: string } | null>(null);

  const read = useCallback(async () => {
    setBusy(true);
    try {
      const answer = await envReadFile(project);
      setText(answer.text);
      setStored(answer.text);
      setIgnored(answer.ignored);
      setExisted(answer.exists);
    } catch (error: unknown) {
      setSaid({ ok: false, detail: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }, [project]);

  useEffect(() => {
    void read();
  }, [read]);

  const dirty = text !== stored;

  const save = useCallback(async () => {
    setBusy(true);
    try {
      const answer = await envWriteFile(project, text);
      setSaid({ ok: answer.ok, detail: answer.detail });
      if (answer.ok) {
        setStored(text);
        setExisted(true);
      }
    } catch (error: unknown) {
      setSaid({ ok: false, detail: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }, [project, text]);

  return (
    <div className="bp-env">
      <div className="bp-env-head">
        <code className="bp-env-path">.env</code>
        {/* Three states and three sentences. `null` is not folded into "not ignored":
            one of them means the key is about to be committed and the other means nobody
            asked, and a person deciding whether to paste a key needs them apart. */}
        {ignored === true ? (
          <span className="bp-env-tag is-safe">git ignores this file</span>
        ) : ignored === false ? (
          <span className="bp-env-tag is-warn">git would commit this file</span>
        ) : (
          <span className="bp-env-tag">not a git repository — nothing checked</span>
        )}
      </div>

      <p className="bp-env-why">
        Values live here, never in a knob: a knob holds the <em>name</em> of a variable
        (<code>token_env</code>), so nothing the graph writes can carry a secret.
      </p>

      {/* **The one thing a person will otherwise get wrong.** The builder does not parse
          this file and does not hand it to anything it runs -- deliberately: the deployed
          application reads its own environment, and a run gathered under variables the
          deployment cannot reproduce would be evidence about a different program (I-5). So
          the project loads it, the same way it will in production. Saying this here is the
          only place it can be said, because not parsing the file also means not being able
          to check which of its variables ever arrive. */}
      <p className="bp-env-why">
        <b>The project loads this file, not the builder.</b> Use{" "}
        <code>SettingsConfigDict(env_file=".env")</code> or <code>load_dotenv()</code> —
        without one of them nothing here reaches a run, and a missing credential surfaces
        as a timeout somewhere else.
      </p>

      <textarea
        className="bp-env-text"
        value={text}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        placeholder={busy ? "" : "GMAIL_MCP_CREDENTIALS=/path/to/credentials.json"}
        onChange={(event) => setText(event.target.value)}
        aria-label="Environment file"
      />

      <div className="bp-env-acts">
        <button className="bp-btn bp-btn-go" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? "…" : "Save"}
        </button>
        <button className="bp-btn" disabled={busy || !dirty} onClick={() => setText(stored)}>
          Revert
        </button>
        {/* Stated always, not only after a save: a person reading this panel while a server
            is up needs to know that what they are looking at is not what it is running. */}
        <span className="bp-env-note">
          A process already running keeps the environment it started with.
        </span>
      </div>

      {!existed && !dirty ? (
        <div className="bp-env-note">No <code>.env</code> yet — saving creates one.</div>
      ) : null}

      {said ? (
        <Notice
          tone={said.ok ? "said" : "failed"}
          text={said.detail}
          onClose={() => setSaid(null)}
        />
      ) : null}
    </div>
  );
}
