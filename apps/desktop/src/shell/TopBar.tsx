/**
 * The top bar: the project's name and the control cluster.
 *
 * The reference's row, in its geometry and its weights, with three deliberate differences:
 *
 *   - **No tabs.** There are two surfaces and one of them is a panel, so a tab group would
 *     be a control with one option. The row that held `Graph` / `Use` went with the `Use`
 *     tab it was drawn for.
 *   - **`Observe` is the black primary**, where the reference puts `Publish`. That
 *     placement is the argument of the whole product: the most emphatic button on the
 *     screen is the one that produces evidence, because evidence is the thing no competitor
 *     can print. The evidence dot sits beside it, as a statement *about that button* --
 *     this picture was earned by a run, or nothing has been run yet.
 *   - **No `Share` and no `Save`.** There is nothing to share; the project is a directory.
 *     And a settings write goes through `libcst` into the file the moment it is made, so a
 *     Save button would imply a buffer this application deliberately does not have.
 *
 * The buttons arrive with the capability behind them. `Observe` is here because the core can
 * answer for it; `Run` and `Deploy` come with Phase 5. Drawing one before the core can answer
 * for it would be a control whose only possible outcome is an error.
 */

export function TopBar({
  name,
  onAgent,
  onObserve,
  observing,
  observed,
}: {
  name: string;
  onAgent: () => void;
  onObserve: () => void;
  observing: boolean;
  /** Has anything been run here? Not whether it passed — that is the graph's to say. */
  observed: boolean;
}) {
  return (
    <header className="bp-top">
      {/* The product's own name, in the window as well as on it. The native title is what
          macOS shows when a person hovers the window in Mission Control or the Dock, and it
          is hidden in the title bar because the bar is transparent -- so without this the
          application never says what it is anywhere a person is actually looking. It is a
          label and never a button: there is nothing above the project to navigate to. */}
      <span className="bp-top-product" title="Framestack AI Builder">
        Framestack AI Builder
      </span>
      <span className="bp-top-sep" aria-hidden="true" />

      <span className="bp-top-name" title={name}>
        {name}
      </span>

      <div className="bp-cluster">
        {/* Quiet, and left of where the commands will be: writing code is not a claim about
            the project the way running it is. Named for what a person is about to do rather
            than for what is on the other end -- "Agent" is this application's word for its
            own machinery, and a button is labelled with the reader's verb, not ours. */}
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

        {/* A statement about the button beside it: this picture was earned by a run, or
            nothing has been run yet. It says *whether*, never *how it went* — the graph is
            where a colour belongs, and a green dot up here would be a second verdict with
            no node attached to it. */}
        <span
          className={`bp-evidence-dot${observed ? " is-on" : ""}`}
          title={observed ? "these colours came from a run" : "nothing has been run here yet"}
        />

        {/* The black primary, where the reference puts `Publish`. That placement is the
            argument of the whole product: the most emphatic button on the screen is the one
            that produces evidence, because evidence is the thing no competitor can print. */}
        <button
          className="bp-btn is-primary"
          onClick={onObserve}
          disabled={observing}
          title="Run this project's tests and colour the graph from what happened"
        >
          {observing ? "Observing…" : "Observe"}
        </button>
      </div>
    </header>
  );
}
