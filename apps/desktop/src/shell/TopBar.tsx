/**
 * The top bar (P18.1): the project's name, a segmented tab group, and the control cluster.
 *
 * The reference's row, in its geometry and its weights, with three deliberate differences:
 *
 *   - **One tab.** `Workflow` `Export` `Analytics` `Manager` have no analogue here: the
 *     project *is* the export, there is nothing to analyse, and nothing to manage. The row
 *     still ships, because its geometry is the reference's and a second tab arrives the
 *     moment a deploy or a run history does. Inventing three to fill it would be drawing a
 *     product that does not exist.
 *   - **`Observe` is the black primary**, where the reference puts `Publish`. That
 *     placement is the argument of the whole product: the most emphatic button on the
 *     screen is the one that produces evidence, because evidence is the thing no competitor
 *     can print. The evidence dot sits beside it, as a statement *about that button* --
 *     this picture was earned by a run, or nothing has been run yet.
 *   - **No `Share` and no `Save`.** There is nothing to share; the project is a directory.
 *     And a knob write goes through `libcst` into the file the moment it is made, so a Save
 *     button would imply a buffer this application deliberately does not have.
 */

export function TopBar({
  name,
  observed,
  reading,
  running,
  servicesUp,
  onObserve,
  onRun,
  onEnv,
  onAgent,
  tab,
  onTab,
}: {
  name: string;
  observed: boolean;
  reading: boolean;
  /** The application's own process is alive. Asked on a clock, never assumed (P13). */
  running: boolean;
  /** Docker says the compose project's containers are up. A different claim (Q24). */
  servicesUp: boolean;
  onObserve: () => void;
  onRun: () => void;
  onEnv: () => void;
  onAgent: () => void;
  /** Which view is showing. Two now: how it is built, and how it is used. */
  tab: string;
  onTab: (tab: string) => void;
}) {
  return (
    <header className="bp-top">
      <span className="bp-top-name" title={name}>
        {name}
      </span>

      {/* The second tab, at last. It was drawn as a group of one on the promise that one
          would arrive "the moment a deploy or a run history does" -- what arrived instead
          is the other question a person has about a project: not how it is built, but how
          it is used. The row's geometry is unchanged. */}
      <div className="bp-seg" role="tablist" aria-label="Views">
        {["Graph", "Use"].map((name) => {
          const id = name.toLowerCase();
          return (
            <button
              key={id}
              className={`bp-seg-tab${tab === id ? " is-on" : ""}`}
              role="tab"
              aria-selected={tab === id}
              onClick={() => onTab(id)}
            >
              {name}
            </button>
          );
        })}
      </div>

      <div className="bp-cluster">
        {/* Quiet, and left of the rest: writing code is not a claim about the project the
            way the other three are. Named for what a person is about to do rather than for
            what is on the other end -- "Agent" is this application's word for its own
            machinery, and a button is labelled with the reader's verb, not ours. */}
        <button className="bp-btn is-quiet" onClick={onAgent}>
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
            <path
              d="M12 3.5 13.7 9l5.5 1.7-5.5 1.8L12 18l-1.7-5.5L4.8 10.7 10.3 9z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
          Ask AI
        </button>

        <button className={`bp-btn${servicesUp ? " is-live" : ""}`} onClick={onEnv}>
          {servicesUp ? "Env down" : "Env up"}
        </button>

        <button className={`bp-btn${running ? " is-live" : ""}`} onClick={onRun}>
          <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
            {running ? (
              <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
            ) : (
              <path d="M8 5.5 18 12 8 18.5z" fill="currentColor" />
            )}
          </svg>
          {running ? "Stop" : "Run"}
        </button>

        {/* Said as a fact about what has happened rather than as a state the project is
            in: "not observed" reads like a fault, and a project that has just been opened
            has nothing wrong with it -- nobody has run anything yet, which is different. */}
        <span
          className={`bp-evidence-dot${observed ? " is-on" : ""}`}
          title={
            observed
              ? "the project's tests were run for this picture"
              : "nothing has been run yet — Observe is where green comes from"
          }
        />

        <button className="bp-btn is-primary" onClick={onObserve} disabled={reading}>
          {reading ? "Observing…" : "Observe"}
        </button>
      </div>
    </header>
  );
}
