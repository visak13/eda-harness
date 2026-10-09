import { label as glossLabel, term } from "../copy/glossary";
import { Term } from "./Term";
import { Avatar } from "./Avatar";
import styles from "./AgentLine.module.css";

// Agent-authored text framing (design §15): a line of agent text is shown verbatim, but framed so a
// first-time reader knows WHO said it, in WHAT role, and what it means FOR THEM. Name first, id after
// in the mono face (never a bare id as the primary label); the message kind resolves through the
// glossary tooltip. (s-aa76c83998: the reader-relative "waiting" tag is gone; the owner dislikes that framing.)

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
  at,
}: {
  by: string;
  kind: string;
  at?: string | null;
}): React.JSX.Element {
  const role = roleWordOf(by);

  return (
    <div className={styles.line} data-testid="agent-line">
      <Avatar id={by} size={20} />
      <span className={styles.name}>{nameOf(by)}</span>
      {role ? <span className={styles.role}>{role}</span> : null}
      <span className={styles.mono} data-testid="agent-id">
        {by}
      </span>
      {/* The message kind carries its plain meaning as a keyboard-reachable tooltip (aria-describedby),
          not a mouse-only title — the S15 "kind label" rule (c-581d50496d). */}
      <Term category="message_kind" value={kind} className={styles.kind} />
      {at ? <span className={styles.at}>{at.slice(0, 16).replace("T", " ")}</span> : null}
    </div>
  );
}
