import { label as glossLabel, term } from "../copy/glossary";
import { Term } from "./Term";
import styles from "./AgentLine.module.css";

// Agent-authored text framing (design §15): a line of agent text is shown verbatim, but framed so a
// first-time reader knows WHO said it, in WHAT role, and what it means FOR THEM. Name first, id after
// in the mono face (never a bare id as the primary label); the message kind resolves through the
// glossary tooltip; and a reader-relative tag — "Waiting on you" when a question is addressed to the
// viewer, "For your information" otherwise — tells the reader whether they must act.

/** A seat handle is conventionally `<role>.<ticket>`; derive the role word when the prefix is one. */
function roleWordOf(by: string): string | null {
  const prefix = by.includes(".") ? by.split(".")[0] : by;
  return term("role", prefix) ? glossLabel("role", prefix) : null;
}

/** Name-first display: the handle without its id tail is the name; the whole handle is the id. */
function nameOf(by: string): string {
  return by.includes(".") ? by.split(".")[0] : by;
}

export function AgentLine({
  by,
  kind,
  to,
  viewer,
  at,
}: {
  by: string;
  kind: string;
  to?: string | null;
  /** The current viewer's handle (from ?as=). A question addressed to them → "Waiting on you". */
  viewer?: string | null;
  at?: string | null;
}): React.JSX.Element {
  const role = roleWordOf(by);
  const waitingOnYou = kind === "question" && !!viewer && to === viewer;

  return (
    <div className={styles.line} data-testid="agent-line">
      <span className={styles.name}>{nameOf(by)}</span>
      {role ? <span className={styles.role}>{role}</span> : null}
      <span className={styles.mono} data-testid="agent-id">
        {by}
      </span>
      {/* The message kind carries its plain meaning as a keyboard-reachable tooltip (aria-describedby),
          not a mouse-only title — the S15 "kind label" rule (c-581d50496d). */}
      <Term category="message_kind" value={kind} className={styles.kind} />
      <span
        className={`${styles.tag} ${waitingOnYou ? styles.waiting : styles.fyi}`}
        data-testid="reader-tag"
      >
        {waitingOnYou ? "Waiting on you" : "For your information"}
      </span>
      {at ? <span className={styles.at}>{at.slice(0, 16).replace("T", " ")}</span> : null}
    </div>
  );
}
