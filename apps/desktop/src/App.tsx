/**
 * Shell layout: a status strip that reports the bridge, and the graph canvas.
 *
 * The status strip is scaffolding with a purpose -- it is the visible proof that
 * the Rust shell reached the Python core. It goes away once the graph itself is
 * evidence of that.
 */

import { useEffect, useState } from "react";

import { GraphCanvas } from "./graph/GraphCanvas";
import { ping, type PingResult } from "./core/client";

type BridgeState =
  | { status: "connecting" }
  | { status: "ok"; info: PingResult }
  | { status: "failed"; message: string };

export default function App() {
  const [bridge, setBridge] = useState<BridgeState>({ status: "connecting" });

  useEffect(() => {
    let cancelled = false;

    ping("hello from the webview")
      .then((info) => {
        if (!cancelled) setBridge({ status: "ok", info });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBridge({
            status: "failed",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="app">
      <header className="status" data-state={bridge.status}>
        <span className="dot" aria-hidden="true" />
        <span className="status-text">
          {bridge.status === "connecting" && "connecting to core…"}
          {bridge.status === "ok" &&
            `core online — python ${bridge.info.python}, libcst ${bridge.info.libcst}, protocol v${bridge.info.protocol_version}`}
          {bridge.status === "failed" && `core unreachable — ${bridge.message}`}
        </span>
      </header>

      <main className="canvas">
        <GraphCanvas />
      </main>
    </div>
  );
}
