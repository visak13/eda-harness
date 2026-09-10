import { useEffect, useState } from "react";
import type { CriterionView, DocHtml } from "../api/types";
import { CriterionCard } from "./CriterionCard";
import ui from "./ui.module.css";
import styles from "./DocView.module.css";

// The doc reader's inline sign-off pane (design §14, criterion c-a0b2f8ddda): when the board
// reports the viewer has pending criteria whose evidence is THIS doc, each appears beside the
// document as G2's one-click CriterionCard in ruling mode — Approve (one click) / Needs work
// (note required) posting the verdict for the frozen version. This file (G3a-owned) is the seam
// that turns the board's `signoff_criteria` into the shared cards; the card itself is G2's.
// EVERY pending criterion the viewer checks is shown — owner-checked for the owner, qa-checked for
// the qa seat, and so on — not the first owner one only (adversary finding #8, 2026-09-10).
//
// LATCH: on a successful ruling G2's card invalidates all queries, so the doc refetches and the
// criterion leaves the list (no longer pending) — which would unmount the card mid-success.
// c-a0b2f8ddda requires the card to stay and read "Passed"/"Needs work" WITHOUT a navigation, so
// once a criterion has appeared we keep rendering that same card instance; its own post-ruling
// verdict word is what the owner sees. New ids are appended as they appear.
type Row = { id: string; text: string; ticket_id: string; checked_by?: string | null };

export function SignoffPane({ doc }: { doc: DocHtml }): React.JSX.Element | null {
  const reported: Row[] = doc.signoff_criteria ?? (doc.signoff_criterion ? [doc.signoff_criterion] : []);
  const [latched, setLatched] = useState<Row[]>(reported);
  useEffect(() => {
    const fresh = reported.filter((r) => !latched.some((l) => l.id === r.id));
    if (fresh.length) setLatched((l) => [...l, ...fresh]); // adopt new criteria; keep ruled ones
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.signoff_criteria, doc.signoff_criterion]);

  if (latched.length === 0) return null;
  const latest = doc.versions.length ? Math.max(...doc.versions) : doc.version;
  return (
    <div className={styles.signoff} data-testid="signoff-pane">
      <div className={ui.sectionLabel}>{latched.length > 1 ? `Your sign-offs (${latched.length})` : "Your sign-off"}</div>
      {latched.map((s) => {
        const criterion: CriterionView = {
          id: s.id,
          text: s.text,
          check: "look",
          checked_by: s.checked_by ?? null,
          verdict: "pending",
          evidence_ref: doc.id,
          evidence_version: doc.version,
        };
        return (
          <CriterionCard
            key={s.id}
            criterion={criterion}
            ticketId={s.ticket_id}
            ruling={{ evidenceVersion: doc.version, stale: doc.version !== latest }}
          />
        );
      })}
    </div>
  );
}
