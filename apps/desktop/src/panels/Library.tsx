/**
 * The library: what this builder can prove, listed (P19).
 *
 * The complaint it answers is that the boundary was invisible. `kinds.REGISTRY` **is** the
 * boundary -- twenty-seven kinds, and everything outside them is unprovable by construction
 * (Q8) -- and until now nothing had ever shown it to anybody. A person who has never opened
 * `kinds.py` should be able to read this panel and say what the tool can do.
 *
 * **It holds no list of its own.** Every family, every kind, every description and every
 * check comes from `graph.kinds`; the families arrive in the registry's own order and the
 * only thing written down here is how a family's name is *spelled* for a reader, with the
 * raw name as the fallback. That matters more than it looks: the first version of this
 * panel had seven families hard-coded, and `db` and `vector` were simply missing from it --
 * a kind can be added to the registry and quietly appear nowhere, which is the exact
 * failure a library exists to make impossible.
 *
 * **Nothing is insertable yet.** An entry is a description; P20 is what makes one carry
 * code. This is the honest intermediate state, and it is already the answer to "what can I
 * build here".
 */

import { useEffect, useState } from "react";

import { agentBlueprints, blueprintInsert, blueprintPlan } from "../core/client";
import { kindRegistry } from "../core/registry";
import type { BlueprintEntry, BlueprintPlan, NodeKindInfo } from "../core/types";
import { Notice } from "./Notice";
import { GLYPHS } from "../graph/kinds";

/**
 * How a family's name is spelled for a reader.
 *
 * Presentation and nothing else, with the registry's own name as the fallback -- so a
 * family nobody has written a caption for still appears, under the name the code uses.
 * A missing entry costs a nicer word; it can never cost a kind.
 */
const SPOKEN: Record<string, string> = {
  fastapi: "FastAPI",
  langgraph: "LangGraph",
  rag: "RAG",
  db: "Database",
  vector: "Vector store",
  queue: "Background work",
  mcp: "MCP",
  docker: "Infrastructure",
};

/** What a kind hangs on, said in words rather than in the enum's own vocabulary (I-3). */
function carriedBy(kind: NodeKindInfo): string {
  if (kind.artifact.length > 0) return kind.artifact.join(" · ");
  return kind.carriers.join(" or ");
}

/** Every verb the registry says this kind has. Read off it, never listed here (§5.6). */
function verbsOf(kind: NodeKindInfo): string[] {
  const verbs: string[] = [];
  if (kind.starts) verbs.push(`${kind.starts}.start / stop`);
  if (kind.converses) verbs.push(kind.converses);
  if (kind.indexes) verbs.push(kind.indexes);
  return verbs;
}

function Entry({ kind }: { kind: NodeKindInfo }) {
  return (
    <div className="bp-lib-row">
      <svg className="bp-lib-glyph" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
        <path
          d={GLYPHS[kind.family] ?? GLYPHS.none}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="bp-lib-body">
        <div className="bp-lib-name">
          {kind.name}
          {kind.top_level ? <span className="bp-lib-flag">top level</span> : null}
        </div>
        <div className="bp-lib-desc">{kind.description}</div>
        {/* The two facts that make this a boundary rather than a menu: what has to exist
            for the node to exist, and what will be run to prove it works. A kind whose
            check nobody can satisfy is a kind you cannot build, and saying so here is
            cheaper than finding out from a grey node. */}
        <div className="bp-lib-facts">
          <span className="bp-chip is-quiet">carried by {carriedBy(kind)}</span>
          <span className="bp-chip is-quiet">proven by {kind.check}</span>
          {verbsOf(kind).map((verb) => (
            <span className="bp-chip is-quiet" key={verb}>
              {verb}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * One catalog entry, and the button that inserts it.
 *
 * **Which entries ask first is decided by where they came from** (Q28.2). A bundled entry
 * inserts without a dialog, because the trust decision was made once, at install, and
 * confirming per entry what was already confirmed per catalog is friction that trains people
 * to click through. A named one -- a stranger's Python from a path this person passed in --
 * shows every file and every import and waits.
 *
 * Both take the same path through the core: plan, then insert with the plan's identity. What
 * differs is whether a person saw the plan, which is a question about this component and not
 * about what is written.
 */
function Blueprint({
  entry,
  project,
  onInserted,
}: {
  entry: BlueprintEntry;
  project: string;
  onInserted: () => void;
}) {
  const [plan, setPlan] = useState<BlueprintPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<string | null>(null);

  const insertable = entry.carries_code > 0 && project !== "";

  async function write(identity: string) {
    setBusy(true);
    try {
      const done = await blueprintInsert(project, entry.id, identity);
      setSaid(
        done.inserted
          ? `inserted ${done.files.length} file(s) — nothing is green until something runs it`
          : (done.refused ?? "the insert was refused"),
      );
      setPlan(null);
      if (done.inserted) onInserted();
    } catch (error) {
      setSaid(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function begin() {
    setBusy(true);
    setSaid(null);
    try {
      const asked = await blueprintPlan(project, entry.id);
      if (asked.refused) {
        setSaid(asked.refused);
      } else if (asked.origin === "bundled") {
        await write(asked.identity);
      } else {
        setPlan(asked);
      }
    } catch (error) {
      setSaid(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="bp-lib-row">
        <svg className="bp-lib-glyph" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path
            d="M4 5h16v14H4zM4 9h16M9 9v10"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinejoin="round"
          />
        </svg>
        <div className="bp-lib-body">
          <div className="bp-lib-name">{entry.title}</div>
          <div className="bp-lib-desc">{entry.summary}</div>
          <div className="bp-lib-facts">
            <span className="bp-chip is-quiet">{entry.origin}</span>
            {entry.carries_code > 0 ? (
              <span className="bp-chip is-quiet">{entry.carries_code} files</span>
            ) : (
              // An entry with no code is specification text the agent is handed, which is
              // what every entry was before P20. The two kinds live side by side.
              <span className="bp-chip is-quiet">text only</span>
            )}
          </div>
          {said ? <div className="bp-block-note">{said}</div> : null}
        </div>
        {insertable ? (
          <button className="bp-btn bp-btn-slim" disabled={busy} onClick={() => void begin()}>
            {busy ? "…" : "Insert"}
          </button>
        ) : null}
      </div>

      {plan ? (
        <Diff plan={plan} busy={busy} onAccept={() => void write(plan.identity)} onClose={() => setPlan(null)} />
      ) : null}
    </>
  );
}

/**
 * The diff a third-party entry shows before anything is written.
 *
 * Every file with its **full contents**, because a person deciding whether to accept a
 * stranger's code is owed the code and not a list of filenames -- and the imports beside
 * them, as a line of facts. That summary is deliberately **not** a verdict: an allowlist or
 * a scanner here would be bypassed by anyone who wanted to and would read as a guarantee to
 * everyone who did not (Q28.4). Nobody vouches for this, and saying so plainly is the
 * honest thing this dialog can do.
 */
function Diff({
  plan,
  busy,
  onAccept,
  onClose,
}: {
  plan: BlueprintPlan;
  busy: boolean;
  onAccept: () => void;
  onClose: () => void;
}) {
  return (
    <div className="bp-modal-scrim" onClick={onClose}>
      <div className="bp-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="bp-dialog-head">
          <span className="bp-dialog-title">Insert {plan.title}</span>
          <button className="bp-icon" onClick={onClose} title="Close">
            ✕
          </button>
        </div>

        <p className="bp-inspector-desc">
          {plan.files.length} file(s) from a catalog you named. Nobody vouches for this code —
          it arrives inert, nothing here runs it, and the first execution is a press you make.
        </p>

        {plan.imports.length > 0 ? (
          <div className="bp-lib-facts">
            {plan.imports.map((name) => (
              <span
                key={name}
                className={`bp-chip${plan.requires.includes(name) ? "" : " is-quiet"}`}
              >
                {name}
                {plan.requires.includes(name) ? " — not installed" : ""}
              </span>
            ))}
          </div>
        ) : null}

        {plan.collisions.length > 0 ? (
          <Notice
            tone="refused"
            label="in the way"
            text={`already in this project: ${plan.collisions.join(", ")}`}
            onClose={onClose}
          />
        ) : null}

        {plan.files.map((file) => (
          <div className="bp-diff" key={file.path}>
            <div className="bp-diff-path">{file.path}</div>
            <pre className="bp-src">{file.contents}</pre>
          </div>
        ))}

        <div className="bp-modal-acts">
          <button className="bp-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="bp-btn is-primary"
            disabled={busy || plan.collisions.length > 0}
            onClick={onAccept}
          >
            Insert
          </button>
        </div>
      </div>
    </div>
  );
}

export function Library({
  project,
  onInserted,
}: {
  project: string;
  /** An insert wrote files, so what is on the canvas is a claim about older code. */
  onInserted: () => void;
}) {
  const [kinds, setKinds] = useState<NodeKindInfo[] | null>(null);
  const [families, setFamilies] = useState<string[]>([]);
  const [blueprints, setBlueprints] = useState<BlueprintEntry[]>([]);
  const [catalog, setCatalog] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    void kindRegistry()
      .then((answer) => {
        setKinds(answer.kinds);
        setFamilies(answer.families);
      })
      .catch(() => setKinds([]));
    // A catalog that is not configured answers `null`, which is a normal answer: input B is
    // unavailable and nothing about that is an error (§3). So a failure here costs the
    // blueprint section and nothing else.
    void agentBlueprints()
      .then((answer) => {
        setCatalog(answer.catalog);
        setBlueprints(answer.blueprints);
      })
      .catch(() => undefined);
  }, []);

  const needle = query.trim().toLowerCase();
  // Searched across everything the row shows, so what a person can read is what they can
  // find: the kind, what it is for, what carries it, and what proves it.
  const matches = (kind: NodeKindInfo) =>
    !needle ||
    [kind.name, kind.description, kind.check, carriedBy(kind), SPOKEN[kind.family] ?? kind.family]
      .join(" ")
      .toLowerCase()
      .includes(needle);

  const shown = (kinds ?? []).filter(matches);
  const shownBlueprints = blueprints.filter(
    (entry) =>
      !needle ||
      `${entry.title} ${entry.summary} ${entry.section}`.toLowerCase().includes(needle),
  );

  return (
    <div className="bp-library">
      <input
        className="bp-search"
        placeholder="Search the library"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {kinds === null ? <div className="bp-empty">Reading the registry…</div> : null}

      {kinds !== null && shown.length === 0 && shownBlueprints.length === 0 ? (
        <div className="bp-empty">Nothing here matches “{query}”.</div>
      ) : null}

      {families.map((family) => {
        const entries = shown.filter((kind) => kind.family === family);
        if (entries.length === 0) return null;
        return (
          <div className="bp-lib-group" key={family}>
            <div className="bp-lib-head">
              <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
                <path
                  d={GLYPHS[family] ?? GLYPHS.none}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {SPOKEN[family] ?? family}
              <span className="bp-lib-n">{entries.length}</span>
            </div>
            {entries.map((kind) => (
              <Entry kind={kind} key={kind.name} />
            ))}
          </div>
        );
      })}

      {/* A catalog is named, never found: it comes from `FRAMESTACK_BLUEPRINTS` or from a
          caller, and with neither there is simply no section here. What this tool offers
          must not depend on the shape of somebody's disk. */}
      {shownBlueprints.length > 0 ? (
        <div className="bp-lib-group">
          <div className="bp-lib-head">
            Blueprints
            <span className="bp-lib-n">{shownBlueprints.length}</span>
          </div>
          {shownBlueprints.map((entry) => (
            <Blueprint
              entry={entry}
              project={project}
              onInserted={onInserted}
              key={entry.id}
            />
          ))}
          {catalog ? <div className="bp-lib-note">from {catalog}</div> : null}
        </div>
      ) : null}

      {kinds !== null && !needle ? (
        <div className="bp-lib-note">
          This is the whole of what the builder can prove: a kind outside this list has no
          observable check, so a node of it could never be more than unproven. The agent
          writes the code; the registry is what decides whether anything can be said about
          it afterwards.
        </div>
      ) : null}
    </div>
  );
}
