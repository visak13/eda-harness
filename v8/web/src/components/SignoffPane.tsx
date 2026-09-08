import { useEffect, useState } from "react";
import type { CriterionView, DocHtml } from "../api/types";
import { CriterionCard } from "./CriterionCard";
import ui from "./ui.module.css";
import styles from "./DocView.module.css";

// The doc reader's inline sign-off pane (design §14, criterion c-a0b2f8ddda): when the board
// reports the viewer has a pending criterion whose evidence is THIS doc, it appears beside the
// document as G2's one-click CriterionCard in ruling mode — Approve (one click) / Needs work
// (note required) posting the verdict for the frozen version. This file (G3a-owned) is the seam
// that turns the board's `signoff_criterion` into the shared card; the card itself is G2's.
//
// LATCH: on a successful ruling G2's card invalidates all queries, so the doc refetches and
// `signoff_criterion` goes null (the criterion is no longer pending) — which would unmount the
// card mid-success. c-a0b2f8ddda requires the card to stay and read "Passed"/"Needs work" WITHOUT
// a navigation, so once a criterion has appeared we keep rendering that same card instance; its
// own post-ruling verdict word is what the owner sees. A genuinely different pending criterion
// (new id) replaces the latched one.
export function SignoffPane({ doc }: { doc: DocHtml }): React.JSX.Element | null {
  const [latched, setLatched] = useState(doc.signoff_criterion);
  useEffect(() => {
    const s = doc.signoff_criterion;
    if (s && (!latched || s.id !== latched.id)) setLatched(s); // adopt the first / a new criterion
    // s === null after a successful ruling: keep the latched card so it can show its verdict word.
  }, [doc.signoff_criterion, latched]);

  const s = latched;
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
