/**
 * The node library, behind `+` on the rail (P18.2).
 *
 * The reference keeps no permanent library column: it is a searchable panel opened from the
 * rail, and closing it gives the canvas back. Same here -- a search field at the top,
 * entries grouped by family below, each a row with its glyph, its name and one line of what
 * it is.
 *
 * **It ships empty on purpose.** This phase draws the shell; P19 fills it from
 * `kinds.REGISTRY`, and P20 makes an entry insertable. It has to be present now because the
 * layout cannot be judged with a hole in it -- and it is empty rather than stocked with a
 * hand-written list, because a list of kinds spelled out in the front end would be a second
 * opinion about the registry and would go stale the first time somebody added one.
 *
 * The families are named here and nothing else is. That is the shape of the answer P19
 * pours into, not the answer.
 */

import { useState } from "react";

import { GLYPHS } from "../graph/kinds";

/** The groups the reference's own library is organised into, in our vocabulary. */
const FAMILIES: { id: string; label: string }[] = [
  { id: "fastapi", label: "FastAPI" },
  { id: "langgraph", label: "LangGraph" },
  { id: "rag", label: "RAG" },
  { id: "mcp", label: "MCP" },
  { id: "queue", label: "Background work" },
  { id: "db", label: "Persistence" },
  { id: "docker", label: "Infrastructure" },
];

export function Library() {
  const [query, setQuery] = useState("");
  const shown = FAMILIES.filter((family) =>
    family.label.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="bp-library">
      <input
        className="bp-search"
        placeholder="Search the library"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {shown.map((family) => (
        <div className="bp-lib-group" key={family.id}>
          <div className="bp-lib-head">
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
              <path
                d={GLYPHS[family.id] ?? GLYPHS.none}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {family.label}
          </div>
          <div className="bp-lib-empty">no entries yet</div>
        </div>
      ))}

      {/* Said once, at the bottom, rather than seven times in the groups above. What is
          missing here is the catalog, and where it comes from is a fact worth stating --
          an empty panel that explains nothing reads as a panel that is broken. */}
      <div className="bp-lib-note">
        The library is a view of the kind registry — what this toolchain can actually prove.
        Until it is wired up, code is written by the agent, which is the path that has never
        had a boundary.
      </div>
    </div>
  );
}
