/**
 * The agent, docked bottom right.
 *
 * **The transcript is not the point and stays folded.** What the agent does to the code shows
 * up on the canvas -- that is the whole idea of this product -- so at rest the dock is an
 * input, a send button, a way to attach files and a ring showing how full the conversation
 * is. One line of status appears above it while a turn is running; the transcript and the
 * conversations are behind the toggle, and it opens to full height because reading a
 * transcript through a letterbox is not reading.
 *
 * Nothing is pushed (P13): a turn in flight is polled with an offset the client keeps, and
 * the polling stops when the turn is done. A quiet session costs nothing.
 *
 * A blocked tool is the entire permission surface there is (Q17) -- the stream carries no
 * "may I?" to answer -- so it is surfaced rather than swallowed.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import {
  agentAccount,
  agentChoices,
  agentConfigure,
  agentForget,
  agentPoll,
  agentRename,
  agentSay,
  agentInterrupt,
  agentPermission,
  agentSession,
  agentSignIn,
  agentStart,
} from "../core/client";
import { Markdown } from "../code/markdown";
import { Menu } from "./Menu";
import type { Item, Placed } from "./Menu";
import { Step } from "./Step";
import { Notice } from "./Notice";
import { Question } from "./Question";
import type {
  Account,
  AgentChoices,
  AgentEvent,
  AgentSessionRef,
  Pasted,
} from "../core/client";

const POLL_MS = 700;

/**
 * How big each model's context window is.
 *
 * A fraction needs a denominator, and the denominator is a property of the model rather than
 * of the session -- it differs by a factor of five across models the agent may pick. So the
 * model is read from the stream (`poll.model`) and looked up here, rather than assumed: an
 * assumed 200k against a 1M model draws a ring five times too full, which is worse than no
 * ring, because it reads as a reason to compact when there is none.
 *
 * A model that is not in this table gets **no ring at all** -- the raw count is shown alone.
 * Not knowing the window is a fact about us, and inventing one would hide it.
 */
const WINDOWS: Record<string, number> = {
  "claude-opus-5": 1_000_000,
  "claude-sonnet-5": 1_000_000,
  "claude-fable-5": 1_000_000,
  "claude-haiku-4-5": 200_000,
};

function windowFor(model: string): number {
  if (!model) return 0;
  const exact = WINDOWS[model];
  if (exact) return exact;
  // Dated ids ("claude-haiku-4-5-20251001") name the same model as the alias they extend.
  const prefix = Object.keys(WINDOWS).find((name) => model.startsWith(name));
  return prefix ? WINDOWS[prefix] : 0;
}

/**
 * Is this event something a person asked to see?
 *
 * `done` carries `end_turn` -- a fact about the protocol, and the signal the poll loop stops
 * on. It is used, and it is not shown. `ready` is the session announcing itself, which the
 * status line under the field already says; printing it in the log as well left the panel
 * opening with a record of its own startup.
 *
 * Filtered here rather than in the core, deliberately: the events are the *core's* answer and
 * another reader may want every one of them. What a chat panel puts on screen is the panel's
 * decision.
 */
function worthShowing(event: AgentEvent): boolean {
  // `done` and `ready` are the protocol talking about itself. `delta` and `spending` are
  // read for the line being written and the number beside it -- they are used, and they are
  // not lines of the conversation, so they do not accumulate in it.
  return !["done", "ready", "delta", "spending"].includes(event.kind);
}

/**
 * The mark on a line shown before the core has confirmed it.
 *
 * What the person typed is true the moment they press send, so it is drawn at once. The core
 * then records it and replays it with the rest of the conversation -- which is what makes it
 * survive a switch between conversations -- and the two have to be the same line rather than
 * two of them.
 */
const PENDING = "pending";

/** What the person said, as a line of the transcript. Marked pending until the core has it. */
function yours(text: string): AgentEvent {
  return {
    kind: "you",
    text,
    file: "",
    detail: "",
    id: PENDING,
    tool: "",
    // A line the person typed asks nothing, so there is nothing here (Q37).
    questions: [],
    answer: "",
  };
}

function absorbTurns(
  previous: AgentEvent[],
  incoming: AgentEvent[],
): AgentEvent[] {
  const shown = incoming.filter(worthShowing);
  const confirmed = new Set(
    shown.filter((event) => event.kind === "you").map((event) => event.text),
  );
  const kept =
    confirmed.size === 0
      ? previous
      : previous.filter(
          (event) =>
            !(
              event.kind === "you" &&
              event.id === PENDING &&
              confirmed.has(event.text)
            ),
        );
  return [...kept, ...shown];
}

type Props = {
  project: string;
  onTouch: (files: string[]) => void;
  onSettled: () => void;
  /**
   * Words put into the field from elsewhere -- a repair the toolchain cannot carry out.
   * Placed in the draft and **never sent**: handing a request over is not the same as
   * deciding to make it, and the person still presses send.
   */
  handOver: string | null;
  onHandedOver: () => void;
  /**
   * A press of `Agent` in the control cluster, counted.
   *
   * A counter and not a boolean, because the question it answers is "has somebody just
   * asked for me again?" -- and a boolean that was already true says nothing the second
   * time. It unfolds the panel and never folds it: closing is the person's own verb.
   */
  summon: number;
};

/**
 * The mark on the sign-in row.
 *
 * A glyph of our own rather than a reproduction of somebody's logo: this application is not
 * Anthropic's, and wearing their mark would say it was. It reads as "the agent" here because
 * of where it sits, which is all it has to do.
 */
function Spark() {
  return (
    <svg
      className="bp-spark"
      viewBox="0 0 16 16"
      width="15"
      height="15"
      aria-hidden="true"
    >
      <path
        d="M8 1v14M1 8h14M3 3l10 10M13 3L3 13"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Chat({
  project,
  onTouch,
  onSettled,
  handOver,
  onHandedOver,
  summon,
}: Props) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AgentSessionRef[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [blocked, setBlocked] = useState<string | null>(null);
  /**
   * Which request is being answered right now, if any.
   *
   * **The turn is stopped on the answer** (Q21), so the press has to look pressed: without
   * this the buttons sit unchanged while the core writes the response and the agent picks
   * the work back up, and a button that looks unpressed gets pressed again.
   */
  const [answering, setAnswering] = useState<string | null>(null);
  /**
   * How long the turn in flight has been going, in seconds.
   *
   * **The one thing on this line that is guaranteed to move.** The status says what the
   * agent is doing, and a single long step -- creating a virtualenv, installing packages,
   * running a suite -- says the same words for a minute at a time. A person watching a line
   * that has not changed cannot tell working from hung, and starts pressing things. A second
   * hand answers that question without pretending to know more than we do: it is not
   * progress, it is proof of life.
   */
  const [elapsed, setElapsed] = useState(0);
  const [transcript, setTranscript] = useState<AgentEvent[]>([]);
  const [context, setContext] = useState(0);
  const [model, setModel] = useState("");
  /** A session is being opened right now. Nothing else may ask for one until it answers. */
  const [connecting, setConnecting] = useState(false);
  /** The conversation being renamed, if any. Its chip becomes a field while it is. */
  const [naming, setNaming] = useState<string | null>(null);
  /**
   * Whether anybody is signed in. **Only that** -- who they are lives in Settings, because an
   * email address above every turn is somebody's address on a screen they may be sharing, and
   * it is not something a person reads while talking to an agent.
   */
  const [who, setWho] = useState<Account | null>(null);
  const [menu, setMenu] = useState<Placed>(null);
  /** The agent's own running estimate of what this turn has cost. Zero between turns. */
  const [spending, setSpending] = useState(0);
  /**
   * What the agent says it can be asked to do.
   *
   * Kept rather than replaced on every answer: the list arrives with the session's `init`
   * and a poll that carried none says so with an empty list, which means "nothing new" and
   * not "there are none". A resumed session sends no `init` at all until its first turn.
   */
  const [commands, setCommands] = useState<string[]>([]);
  /** Which suggestion the arrow keys are on. Reset whenever the list changes. */
  const [picked, setPicked] = useState(0);
  /**
   * What a session may be set to, and what this one is set to.
   *
   * The choices are **asked of the core** rather than listed here: which flags the agent
   * honours is a fact about the agent, and one it accepts and then ignores (`manual`) is
   * exactly what a menu written from documentation gets wrong.
   */
  /**
   * Pictures pasted into the turn being written.
   *
   * They belong to the *message*, not to the conversation: they go when it is sent, the same
   * way the words in the field do. Held as base64 because that is what a clipboard hands
   * over -- there is no file on disk to point the agent at, and writing one to invent a path
   * would leave it behind on somebody's machine.
   */
  const [pasted, setPasted] = useState<Pasted[]>([]);
  const [choices, setChoices] = useState<AgentChoices | null>(null);
  const [settings, setSettings] = useState({
    model: "",
    effort: "",
    mode: "acceptEdits",
    // Asking is the arrangement; running without being asked is the opt-out, and it is
    // theirs to choose rather than ours to ship.
    commands: "",
  });
  /**
   * Questions asked while an answer was still being written.
   *
   * A turn is one at a time -- the agent is answering the last one -- so a second question
   * waits rather than being refused or silently dropped. It is shown in the transcript at
   * once, because it *was* said; what is pending is the asking, not the saying.
   */
  const queue = useRef<{ text: string; images: Pasted[] }[]>([]);
  // The poll loop is defined before the sender and has to reach it when a turn ends. A ref
  // rather than a dependency, so the two do not have to be rebuilt around each other.
  const deliverRef = useRef<
    ((text: string, images: Pasted[]) => Promise<void>) | null
  >(null);
  /**
   * The answer as it is being written.
   *
   * Held apart from the transcript rather than appended to it, because the complete
   * `assistant` message is what is authoritative: when it arrives this is dropped and the
   * message takes its place, so there is never a moment where both are on screen.
   */
  const [writing, setWriting] = useState("");
  const [musing, setMusing] = useState("");
  /**
   * Folded until it is asked for.
   *
   * It used to begin open, because the chat is how a project gets its first line of code and
   * a panel that begins folded is a feature a person has to already know about. What changed
   * is that `Agent` is now a button in the control cluster (P18.1), so it is no longer
   * something to discover -- and the canvas gets the whole window, which is the reference's
   * behaviour and the thing a permanently docked panel takes away.
   */
  const [open, setOpen] = useState(false);

  // Asked for from the cluster. It only ever unfolds: a press of `Agent` by somebody who
  // already has the panel open is not a request to close it.
  useEffect(() => {
    if (summon > 0) setOpen(true);
  }, [summon]);

  /**
   * The next message starts a new conversation.
   *
   * **A conversation is not created until something is said in it.** Opening the application
   * used to mean either an empty panel with a button on it, or a session spawned for a person
   * who had not yet decided to say anything -- and a session that was never spoken to does not
   * exist for the agent either (`--resume` on one answers "no conversation found"). So the
   * panel offers a conversation, and sending is what brings it into being.
   */
  const [unstarted, setUnstarted] = useState(true);
  const [busy, setBusy] = useState(false);

  const offset = useRef(0);
  /**
   * Whether a read of the stream is already in flight.
   *
   * **Two readers share this offset** -- the poll loop and the one that waits for a session
   * to announce itself -- and a turn sent into a session that is still opening starts both.
   * Both then ask from the same offset, both are handed the same events, and the person sees
   * their own question twice. The stream is read once at a time; the second caller is not
   * queued, because what it wanted is exactly what the first one is already fetching.
   */
  const reading = useRef(false);
  const timer = useRef<number | null>(null);
  const field = useRef<HTMLTextAreaElement | null>(null);
  const shell = useRef<HTMLDivElement | null>(null);
  const tail = useRef<HTMLDivElement | null>(null);

  /**
   * The conversation closes when attention goes elsewhere.
   *
   * `pointerdown` rather than `click`: a press that lands on the canvas should put the chat
   * away before the canvas does anything with it, so the two never happen in the wrong order.
   * The listener exists only while the panel is open -- a document listener kept alive for a
   * closed panel is a handler that runs on every press in the application for no reason.
   */
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        shell.current &&
        !shell.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  /**
   * Follow the newest line — **unless the person is reading something else.**
   *
   * The newest line is usually the one being waited for, so the view follows it. But an
   * agent writing while somebody scrolls back is the one case where following is wrong:
   * every new line yanked them to the bottom, mid-sentence, and there was no way to read
   * what happened two minutes ago without stopping the agent first.
   *
   * "At the bottom" is a few pixels of tolerance rather than an exact match, because a log
   * that grows while it is measured is never exactly at its end.
   */
  const following = useRef(true);

  useEffect(() => {
    const log = tail.current;
    if (log && following.current) log.scrollTop = log.scrollHeight;
  }, [transcript, status, writing, musing]);

  /**
   * Opening lands at the newest line.
   *
   * A panel that comes back is a person returning to a conversation, and what they left off
   * at is the end of it -- an unfolded log that starts at the top shows them a greeting from
   * an hour ago. The log is mounted fresh at scroll position zero, which is also why this is
   * its own effect: nothing in the transcript changed, so the effect that follows it does
   * not run, and the first `onScroll` at position zero would otherwise read as "reading
   * something else" and switch following off for good.
   */
  useEffect(() => {
    if (!open) return;
    following.current = true;
    const log = tail.current;
    if (log) log.scrollTop = log.scrollHeight;
    // **Opening only**, not every new line: including the transcript here would switch
    // following back on with each arriving message, which is exactly the yanking that
    // scrolling up is supposed to stop. What arrives after this is handled by the effect
    // above, which is still following because this one said so.
  }, [open]);

  // A request handed over from the repair dialog lands in the field, focused and unsent.
  useEffect(() => {
    if (!handOver) return;
    setDraft((previous) => (previous ? `${previous}\n${handOver}` : handOver));
    setOpen(true);
    field.current?.focus();
    onHandedOver();
  }, [handOver, onHandedOver]);

  /**
   * Every call to the core, with its failure made visible.
   *
   * Without this a rejected request disappears into an unhandled promise and the panel shows
   * nothing at all -- which is how a button comes to be pressed seven times: the person is
   * not being stubborn, they are being told nothing. A refusal is an answer and has to look
   * like one.
   */
  const attempt = useCallback(
    async <T,>(work: () => Promise<T>): Promise<T | null> => {
      try {
        return await work();
      } catch (error) {
        setBlocked(error instanceof Error ? error.message : String(error));
        setBusy(false);
        setStatus("");
        stopPollingRef.current?.();
        return null;
      }
    },
    [],
  );

  const stopPollingRef = useRef<(() => void) | null>(null);

  const absorb = useCallback(
    (state: { session: string | null; sessions: AgentSessionRef[] }) => {
      setCurrent(state.session);
      setSessions(state.sessions);
    },
    [],
  );

  // Reset on every turn rather than accumulated: what a person wants to know is how long
  // *this* has been going, not how long the conversation has lasted.
  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const ticking = window.setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(ticking);
  }, [busy]);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);
  stopPollingRef.current = stopPolling;

  // Who is signed in is a fact about the machine, not about the project, so it is asked once
  // rather than on every project change. The same is true of what a session may be set to.
  useEffect(() => {
    void attempt(() => agentAccount()).then((told) => told && setWho(told));
    void attempt(() => agentChoices()).then((told) => told && setChoices(told));
  }, [attempt]);

  useEffect(() => {
    void attempt(async () => {
      const state = await agentSession(project);
      setAvailable(state.available);
      setRunning(state.running);
      // The list the last session here left behind, so `/` answers before the first turn.
      if (state.commands.length > 0) setCommands(state.commands);
      if (state.settings) setSettings(state.settings);
      absorb(state);
      return state;
    });
  }, [project, absorb, attempt]);

  const poll = useCallback(async () => {
    if (reading.current) return;
    reading.current = true;
    const from = offset.current;
    const answer = await attempt(() => agentPoll(project, from)).finally(() => {
      reading.current = false;
    });
    if (answer === null) return;
    offset.current = answer.offset;
    if (answer.context > 0) setContext(answer.context);
    if (answer.spending > 0) setSpending(answer.spending);
    if (answer.model) setModel(answer.model);
    // Empty means "no `init` in this chunk", not "the agent has no commands".
    if (answer.commands.length > 0) setCommands(answer.commands);
    absorb(answer);

    const touched = answer.events.map((event) => event.file).filter(Boolean);
    if (touched.length > 0) onTouch(touched);

    for (const event of answer.events) {
      // The working line says what the agent is *doing*, so only a tool call writes to it.
      // Letting `says` through put a whole answer on one line, and letting `ready` through
      // left the session's own startup sitting there for the rest of it.
      // A `blocked` carrying a `tool_use_id` is one tool's error, and it is drawn against
      // the call it answers -- the same rule the transcript applies below. Hoisting it here
      // as well put a bash exit code into the panel's alarm banner, stripped of the command
      // that produced it, where it then outlived the turn: what the banner is for is the
      // session failing, and a `blocked` with no id is the only one of those.
      if (event.kind === "blocked" && !event.id) setBlocked(event.text);
      else if (event.kind === "asking") {
        // Not an alarm and not work: the agent is stopped. The line says so, because a
        // panel that went on saying "thinking…" while nothing was happening is how a person
        // sits waiting for an answer that is waiting for them (Q21).
        setStatus("waiting for you");
        setWriting("");
        setMusing("");
      } else if (event.kind === "doing") setStatus(event.text);
      else if (event.kind === "delta") {
        if (event.detail === "thinking")
          setMusing((previous) => previous + event.text);
        else setWriting((previous) => previous + event.text);
      } else if (event.kind === "says") {
        // The whole message has arrived; what was accumulating for it is now a duplicate.
        setWriting("");
        setMusing("");
      }
    }
    // From the top means the whole conversation again, not more of it: appending a re-read
    // to what it re-read is how one question becomes two.
    setTranscript((previous) =>
      from === 0 ? answer.events.filter(worthShowing) : absorbTurns(previous, answer.events),
    );

    if (answer.events.some((event) => event.kind === "done")) {
      // The turn is over: stop asking, and read the graph again -- the agent has been
      // editing files, and everything on the canvas is a claim about older code.
      setBusy(false);
      setStatus("");
      setWriting("");
      setMusing("");
      setSpending(0);
      stopPolling();
      onSettled();
      // The turn is over, so the next question that was waiting can be asked. One at a
      // time, in the order they were typed.
      const next = queue.current.shift();
      if (next !== undefined) void deliverRef.current?.(next.text, next.images);
      return;
    }
    timer.current = window.setTimeout(() => void poll(), POLL_MS);
  }, [project, onTouch, onSettled, stopPolling, absorb, attempt]);

  useEffect(() => stopPolling, [stopPolling]);

  /**
   * Read the opening of a session, and stop.
   *
   * A **new** session writes its `init` line a moment after the process exists, so
   * `agent.start` returning is not the same as the agent having said anything -- and until it
   * does, the panel has no model for the context ring and nothing to show for the press.
   *
   * A **resumed** one announces nothing until it answers a turn. Measured, not assumed:
   * `agent.start` with `resume` returns in 0.6s and no `ready` arrives within twenty
   * seconds. So waiting for one is waiting for something that is not coming, and every
   * switch between conversations sat on "Connecting…" for the full timeout — which is the
   * whole of why switching felt slow. The core was never the slow part.
   *
   * Bounded either way: a connect that never says anything must stop asking rather than
   * leave a timer running for the rest of the session (P13).
   */
  const readOpening = useCallback(
    async (tries = 12) => {
      // Named `tried`, not `attempt`: the loop variable would shadow the helper that wraps
      // every call to the core, and the shadowing is silent until the call is made.
      for (let tried = 0; tried < tries; tried += 1) {
        if (reading.current) {
          await new Promise((resolve) => window.setTimeout(resolve, 200));
          continue;
        }
        reading.current = true;
        const from = offset.current;
        const answer = await attempt(() => agentPoll(project, from)).finally(() => {
          reading.current = false;
        });
        if (answer === null) return;
        offset.current = answer.offset;
        if (answer.model) setModel(answer.model);
        absorb(answer);
        setTranscript((previous) =>
          from === 0
            ? answer.events.filter(worthShowing)
            : absorbTurns(previous, answer.events),
        );
        for (const event of answer.events) {
          if (event.kind === "blocked" && !event.id) setBlocked(event.text);
        }
        if (
          answer.events.some(
            (event) =>
              event.kind === "ready" ||
              event.kind === "blocked" ||
              // A session that opens straight into a question has said something, and
              // waiting past it for a `ready` that is not coming is the wait Q21 removed.
              event.kind === "asking",
          )
        )
          return;
        if (tried + 1 < tries) {
          await new Promise((resolve) => window.setTimeout(resolve, 400));
        }
      }
    },
    [project, absorb, attempt],
  );

  const begin = useCallback(
    async (resume?: string, fork = false) => {
      // Starting the agent spawns a process, which takes a second or two. Without a visible
      // in-flight state the button looks unpressed for that whole time, and a button that
      // looks unpressed gets pressed again -- five `agent.start` calls for one intention.
      if (connecting) return false;
      setConnecting(true);
      setBlocked(null);
      try {
        const state = await attempt(() => agentStart(project, resume, fork));
        if (state === null) return false;
        setRunning(state.running);
        setAvailable(state.available);
        absorb(state);
        // A different conversation is a different log: start reading it from the top, and
        // drop what the previous one said rather than letting two share a panel.
        offset.current = 0;
        setTranscript([]);
        setContext(0);
        setModel("");
        if (!state.ok) {
          setBlocked(state.detail);
          return false;
        }
        // One read for a conversation being resumed: it will not announce itself until it
        // answers, and its model and corrected id arrive with that turn.
        await readOpening(resume ? 1 : 12);
        setUnstarted(false);
        return true;
      } finally {
        setConnecting(false);
      }
      return false;
    },
    [project, absorb, attempt, connecting, readOpening],
  );

  /** Put the panel back to an unstarted conversation. Starts nothing; stops nothing. */
  const freshen = useCallback(() => {
    setUnstarted(true);
    setTranscript([]);
    setBlocked(null);
    setStatus("");
    setContext(0);
    setModel("");
    setCurrent(null);
    offset.current = 0;
    field.current?.focus();
  }, []);

  const forget = useCallback(
    async (identifier: string) => {
      const state = await attempt(() => agentForget(project, identifier));
      if (state === null) return;
      setRunning(state.running);
      absorb(state);
      // Forgetting the live conversation closes it, so what was on screen belongs to a
      // session that no longer exists.
      if (!state.running) {
        stopPollingRef.current?.();
        setTranscript([]);
        setStatus("");
        setContext(0);
        setModel("");
        offset.current = 0;
      }
    },
    [project, absorb, attempt],
  );

  const rename = useCallback(
    async (identifier: string, label: string) => {
      setNaming(null);
      const state = await attempt(() =>
        agentRename(project, identifier, label),
      );
      if (state !== null) absorb(state);
    },
    [project, absorb, attempt],
  );

  const deliver = useCallback(
    async (said: string, images: Pasted[] = []) => {
      setBlocked(null);
      setBusy(true);
      setStatus("thinking…");
      // Shown before the core has answered: what the person typed is true the moment they
      // press send, and waiting for a round trip to display it is what made the panel read
      // as a log of the agent rather than as a conversation between two parties.
      // **Sending is what creates the conversation.** Until now there was a tab and a draft
      // and nothing on disk -- no process, no id, no entry in the list -- because a session
      // nobody has spoken to is not a conversation the agent will resume either.
      //
      // Opened *before* the line is drawn, not after. Opening clears the transcript, and
      // doing it second wiped the question for the two seconds a session takes to start --
      // leaving "thinking…" above an empty panel that said nothing had been said.
      if (unstarted || !running) {
        const opened = await begin();
        if (!opened) {
          setBusy(false);
          setStatus("");
          return;
        }
      }

      // What the person typed is true the moment they press send, so it is drawn without
      // waiting for a round trip. The core records it and replays it later; `PENDING` is
      // what keeps the two from becoming two lines.
      // Sending is the person choosing the bottom again: their own line is the one they
      // want to see, whatever they were reading a moment ago.
      following.current = true;
      setTranscript((previous) => [...previous, yours(said)]);

      const answer = await attempt(() => agentSay(project, said, images));
      if (answer === null) return;
      if (!answer.ok) {
        setBusy(false);
        setStatus("");
        setBlocked(answer.detail);
        return;
      }
      void poll();
    },
    [project, poll, attempt, unstarted, running, begin],
  );

  deliverRef.current = deliver;

  /**
   * Ask, or wait to ask.
   *
   * A turn is one at a time, so a question typed while an answer is being written joins a
   * queue instead of being refused. It appears in the transcript immediately either way --
   * it *was* said; what is waiting is the asking.
   */
  const send = useCallback(
    (text: string) => {
      const said = text.trim();
      // A picture on its own is a question -- "what is this?" -- so it is not nothing.
      if (!said && pasted.length === 0) return;
      const images = pasted;
      setDraft("");
      setPasted([]);
      if (busy) {
        queue.current.push({ text: said, images });
        setTranscript((previous) => [...previous, yours(said)]);
        return;
      }
      void deliver(said, images);
    },
    [busy, deliver, pasted],
  );

  /**
   * Stop the answer being written. **Not the conversation.**
   *
   * The agent takes a control message and ends the turn; killing its process would throw
   * away the session and the thread of what was being discussed to cancel one answer.
   * Anything still waiting to be asked is dropped too -- stopping means stopping.
   */
  const halt = useCallback(async () => {
    queue.current = [];
    await attempt(() => agentInterrupt(project));
  }, [project, attempt]);

  /*
   * A picture pasted from the clipboard.
   *
   * Only pictures are taken -- text keeps the textarea's own behaviour, and intercepting a
   * paste of words would break the most ordinary thing anyone does in a field. The bytes are
   * read into base64 here rather than written to a file: a temporary file would outlive the
   * message, and there is nowhere in the project it would belong.
   */
  function absorbPaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const pictures = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (pictures.length === 0) return;
    event.preventDefault();

    for (const picture of pictures) {
      const reader = new FileReader();
      reader.onload = () => {
        const url = String(reader.result);
        const comma = url.indexOf(",");
        if (comma < 0) return;
        setPasted((previous) => [
          ...previous,
          { media_type: picture.type, data: url.slice(comma + 1) },
        ]);
      };
      reader.readAsDataURL(picture);
    }
  }

  /** Attach files by naming them the way the agent already understands: `@path`. */
  async function attach() {
    const chosen = await attempt(() =>
      openDialog({ multiple: true, defaultPath: project }),
    );
    if (chosen === null) return;
    const files = Array.isArray(chosen) ? chosen : chosen ? [chosen] : [];
    if (files.length === 0) return;
    const root = project.endsWith("/") ? project : `${project}/`;
    const mentions = files
      .map((file) => (file.startsWith(root) ? file.slice(root.length) : file))
      .map((file) => `@${file}`)
      .join(" ");
    setDraft((previous) =>
      previous ? `${previous} ${mentions} ` : `${mentions} `,
    );
    field.current?.focus();
  }

  // Named `limit` and not `window`: shadowing the global would silently break the timers.
  const limit = windowFor(model);
  const filled = limit > 0 ? Math.min(1, context / limit) : 0;
  const circumference = 2 * Math.PI * 8;

  /*
   * The ring is a warning, so it appears when there is something to warn about. Drawn at
   * every size it is a decoration shaped like an alarm -- a nearly empty circle beside a
   * conversation with a million tokens of room reads as a reason to compact when there is
   * none. Past a quarter it starts meaning something, and below that the raw count beside
   * it is the whole truth anyway. An unrecognised model has no fraction to draw at all
   * (`windowFor` returns 0), and a fraction we cannot compute must never be shown as one.
   */
  const QUARTER = 0.25;
  const showRing = limit > 0 && filled > QUARTER;

  /*
   * The commands a `/` at the start of the field could still become.
   *
   * Only at the start, and only while the name is still being typed -- once there is a
   * space the person is writing the command's argument, and a list of names over the top of
   * that is in the way. **Names without descriptions**, because names without descriptions
   * is what the agent sends; a sentence of ours about `/compact` would be this application
   * making claims about somebody else's command, and it would still be there after the
   * command changed.
   */
  const typing = draft.startsWith("/") && !draft.includes(" ") ? draft.slice(1) : null;
  const suggestions =
    typing === null
      ? []
      : commands.filter((name) => name.startsWith(typing)).slice(0, 8);
  const at = Math.min(picked, Math.max(0, suggestions.length - 1));

  /*
   * Changing one of the three flags a session is started with.
   *
   * **It restarts the conversation, and it says so.** These are flags at spawn -- the agent
   * offers no way to change a running session's model or its permission mode -- so the core
   * resumes the conversation under its own id in a new process. The conversation is kept; the
   * process it was being had in is not, and a person is told that rather than left to believe
   * a switch mid-answer was free.
   */
  const configure = useCallback(
    async (change: {
      model?: string;
      effort?: string;
      mode?: string;
      commands?: string;
    }) => {
      const answer = await attempt(() => agentConfigure(project, change));
      if (answer === null) return;
      if (!answer.ok) {
        setBlocked(answer.detail);
        return;
      }
      if (answer.settings) setSettings(answer.settings);
      setStatus(answer.detail);
      if (answer.running) setRunning(true);
    },
    [attempt, project],
  );

  /*
   * How each choice is spelled for a person. Only the spelling: the set itself comes from the
   * core, so a choice arriving that has no line here is still shown, under its own name.
   */
  const MODE_NAMES: Record<string, string> = {
    acceptEdits: "Edit automatically",
    plan: "Plan only — no changes",
    default: "Ask about everything",
    dontAsk: "Don't ask",
    auto: "Auto",
  };
  const OWN_CHOICE = "The agent's own";

  /*
   * Whether commands are asked about, spelled as what it means rather than as its value.
   *
   * A setting of its own because it is a different mechanism from the mode -- measured, not
   * assumed. It is no longer what makes commands *possible*, though: pressing "Allow" on the
   * request does that (Q21). What is left is the standing answer of somebody who does not
   * want to be asked about commands in this project.
   */
  const COMMAND_NAMES: Record<string, string> = {
    "": "Ask before running commands",
    bash: "Run commands without asking",
  };

  function settingItems(
    section: string,
    field: "model" | "effort" | "mode" | "commands",
    offered: string[],
  ): Item[] {
    return offered.map((value) => ({
      section,
      label:
        field === "mode"
          ? value === ""
            ? OWN_CHOICE
            : (MODE_NAMES[value] ?? value)
          : field === "commands"
            ? (COMMAND_NAMES[value] ?? value)
            : value === ""
              ? OWN_CHOICE
              : value,
      checked: settings[field] === value,
      run: () => void configure({ [field]: value }),
    }));
  }

  /**
   * Answer one standing request. **The turn resumes from where it stopped.**
   *
   * The transcript is corrected here rather than waited for: the answer is a fact about what
   * this person just did, the core records it, and the poll that would carry it back only
   * re-reads a chunk it has already passed. Waiting for it would leave the buttons live for
   * a second after the decision was made.
   */
  const answer = useCallback(
    async (
      request: string,
      allow: boolean,
      always = false,
      answers?: Record<string, string>,
    ) => {
      if (answering !== null) return;
      setAnswering(request);
      try {
        const told = await attempt(() =>
          agentPermission(project, request, allow, always, answers),
        );
        if (told === null || !told.ok) return;
        setTranscript((previous) =>
          previous.map((event) =>
            event.kind === "asking" && event.id === request
              ? { ...event, answer: allow ? "allowed" : "denied" }
              : event,
          ),
        );
        // The agent was stopped on this and is now working again -- and the poll loop may
        // have wound down while nothing was happening. Nudging it here is what makes the
        // reply arrive without the person having to type something to wake it up.
        setStatus("");
        if (!busy) setBusy(true);
        void poll();
      } finally {
        setAnswering(null);
      }
    },
    [answering, attempt, project, busy, poll],
  );

  /**
   * The request still waiting, or -1. Computed, never stored: the transcript is it.
   *
   * Only the **last** one gets buttons. An agent asked about three commands in a row would
   * otherwise put three live cards on screen, and the one it is actually stopped on is the
   * last of them.
   */
  const standing = transcript.reduce(
    (found, event, index) =>
      event.kind === "asking" && !event.answer ? index : found,
    -1,
  );

  function openMenu(target: HTMLElement, items: Item[]) {
    const box = target.getBoundingClientRect();
    setMenu({ x: box.left, y: box.top, items });
  }

  function complete(name: string) {
    setDraft(`/${name} `);
    setPicked(0);
    field.current?.focus();
  }

  /**
   * Closed is **closed**, not folded.
   *
   * The composer used to stay on screen whatever `open` said, so "hidden" was a box in the
   * corner of a canvas that is supposed to keep the whole window (P18.1) -- and the panel
   * arrived in two pieces, a transcript that appeared above a field that had never left.
   * Now `Ask AI` opens one thing and closing puts all of it away.
   *
   * The exception is a turn that is still running. An agent editing files with nothing on
   * screen to say so is the application doing work behind the person's back, so a running
   * turn leaves a chip that says so and opens the panel again.
   */
  if (!open) {
    return busy ? (
      <button
        className="bp-chat-working"
        onClick={() => setOpen(true)}
        title="The agent is working — open the conversation"
      >
        <span className="bp-livedot" />
        {status || "working"}
      </button>
    ) : null;
  }

  return (
    <div ref={shell} className="bp-chat">
      <div className="bp-chat-panel">
          <div className="bp-chat-head">
            <span className="bp-chat-title">Ask AI</span>
            {/* Closing by hand as well as by looking away: a panel that only closes when
                attention moves cannot be put away while attention stays here. */}
            <button
              className="bp-icon"
              onClick={() => setOpen(false)}
              title="Close the conversation"
            >
              ✕
            </button>
          </div>

          <div className="bp-chat-sessions">
            <div className="bp-sess">
              {sessions.map((session) => (
                // A chip and its ✕ are two actions, so they are two buttons -- one nested
                // inside the other would make every close a switch as well.
                <span
                  key={session.id}
                  className={`bp-sess-chip${
                    !unstarted && session.id === current ? " is-on" : ""
                  }`}
                >
                  {naming === session.id ? (
                    // The chip becomes the field, so the name is edited where it is read.
                    <input
                      className="bp-sess-name"
                      autoFocus
                      defaultValue={session.label}
                      maxLength={60}
                      onBlur={(event) =>
                        void rename(session.id, event.target.value)
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") event.currentTarget.blur();
                        if (event.key === "Escape") setNaming(null);
                      }}
                    />
                  ) : (
                    <button
                      className="bp-sess-open"
                      // The id lives in the tooltip. On the chip it was eight characters of
                      // hex that told a person nothing and made every tab look alike.
                      title={`${session.id} · ${session.at}`}
                      disabled={connecting}
                      onClick={() => void begin(session.id)}
                      onDoubleClick={() => setNaming(session.id)}
                      onContextMenu={(event) => {
                        // Where a person looks for rename and delete. The double-click still
                        // renames, but nothing announced it, so it was a secret.
                        event.preventDefault();
                        setMenu({
                          x: event.clientX,
                          y: event.clientY,
                          items: [
                            {
                              label: "Rename",
                              run: () => setNaming(session.id),
                            },
                            {
                              label: "Delete",
                              destructive: true,
                              run: () => void forget(session.id),
                            },
                          ],
                        });
                      }}
                    >
                      {session.label}
                    </button>
                  )}
                </span>
              ))}
              {/* Instant, and empty. Nothing is spawned and nothing is written until the
                  first message -- the tab is a place to start, not a session. */}
              <button
                className={`bp-sess-chip bp-sess-act${unstarted ? " is-on" : ""}`}
                disabled={connecting}
                onClick={freshen}
              >
                + New
              </button>
              {/* A fork keeps the original branch: "do that again differently" must not
                  mean "lose the first attempt". */}
              <button
                className="bp-sess-chip bp-sess-act"
                disabled={!current || connecting}
                onClick={() => current && void begin(current, true)}
              >
                ⑂ Fork
              </button>
            </div>
          </div>

          <div
            className="bp-chat-log"
            ref={tail}
            // Reading is the signal, and it is read from the scroll itself rather than from
            // a button: scrolling up means "I am reading", coming back to the bottom means
            // "carry on". Nothing to notice, nothing to switch off.
            onScroll={(event) => {
              const log = event.currentTarget;
              const left = log.scrollHeight - log.scrollTop - log.clientHeight;
              following.current = left < 40;
            }}
          >
            {transcript.map((event, index) => {
              // A `did` is not a line of its own: it is the answer to the call above it,
              // and it is drawn there. Pairing is by the agent's `tool_use_id`, because
              // "the next one" stops being true as soon as two tools are in flight.
              if (event.kind === "did" || event.kind === "delta") return null;

              // The one card in this panel that is a question rather than a report. It gets
              // buttons only while it is **the** standing request: an answered one stays in
              // the transcript, because what was allowed is part of the story, and a request
              // the agent has since been asked about again is not the one it is stopped on.
              const waiting = event.kind === "asking" && index === standing;

              const answered =
                event.kind === "doing"
                  ? (transcript.find(
                      (later) =>
                        (later.kind === "did" || later.kind === "blocked") &&
                        later.id === event.id,
                    ) ?? null)
                  : null;

              return (
                <div key={index} className={`bp-turn is-${event.kind}`}>
                  {event.kind === "says" ? (
                    // Only the agent's text is formatted. What the person typed is shown as
                    // typed -- rendering their asterisks would be editing what they said.
                    <div className="bp-turn-text">
                      <Markdown source={event.text} />
                    </div>
                  ) : event.kind === "you" ? (
                    <div className="bp-turn-text">{event.text}</div>
                  ) : event.kind === "asking" && waiting && event.questions.length > 0 ? (
                    // **A question, not a command** (Q37). Drawn as the decision it is,
                    // and only while it is the standing one -- an answered question goes
                    // back to the ordinary card below, which says what was chosen.
                    <Question
                      questions={event.questions}
                      busy={answering !== null || !running}
                      onAnswer={(answers) =>
                        void answer(event.id, true, false, answers)
                      }
                      onDecline={() => void answer(event.id, false)}
                    />
                  ) : event.kind === "asking" ? (
                    <div className={`bp-ask${waiting ? " is-waiting" : ""}`}>
                      <div className="bp-ask-h">
                        {/* A question that has been answered did not get "permission",
                            and saying so would misdescribe what the person did (Q37). */}
                        {waiting
                          ? "Permission"
                          : event.questions.length > 0
                            ? event.answer === "allowed"
                              ? "Answered"
                              : "Skipped"
                            : event.answer === "allowed"
                              ? "Allowed"
                              : "Denied"}
                      </div>
                      <div className="bp-ask-what">
                        {/* What it asked for, in full and unedited. A person answering
                            about a command has to be able to read the command. */}
                        <span className="bp-ask-tool">
                          {event.tool || "a tool"}
                        </span>
                        <code>{event.detail || event.text}</code>
                      </div>
                      {waiting ? (
                        <>
                          <div className="bp-ask-why">
                            Nothing has run yet — the agent is stopped here, waiting for
                            you. <b>Always</b> writes the rule into this project's own
                            settings, where its terminal reads them too.
                          </div>
                          <div className="bp-ask-acts">
                            <button
                              className="bp-btn bp-btn-go"
                              disabled={answering !== null || !running}
                              onClick={() => void answer(event.id, true)}
                            >
                              {answering === event.id ? "…" : "Allow"}
                            </button>
                            <button
                              className="bp-btn"
                              disabled={answering !== null || !running}
                              onClick={() => void answer(event.id, true, true)}
                            >
                              Always
                            </button>
                            <button
                              className="bp-btn"
                              disabled={answering !== null || !running}
                              onClick={() => void answer(event.id, false)}
                            >
                              Deny
                            </button>
                          </div>
                        </>
                      ) : null}
                    </div>
                  ) : event.kind === "blocked" && event.id ? null : (
                    <Step event={event} answer={answered} />
                  )}
                </div>
              );
            })}

            {/* The answer as it is being written. Replaced by the complete message the
                moment it arrives, so the two are never both on screen. */}
            {writing ? (
              <div className="bp-turn is-says">
                <div className="bp-turn-text">
                  <Markdown source={writing} />
                  <span className="bp-caret" />
                </div>
              </div>
            ) : null}
            {/* The working line lives *in* the transcript, at the point in the conversation
                where the work is happening. Above the field it was a separate readout about
                the chat rather than a part of it. */}
            {busy ? (
              <div className="bp-turn is-working">
                <span className="bp-livedot" />
                <span className="bp-step-text">{status || "thinking…"}</span>
                {/* What it is thinking, while it is thinking it. Trailing rather than
                    whole: the finished thought is folded into the chain afterwards. */}
                {musing && !status ? (
                  <span className="bp-musing">{musing.slice(-90)}</span>
                ) : null}
                {/* Seconds, and only once there are some: a "0s" that appears with every
                    turn is furniture, and furniture is what people stop reading. */}
                {elapsed > 1 ? (
                  <span className="bp-elapsed">
                    {elapsed < 60
                      ? `${elapsed}s`
                      : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
                  </span>
                ) : null}
                {/* What this turn has cost so far, counting up from nothing. **The agent's
                    own estimate**, and shown with a tilde because of it: real usage is
                    reported exactly twice in a turn, so a number that moves could only ever
                    have been the agent's guess or ours, and ours would be a fiction. */}
                {spending > 0 ? (
                  <span
                    className="bp-spent"
                    title="the agent's own running estimate"
                  >
                    ~{spending.toLocaleString()} tokens
                  </span>
                ) : null}
              </div>
            ) : null}

            {transcript.length === 0 && !busy ? (
              <div className="bp-empty">
                Nothing said in this conversation yet. What the agent does shows
                on the canvas.
              </div>
            ) : null}
        </div>

        {blocked ? (
          <Notice
            tone="blocked"
            label="blocked"
            text={blocked}
            onClose={() => setBlocked(null)}
          />
        ) : null}

        <div className="bp-chat-box">
          {available === false ? (
            <div className="bp-chat-row">
              <div className="bp-chat-absent">
                No agent on this machine — install Claude Code.
              </div>
            </div>
          ) : who !== null && !who.signed_in ? (
            // Nobody is signed in, so there is nothing to talk to. Everything stays visible --
            // the panel, the conversations, what was said in them -- and only writing is off:
            // hiding it all behind a login would hide the thing the login is for.
            <div className="bp-chat-row">
              <Spark />
              <div className="bp-chat-absent">
                Not signed in — the agent runs on your own Claude account.
              </div>
              <button
                className="bp-chat-connect"
                disabled={connecting}
                onClick={() => {
                  setConnecting(true);
                  void attempt(() => agentSignIn())
                    .then((told) => told && setWho(told))
                    .finally(() => setConnecting(false));
                }}
                title="opens the agent's own sign-in page in your browser"
              >
                {connecting ? "Waiting for the browser…" : "Connect"}
              </button>
            </div>
          ) : (
            <>
              {/* The pictures this message is carrying. Above the field because they belong to
                  the line being written -- and they go when it is sent, the same way the words
                  in the field do. */}
              {pasted.length > 0 ? (
                <div className="bp-shots">
                  {pasted.map((picture, index) => (
                    <div className="bp-shot" key={`${index}-${picture.data.slice(0, 24)}`}>
                      <img
                        src={`data:${picture.media_type};base64,${picture.data}`}
                        alt="pasted"
                      />
                      <button
                        className="bp-shot-drop"
                        title="Remove from this message"
                        onClick={() =>
                          setPasted((previous) =>
                            previous.filter((_, other) => other !== index),
                          )
                        }
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}

              {suggestions.length > 0 ? (
                <div className="bp-slash" role="listbox">
                  {suggestions.map((name, index) => (
                    <button
                      key={name}
                      className={`bp-slash-item${index === at ? " is-picked" : ""}`}
                      role="option"
                      aria-selected={index === at}
                      // The field must not lose focus, or the list it belongs to closes
                      // under the press that was choosing from it.
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setPicked(index)}
                      onClick={() => complete(name)}
                    >
                      /{name}
                    </button>
                  ))}
                </div>
              ) : null}

              <textarea
                ref={field}
                className="bp-chat-field"
                value={draft}
                rows={1}
                placeholder={
                  busy
                    ? "ask the next thing — it waits its turn"
                    : "ask for a change"
                }
                spellCheck={false}
                disabled={connecting}
                onPaste={absorbPaste}
                onChange={(event) => {
                  setDraft(event.target.value);
                  setPicked(0);
                }}
                onKeyDown={(event) => {
                  // While the list is up the arrows and Enter belong to it. Tab completes
                  // without sending, which is the difference between choosing a command and
                  // asking for it -- a command usually wants an argument typed after it.
                  if (suggestions.length > 0) {
                    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                      event.preventDefault();
                      const step = event.key === "ArrowDown" ? 1 : -1;
                      setPicked(
                        (at + step + suggestions.length) % suggestions.length,
                      );
                      return;
                    }
                    if (event.key === "Tab") {
                      event.preventDefault();
                      complete(suggestions[at]);
                      return;
                    }
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setDraft("");
                      return;
                    }
                  }
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    if (suggestions.length > 0 && suggestions[at] !== typing) {
                      complete(suggestions[at]);
                      return;
                    }
                    void send(draft);
                  }
                }}
              />

              <div className="bp-chat-tools">
                <button
                  className="bp-icon"
                  onClick={() => void attach()}
                  title="Attach files"
                >
                  ＋
                </button>

                {/* What this conversation is being had with. Beside the attachments because
                    both are about the turn being prepared rather than about the answer. */}
                {choices ? (
                  <button
                    className="bp-icon"
                    title={`Model: ${settings.model || "the agent's own"} · effort: ${
                      settings.effort || "the agent's own"
                    } — changing either restarts the conversation`}
                    onClick={(event) =>
                      openMenu(event.currentTarget, [
                        ...settingItems("Model", "model", choices.models),
                        ...settingItems("Effort", "effort", choices.efforts),
                      ])
                    }
                  >
                    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
                      <path
                        d="M2 4h12M2 8h12M2 12h12"
                        stroke="currentColor"
                        strokeWidth="1.3"
                        fill="none"
                      />
                      <circle cx="5" cy="4" r="1.9" fill="currentColor" />
                      <circle cx="10" cy="8" r="1.9" fill="currentColor" />
                      <circle cx="6" cy="12" r="1.9" fill="currentColor" />
                    </svg>
                  </button>
                ) : null}

                {/* The ring fills against the window of the model the agent said it is
                    using, so it is only ever drawn when that window is known. Clicking asks
                    the agent to compact -- its own command, not ours. */}
                {showRing ? (
                  <button
                    className={`bp-ring${filled > 0.7 ? " is-full" : ""}`}
                    title={`${context.toLocaleString()} of ${
                      limit >= 1_000_000 ? `${limit / 1_000_000}M` : `${limit / 1000}k`
                    } tokens · ${model} · compact`}
                    onClick={() => void send("/compact")}
                    disabled={busy}
                  >
                    <svg viewBox="0 0 20 20" width="18" height="18">
                      <circle cx="10" cy="10" r="8" className="bp-ring-track" />
                      <circle
                        cx="10"
                        cy="10"
                        r="8"
                        className="bp-ring-fill"
                        strokeDasharray={`${filled * circumference} ${circumference}`}
                      />
                    </svg>
                  </button>
                ) : null}

                <span className="bp-chat-count">
                  {context > 0 ? `${Math.round(context / 1000)}k` : ""}
                </span>

                {/* How much the agent may do on its own. The same three flags as the menu
                    beside the attachments -- two surfaces onto one truth, never two settings
                    that can disagree -- and it sits by send because it is about what pressing
                    send is going to allow. */}
                {choices ? (
                  <button
                    className="bp-mode"
                    title="What the agent may do on its own — changing it restarts the conversation"
                    onClick={(event) =>
                      openMenu(event.currentTarget, [
                        ...settingItems("The agent may", "mode", choices.modes),
                        ...settingItems("And it may run", "commands", choices.commands),
                        ...settingItems("Effort", "effort", choices.efforts),
                      ])
                    }
                  >
                    {MODE_NAMES[settings.mode] ?? settings.mode}
                    <span className="bp-mode-caret">⌃</span>
                  </button>
                ) : null}

                {/* One button, and what it does follows what there is to do. A turn is
                    running and the field is empty: there is nothing to send and something to
                    stop. Type into it and sending is the intention again -- the question joins
                    the queue rather than interrupting the answer being written. */}
                {busy && !draft.trim() ? (
                  <button
                    className="bp-send is-stop"
                    onClick={() => void halt()}
                    title="Stop this answer — the conversation stays"
                  >
                    ■
                  </button>
                ) : (
                  <button
                    className="bp-send"
                    onClick={() => send(draft)}
                    disabled={!draft.trim()}
                    title={busy ? "Ask next — it waits for this answer" : "Send"}
                  >
                    ↑
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <Menu at={menu} onClose={() => setMenu(null)} />
    </div>
  );
}
