import ui from "./ui.module.css";

// Every state carries a WORD, never colour alone (design §4.2). The colour class is a hint
// layered on the word: terminal → success wash, live → accent wash, blocked → accent wash,
// everything else neutral. The label is the status with underscores spaced.
const WORD: Record<string, string> = {
  drafted: "Drafted",
  designed: "Designed",
  signed_off: "Signed off",
  ready: "Ready",
  in_progress: "In progress",
  in_review: "In review",
  blocked: "Blocked",
  done: "Done",
  partial: "Partial",
  dropped: "Dropped",
};

function variant(status: string): string {
  if (status === "done" || status === "partial") return ui.done;
  if (status === "in_progress" || status === "in_review" || status === "ready") return ui.active;
  if (status === "blocked") return ui.blocked;
  return "";
}

export function StatusChip({ status }: { status: string }): React.JSX.Element {
  return (
    <span className={`${ui.chip} ${variant(status)}`} data-testid="status-chip" data-status={status}>
      <span className={ui.chipDot} aria-hidden="true" />
      {WORD[status] ?? status.replace(/_/g, " ")}
    </span>
  );
}
