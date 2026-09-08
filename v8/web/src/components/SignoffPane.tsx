import type { CriterionView, DocHtml } from "../api/types";
import { CriterionCard } from "./CriterionCard";
import ui from "./ui.module.css";
import styles from "./DocView.module.css";

// The doc reader's inline sign-off pane (design §14, criterion c-a0b2f8ddda): when the board
// reports the viewer has a pending criterion whose evidence is THIS doc, it appears beside the
// document as G2's one-click CriterionCard in ruling mode — Approve (one click) / Needs work
// (note required) posting the verdict for the frozen version. This file (G3a-owned) is the seam
// that turns the board's `signoff_criterion` into the shared card; the card itself is G2's.
export function SignoffPane({ doc }: { doc: DocHtml }): React.JSX.Element | null {
  const s = doc.signoff_criterion;
  if (!s) return null;
  const latest = doc.versions.length ? Math.max(...doc.versions) : doc.version;
  const criterion: CriterionView = {
    id: s.id,
    text: s.text,
    check: "look",
    checked_by: null,
    verdict: "pending",
    evidence_ref: doc.id,
    evidence_version: doc.version,
  };
  return (
    <div className={styles.signoff} data-testid="signoff-pane">
      <div className={ui.sectionLabel}>Your sign-off</div>
      <CriterionCard
        criterion={criterion}
        ticketId={s.ticket_id}
        ruling={{ evidenceVersion: doc.version, stale: doc.version !== latest }}
      />
    </div>
  );
}
