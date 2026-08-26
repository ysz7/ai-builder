/**
 * One thing the application has to say, and one way to put it away.
 *
 * Every panel here reports refusals rather than throwing them: a rejected write, a check that
 * could not run, a tool the agent was denied. That is the right behaviour and it leaves a
 * question -- how does the person get rid of the message once they have read it? Without an
 * answer, a notice stays until something else replaces it, which teaches people to ignore the
 * place notices appear.
 *
 * Dismissing is the *reader* saying they are done. It never means the thing was resolved, and
 * nothing here reports it as resolved: the next read, write or run says what is true now.
 */

type Tone = "blocked" | "refused" | "said" | "failed";

type Props = {
  tone: Tone;
  /** The short word in front -- "blocked", "refused". Omitted where the text says it. */
  label?: string;
  text: string;
  /** Absent for a notice that is part of the panel rather than an event in it. */
  onClose?: () => void;
};

export function Notice({ tone, label, text, onClose }: Props) {
  return (
    <div className={`bp-notice is-${tone}`}>
      {label ? <span className="bp-notice-label">{label}</span> : null}
      <span className="bp-notice-text">{text}</span>
      {onClose ? (
        <button className="bp-notice-shut" onClick={onClose} title="Dismiss">
          ✕
        </button>
      ) : null}
    </div>
  );
}
