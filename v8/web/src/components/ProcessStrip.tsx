import { Fragment } from "react";
import { label as glossLabel, meaning as glossMeaning } from "../copy/glossary";
import type { TicketStatus } from "../api/types";
import styles from "./ProcessStrip.module.css";

// The process strip (design §16, §21 amendment 2; folio-ticket plate): the ordered stages a ticket
// or epic moves through, the current one marked "current", and one plain sentence naming the next
// action — linked to the control that performs it. It answers "where is this, and what happens
// next" without a shell. Stages are the happy path; a blocked/partial/dropped ticket shows its
// off-line state as a badge instead of a false position on the line.

const STAGES: TicketStatus[] = [
  "drafted", "designed", "signed_off", "ready", "in_progress", "in_review", "done",
];

/** The default next-action sentence for a stage — a page overrides this with a linked control. */
export function nextActionFor(status: string): string {
  switch (status) {
    case "drafted": return "Draft a design, then move it to Designed.";
    case "designed": return "Sign off the design to let work start.";
    case "signed_off": return "Mark it Ready so a seat can pick it up.";
    case "ready": return "Assign or spawn a seat, then start the work.";
    case "in_progress": return "Do the work and attach evidence, then move it to In review.";
    case "in_review": return "Review the evidence, record the checks, then mark it Done.";
    case "done": return "Complete — nothing more is needed.";
    case "blocked": return "Clear what blocks it, then return it to In progress.";
    case "partial": return "Decide whether the remaining work continues or is dropped.";
    case "dropped": return "This work was stopped; no further action.";
    default: return "";
  }
}

export function ProcessStrip({
  status,
  nextAction,
  ariaLabel = "Process",
}: {
  status: string;
  /** The next-action node (a sentence + a link to its control). Falls back to a plain sentence. */
  nextAction?: React.ReactNode;
  ariaLabel?: string;
}): React.JSX.Element {
  const currentIndex = STAGES.indexOf(status as TicketStatus);
  const offLine = currentIndex === -1; // blocked / partial / dropped

  return (
    <nav className={styles.strip} aria-label={ariaLabel} data-testid="process-strip" data-status={status}>
      <ol className={styles.stages}>
        {STAGES.map((stage, i) => {
          const isCurrent = i === currentIndex;
          const isPast = currentIndex > -1 && i < currentIndex;
          const tip = glossMeaning("ticket_status", stage);
          return (
            <Fragment key={stage}>
              <li
                className={`${styles.stage} ${isCurrent ? styles.current : ""} ${isPast ? styles.past : ""}`}
                aria-current={isCurrent ? "step" : undefined}
                data-testid={isCurrent ? "stage-current" : undefined}
                title={tip}
              >
                <span className={styles.dot} aria-hidden="true" />
                <span className={styles.stageLabel}>{glossLabel("ticket_status", stage)}</span>
                {isCurrent ? <span className={styles.currentTag}>current</span> : null}
              </li>
              {i < STAGES.length - 1 ? <li className={styles.joint} aria-hidden="true" /> : null}
            </Fragment>
          );
        })}
      </ol>

      {offLine ? (
        <p className={styles.offLine} data-testid="off-line-state">
          This ticket is <strong>{glossLabel("ticket_status", status)}</strong> —{" "}
          {glossMeaning("ticket_status", status) ?? ""}
        </p>
      ) : null}

      <p className={styles.next} data-testid="next-action">
        <span className={styles.nextLabel}>Next:</span> {nextAction ?? nextActionFor(status)}
      </p>
    </nav>
  );
}
