/**
 * Which model this node reaches, said once instead of three times.
 *
 * The objection this answers is a fair one: if Ollama was declared in the providers panel,
 * why does every node repeat its URL and its key variable? The answer is that **the node's
 * knobs are what the deployed application reads**, and the providers list is builder state
 * in `.framestack/` that no deployment will ever see. A node that named a provider instead
 * of an endpoint would run here and fail on a server -- which is the independence this
 * project was asked for in the first place. So the duplication is not in the code; it was
 * in the *presentation*, and that is what this fixes: one control, three writes, through
 * `knob.set` like any other knob.
 *
 * **The three fields do not disappear, they move.** A knob is a value in someone's source
 * and a person has to be able to see and type it -- a model pulled yesterday is in no list,
 * and a project whose code already names an endpoint must not be unreadable here. So they
 * are under `Advanced`, one disclosure away, and nothing about them is hidden from a write.
 *
 * Only the knobs the node declares are written. A stage with a `model` and nothing else is
 * pointed at a model and left alone otherwise -- a knob exists because the code declared it
 * (I-1), and this panel writes values, never declarations.
 */

import { useState } from "react";

import type { GraphNode, Knob, Provider } from "../core/types";
import { KnobBlock, literal } from "./Knob";

const MODEL = "model";
const BASE_URL = "base_url";
const KEY_ENV = "api_key_env";

/** The three this control owns. Everything else stays in the ordinary knob list. */
export const MODEL_KNOBS = [MODEL, BASE_URL, KEY_ENV];

/** Does this node name a model at all? Nothing here applies when it does not. */
export function namesAModel(node: GraphNode): boolean {
  return node.knobs.some((knob) => knob.name === MODEL);
}

/**
 * Which saved provider a node is already pointed at, if any.
 *
 * Matched on the endpoint, because that is the thing that decides where a call goes. A node
 * matching nothing is an ordinary state -- its code names an endpoint nobody saved -- and it
 * shows as `Not from the list`, never as an error.
 */
function providerOf(node: GraphNode, providers: Provider[]): Provider | null {
  const at = node.knobs.find((knob) => knob.name === BASE_URL);
  if (!at) return null;
  const url = literal(at).trim();
  return providers.find((one) => one.base_url.trim() === url) ?? null;
}

export function ModelPicker({
  node,
  providers,
  onKnob,
}: {
  node: GraphNode;
  providers: Provider[];
  onKnob: (node: string, knob: string, value: unknown) => void | Promise<void>;
}) {
  const [advanced, setAdvanced] = useState(false);
  const mine = node.knobs.filter((knob) => MODEL_KNOBS.includes(knob.name));
  const model = mine.find((knob) => knob.name === MODEL);
  const declared = new Set(mine.map((knob) => knob.name));
  const now = model ? literal(model) : "";
  const from = providerOf(node, providers);

  /** One gesture, up to three writes. The first refusal is reported by the inspector. */
  const point = async (provider: Provider, name: string) => {
    for (const [knob, value] of [
      [MODEL, name],
      [BASE_URL, provider.base_url],
      [KEY_ENV, provider.api_key_env],
    ] as const) {
      if (declared.has(knob)) await onKnob(node.id, knob, value);
    }
  };

  return (
    <div className="bp-model">
      <div className="bp-model-head">
        <span className="bp-block-label">Model</span>
        <span className="bp-model-now">
          {now || "not set"}
          {from ? ` · ${from.name}` : providers.length > 0 ? " · not from the list" : ""}
        </span>
      </div>

      {providers.length === 0 ? (
        <div className="bp-block-note">
          No providers saved. Add one in <b>Environment → Providers</b> and its models can be
          picked here.
        </div>
      ) : (
        providers.map((provider) => (
          <div key={provider.name} className="bp-model-provider">
            <div className="bp-model-provider-name">{provider.name}</div>
            <div className="bp-model-list">
              {provider.models.length === 0 ? (
                <span className="bp-block-note">no models listed</span>
              ) : (
                provider.models.map((one) => (
                  <button
                    key={one}
                    className={`bp-model-pick${
                      one === now && (from?.name === provider.name || !from) ? " is-on" : ""
                    }`}
                    onClick={() => void point(provider, one)}
                  >
                    {one}
                  </button>
                ))
              )}
            </div>
          </div>
        ))
      )}

      <button className="bp-model-more" onClick={() => setAdvanced((was) => !was)}>
        {advanced ? "Hide fields" : `Advanced — ${mine.length} field(s)`}
      </button>

      {/* The same `KnobBlock` the rest of the list uses: one control and one write verb,
          because the second write path is always the one that forgets to validate. */}
      {advanced
        ? mine.map((knob: Knob) => (
            <KnobBlock
              key={knob.name}
              knob={knob}
              // The saved models, offered on the field itself as well: somebody who opened
              // Advanced to type a variant of a model they have wants the list too.
              suggestions={knob.name === MODEL ? providers.flatMap((one) => one.models) : undefined}
              onChange={(value) => void onKnob(node.id, knob.name, value)}
            />
          ))
        : null}
    </div>
  );
}
