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

import { agentBlueprints } from "../core/client";
import { kindRegistry } from "../core/registry";
import type { BlueprintEntry, NodeKindInfo } from "../core/types";
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

function Blueprint({ entry }: { entry: BlueprintEntry }) {
  return (
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
          <span className="bp-chip is-quiet">{entry.section}</span>
        </div>
      </div>
    </div>
  );
}

export function Library() {
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
            <Blueprint entry={entry} key={entry.id} />
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
