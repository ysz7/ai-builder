/**
 * Providers a person added, the models they hold, and pointing a node at one.
 *
 * **A list of options, never a list of facts.** What a node reaches is in the node's own
 * knobs, in code -- `model`, `base_url`, `api_key_env`, written through `knob.set` like any
 * other knob. This panel makes those three writable in one gesture instead of three, and it
 * is asked nothing else: no check reads it, no node exists because of it, nothing here can
 * be green, and deleting `.framestack/providers.json` leaves the graph byte for byte as it
 * was. That is the line between a convenience and the second source of truth I-1 forbids,
 * and it is a test in `test_providers.py` rather than an intention.
 *
 * **It suggests and never restricts.** A knob holding a model this store has never heard of
 * is an ordinary state -- the code is the truth, and a list that could contradict it would
 * be the beginning of a manifest. So a saved model is a shortcut to a value, and the value
 * stays editable.
 *
 * **Per node, and that is the point.** A provider is not an application-wide setting: an
 * agent may answer through a hosted API while a RAG stage embeds against a model on this
 * machine, so the list of what can be pointed somewhere is the graph's -- every node
 * carrying the three knobs -- and each is applied on its own.
 *
 * **The key never lands here.** A provider holds the *name* of an environment variable
 * (P15); the core refuses an entry carrying anything else, because `.framestack/` is a
 * directory in somebody's repository. The value is appended to `.env`, and a name already
 * present is left alone: rewriting a line would mean deciding what `export`, a quote and a
 * continuation mean in a file this toolchain deliberately does not parse (§5.8).
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  envReadFile,
  envWriteFile,
  knobSet,
  providersRead,
  providersWrite,
} from "../core/client";
import type { GraphNode, GraphRead, Provider } from "../core/types";
import { Notice } from "./Notice";

/** The three knobs the system prompt mandates for anything that calls a model. */
const MODEL = "model";
const BASE_URL = "base_url";
const KEY_ENV = "api_key_env";

/**
 * Well-known endpoints, offered when the add form opens. They decide nothing: every value
 * is visible and editable before anything is stored, and nothing remembers which was used.
 * That is why they may live here rather than in the registry -- unlike a node kind, a
 * provider is not something the core can prove anything about.
 */
const RECIPES: Provider[] = [
  {
    name: "Anthropic",
    base_url: "https://api.anthropic.com/v1/",
    api_key_env: "ANTHROPIC_API_KEY",
    models: ["claude-sonnet-4-5", "claude-haiku-4-5"],
  },
  {
    name: "OpenAI",
    base_url: "",
    api_key_env: "OPENAI_API_KEY",
    models: ["gpt-4o-mini", "text-embedding-3-small"],
  },
  {
    name: "OpenRouter",
    base_url: "https://openrouter.ai/api/v1",
    api_key_env: "OPENROUTER_API_KEY",
    models: ["anthropic/claude-sonnet-4.5"],
  },
  {
    name: "Ollama",
    base_url: "http://localhost:11434/v1",
    api_key_env: "",
    models: ["llama3.1", "nomic-embed-text"],
  },
  {
    name: "LM Studio",
    base_url: "http://localhost:1234/v1",
    api_key_env: "",
    models: ["local-model"],
  },
];

/** Does `.env` already carry this variable? A line starting with the name, nothing cleverer. */
function named(text: string, name: string): boolean {
  if (!name) return false;
  return text.split("\n").some((line) => line.trim().replace(/^export\s+/, "").startsWith(`${name}=`));
}

/**
 * The nodes this panel can act on: the ones that name a model.
 *
 * **`model` alone is enough, and demanding all three was wrong.** A stage that embeds
 * against a local store often declares nothing else -- there is no key and no endpoint to
 * name -- and requiring the full set hid exactly the nodes a person was trying to point at
 * Ollama. What is written is the intersection of what the provider says and what the node
 * declares: a knob that is not there is not invented, because a knob exists because the
 * code declared it (I-1) and this panel writes values, never declarations.
 */
function reachers(graph: GraphRead | null): GraphNode[] {
  if (!graph) return [];
  return graph.graph.nodes.filter((node) => node.knobs.some((knob) => knob.name === MODEL));
}

const BLANK: Provider = { name: "", base_url: "", api_key_env: "", models: [] };

export function Providers({
  project,
  graph,
  onWrote,
}: {
  project: string;
  graph: GraphRead | null;
  /** A knob landed, so the picture is stale. Re-read; never observe (I-5). */
  onWrote: () => void;
}) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [envText, setEnvText] = useState("");
  /** `{provider, model}` -- what would be written. Nothing is stored about this choice. */
  const [chosen, setChosen] = useState<{ provider: string; model: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<Provider>(BLANK);
  const [models, setModels] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; detail: string } | null>(null);

  const read = useCallback(async () => {
    try {
      const [saved, env] = await Promise.all([providersRead(project), envReadFile(project)]);
      setProviders(saved.providers);
      setEnvText(env.text);
    } catch (error: unknown) {
      setSaid({ ok: false, detail: error instanceof Error ? error.message : String(error) });
    }
  }, [project]);

  useEffect(() => {
    void read();
  }, [read]);

  const nodes = useMemo(() => reachers(graph), [graph]);
  const picked = providers.find((one) => one.name === chosen?.provider) ?? null;

  const store = useCallback(
    async (next: Provider[]) => {
      setBusy(true);
      try {
        const answer = await providersWrite(project, next);
        if (!answer.ok) {
          setSaid({ ok: false, detail: answer.detail });
          return false;
        }
        setProviders(next);
        // The `model` knob suggests from this list, and that copy lives in `App`. Telling
        // it to re-read is why a model saved here can be typed on a node a second later.
        onWrote();
        return true;
      } catch (error: unknown) {
        setSaid({ ok: false, detail: error instanceof Error ? error.message : String(error) });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [onWrote, project],
  );

  const add = useCallback(async () => {
    const entry: Provider = {
      name: draft.name.trim(),
      base_url: draft.base_url.trim(),
      api_key_env: draft.api_key_env.trim(),
      models: models
        .split(/[\n,]/)
        .map((one) => one.trim())
        .filter(Boolean),
    };
    if (!(await store([...providers.filter((one) => one.name !== entry.name), entry]))) return;

    // The key, if one was typed, goes next door -- appended, never spliced into. A name
    // already in the file is left alone: silently replacing a key is a bad way to find out
    // you had one.
    if (secret && entry.api_key_env && !named(envText, entry.api_key_env)) {
      const line = `${entry.api_key_env}=${secret}`;
      const next = envText && !envText.endsWith("\n") ? `${envText}\n${line}\n` : `${envText}${line}\n`;
      const answer = await envWriteFile(project, next);
      if (!answer.ok) setSaid({ ok: false, detail: answer.detail });
    }
    setAdding(false);
    setDraft(BLANK);
    setModels("");
    setSecret("");
    await read();
  }, [draft, envText, models, project, providers, read, secret, store]);

  const forget = useCallback(
    async (name: string) => {
      // Only the option goes away. Any node already pointed at it keeps its knobs, because
      // those are in code and this store has never been what they meant.
      if (chosen?.provider === name) setChosen(null);
      await store(providers.filter((one) => one.name !== name));
    },
    [chosen, providers, store],
  );

  const apply = useCallback(
    async (node: GraphNode) => {
      if (!picked || !chosen) return;
      setBusy(true);
      try {
        // Up to three writes, in order, and the first refusal stops the rest: a node left
        // with a new base URL and an old key name is a configuration nobody chose. Only the
        // knobs the node actually declares are written -- see `reachers`.
        const declared = new Set(node.knobs.map((knob) => knob.name));
        const writes = ([
          [MODEL, chosen.model],
          [BASE_URL, picked.base_url],
          [KEY_ENV, picked.api_key_env],
        ] as const).filter(([knob]) => declared.has(knob));
        for (const [knob, value] of writes) {
          const answer = await knobSet(project, node.id, knob, value);
          if (!answer.written) {
            setSaid({ ok: false, detail: answer.refused ?? `${knob} was refused` });
            return;
          }
        }
        setSaid({ ok: true, detail: `${node.title ?? node.id} → ${chosen.model} (${picked.name})` });
        onWrote();
      } catch (error: unknown) {
        setSaid({ ok: false, detail: error instanceof Error ? error.message : String(error) });
      } finally {
        setBusy(false);
      }
    },
    [chosen, onWrote, picked, project],
  );

  return (
    <div className="bp-prov">
      <div className="bp-prov-bar">
        <div className="bp-prov-head">Providers</div>
        <button className="bp-btn" onClick={() => setAdding((was) => !was)}>
          {adding ? "Cancel" : "+ Add"}
        </button>
      </div>

      {adding ? (
        <div className="bp-prov-add">
          <div className="bp-prov-tiles">
            {RECIPES.map((recipe) => (
              <button
                key={recipe.name}
                className="bp-prov-tile"
                onClick={() => {
                  setDraft(recipe);
                  setModels(recipe.models.join(", "));
                }}
              >
                {recipe.name}
              </button>
            ))}
          </div>
          <label className="bp-prov-field">
            <span>Name</span>
            <input
              value={draft.name}
              spellCheck={false}
              placeholder="Ollama"
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </label>
          <label className="bp-prov-field">
            <span>Base URL</span>
            <input
              value={draft.base_url}
              spellCheck={false}
              placeholder="empty for the provider default"
              onChange={(event) => setDraft({ ...draft, base_url: event.target.value })}
            />
          </label>
          <label className="bp-prov-field">
            <span>API key variable</span>
            <input
              value={draft.api_key_env}
              spellCheck={false}
              placeholder="empty for a local model"
              onChange={(event) => setDraft({ ...draft, api_key_env: event.target.value })}
            />
          </label>
          <label className="bp-prov-field">
            <span>Models</span>
            <input
              value={models}
              spellCheck={false}
              placeholder="llama3.1, nomic-embed-text"
              onChange={(event) => setModels(event.target.value)}
            />
          </label>
          {/* Typed here, stored in `.env`, and never in the provider: the core refuses an
              entry carrying a key, so this field has nowhere else it could go. */}
          {draft.api_key_env && !named(envText, draft.api_key_env) ? (
            <label className="bp-prov-field">
              <span>Key value — goes to .env, never here</span>
              <input
                type="password"
                value={secret}
                autoComplete="off"
                placeholder={`value for ${draft.api_key_env}`}
                onChange={(event) => setSecret(event.target.value)}
              />
            </label>
          ) : null}
          <button
            className="bp-btn bp-btn-go"
            disabled={busy || !draft.name.trim()}
            onClick={() => void add()}
          >
            Save provider
          </button>
        </div>
      ) : null}

      {providers.length === 0 && !adding ? (
        <p className="bp-prov-why">
          Nothing added yet. <b>+ Add</b> fills the fields for a known provider — or type any
          OpenAI-compatible endpoint.
        </p>
      ) : null}

      {providers.map((provider) => (
        <div key={provider.name} className="bp-prov-card">
          <div className="bp-prov-card-head">
            <b>{provider.name}</b>
            <button className="bp-prov-x" onClick={() => void forget(provider.name)}>
              Remove
            </button>
          </div>
          <div className="bp-prov-where">
            {provider.base_url || "the client's own default"}
            {provider.api_key_env ? (
              <>
                {" · "}
                <code>{provider.api_key_env}</code>
                <span className={named(envText, provider.api_key_env) ? "is-safe" : "is-warn"}>
                  {named(envText, provider.api_key_env) ? " in .env" : " not in .env"}
                </span>
              </>
            ) : (
              " · no key"
            )}
          </div>
          <div className="bp-prov-models">
            {provider.models.length === 0 ? (
              <span className="bp-prov-note">No models listed — add some to pick from.</span>
            ) : (
              provider.models.map((model) => (
                <button
                  key={model}
                  className={`bp-prov-model${
                    chosen?.provider === provider.name && chosen.model === model ? " is-on" : ""
                  }`}
                  onClick={() => setChosen({ provider: provider.name, model })}
                >
                  {model}
                </button>
              ))
            )}
          </div>
        </div>
      ))}

      <div className="bp-prov-nodes">
        <div className="bp-prov-head">Point a node at it</div>
        {!chosen ? (
          <p className="bp-prov-why">Pick a model above, then a node.</p>
        ) : nodes.length === 0 ? (
          <p className="bp-prov-why">
            No node in this project declares a <code>model</code> knob. Ask the agent for
            one — a node that names its provider in an import cannot be pointed anywhere from
            here, and adding the knob is a change to its code.
          </p>
        ) : (
          nodes.map((node) => {
            const now = node.knobs.find((knob) => knob.name === MODEL)?.default ?? "";
            const declared = new Set(node.knobs.map((knob) => knob.name));
            // Said rather than discovered afterwards: a node with no `api_key_env` keeps
            // reaching whatever its code reaches, and that is worth knowing before pressing.
            const partial = !declared.has(BASE_URL) || !declared.has(KEY_ENV);
            return (
              <div key={node.id} className="bp-prov-node">
                <div className="bp-prov-node-id">
                  <b>{node.title ?? node.id}</b>
                  <span>{partial ? `${now} · model only` : now}</span>
                </div>
                <button className="bp-btn" disabled={busy} onClick={() => void apply(node)}>
                  Apply
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* The sentence that keeps this panel honest, said where it is acted on. */}
      <p className="bp-prov-why">
        This list is a shortcut. What a node uses is the knob in its code — edit it there and
        nothing here disagrees.
      </p>

      {said ? (
        <Notice tone={said.ok ? "said" : "failed"} text={said.detail} onClose={() => setSaid(null)} />
      ) : null}
    </div>
  );
}
