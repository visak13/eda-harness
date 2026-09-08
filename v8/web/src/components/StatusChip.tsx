import { useId } from "react";
import { label as glossLabel, meaning as glossMeaning } from "../copy/glossary";
import ui from "./ui.module.css";
import term from "./Term.module.css";

// Every state carries a WORD, never colour alone (design §4.2). The word and its one-line meaning
// both come from the shared glossary (design §15), so the chip a person sees and the tooltip they
// hover agree with every other place the status appears. The colour class is a hint layered on the
// word: terminal → success wash, live → accent wash, blocked → accent wash, everything else neutral.

function variant(status: string): string {
  if (status === "done" || status === "partial") return ui.done;
  if (status === "in_progress" || status === "in_review" || status === "ready") return ui.active;
  if (status === "blocked") return ui.blocked;
  return "";
}

export function StatusChip({ status }: { status: string }): React.JSX.Element {
  const id = useId();
  const word = glossLabel("ticket_status", status);
  const meaning = glossMeaning("ticket_status", status);
  return (
    <span className={term.wrap}>
      <span
        className={`${ui.chip} ${variant(status)}`}
        data-testid="status-chip"
        data-status={status}
        tabIndex={meaning ? 0 : undefined}
        aria-describedby={meaning ? id : undefined}
      >
        <span className={ui.chipDot} aria-hidden="true" />
        {word}
      </span>
      {meaning ? (
        <span role="tooltip" id={id} className={term.tip}>
          {meaning}
        </span>
      ) : null}
    </span>
  );
}
