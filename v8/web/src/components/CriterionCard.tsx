import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CriterionView, Verdict } from "../api/types";
import { getDocHtml, postVerdict } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import { RewordCriterion } from "./CriterionControls";
import { useDirtyGuard } from "../live/useDraftGuard";
import styles from "./CriterionCard.module.css";
import { Icon } from "./Icon";

// The owner's criterion, typeset to be read (design §14): text verbatim at 14/22 ≤72ch, the id in
// the mono face and NEVER inline in the sentence, the check + checker as small labelled words.
// ONE card is shared by the ruling drawer (S6) and the doc page (S9, G3a's c-a0b2f8ddda) so a
// criterion reads identically everywhere. With `ruling` it becomes the one-click verdict pane:
// nothing preselected, Needs work requires a note, Enter never submits, Approve/Needs work post
// POST /v1/me/verdict carrying the frozen evidence_version (and stale_ok when ruling on an older
// version). Without `ruling` it is a read-only card (verdict word + an "open evidence" link).

const WORD: Record<Verdict, string> = { pass: "Passed", fail: "Needs work", pending: "Pending" };

export interface CriterionCardProps {
  criterion: CriterionView;
  /** Present → the verdict pane (design §14). evidenceVersion is the frozen doc version the ruling
   *  read; stale=true rules on an older version (sends stale_ok). Absent → read-only card. */
  /** evidenceVersion null = the criterion carries evidence but no version yet (the board stamps
   *  evidence_version only AT the verdict; a REST evidence_ref PATCH leaves it null) — the card then
   *  resolves the doc's current version itself, so the Ticket/Epic ruling panes are never hidden
   *  behind a version the page cannot know (acceptance finding, g3b-loop 2026-09-08). */
  ruling?: { evidenceVersion: number | null; stale?: boolean };
  /** Required when `ruling` is present: the ticket the '[sign-off …] note' message posts to. */
  ticketId?: string;
  /** Read-only card: open this criterion's evidence doc (the drawer/reader). */
  onOpenEvidence?: (docId: string) => void;
  /** Read-only card: allow rewording the criterion text while it is still pending (design §16).
   *  Needs `ticketId` for the cache invalidation; only offered on a pending, un-ruled card. */
  canReword?: boolean;
  /** Ruling pane: called after a verdict is recorded so the opener can close + refresh. */
  onRuled?: (verdict: "pass" | "fail") => void;
  /** Ruling pane: artifact ids staged by the host (a file dropped on the ruling drawer, promise #19).
   *  Shown as chips under the note and appended to the '[sign-off …]' note as `art-…` tokens. */
  attachments?: string[];
}

export function CriterionCard({
  criterion,
  ruling,
  ticketId,
  onOpenEvidence,
  canReword,
  onRuled,
  attachments = [],
}: CriterionCardProps): React.JSX.Element {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  // A half-typed ruling note is a draft: the feed holds its refreshes ("N new · refresh") instead
  // of refetching the doc/list under the card (adversary finding #2, 2026-09-10).
  useDirtyGuard(`note:${criterion.id}`, note.trim().length > 0, ticketId);
  const [decided, setDecided] = useState<"pass" | "fail" | null>(null);
  const [rewording, setRewording] = useState(false);

  // A ruling pane whose caller could not name the version reads the evidence doc's versions once.
  const needsVersion = Boolean(ruling) && ruling!.evidenceVersion == null && Boolean(criterion.evidence_ref);
  const evidenceDoc = useQuery({
    queryKey: ["doc-versions", criterion.evidence_ref],
    queryFn: () => getDocHtml(criterion.evidence_ref!),
    enabled: needsVersion,
    retry: false,
  });
  const resolvedVersion: number | null =
    ruling?.evidenceVersion ?? (evidenceDoc.data ? Math.max(evidenceDoc.data.version, ...evidenceDoc.data.versions) : null);

  const mutation = useMutation({
    mutationFn: (verdict: "pass" | "fail") =>
      postVerdict({
        criterion_id: criterion.id,
        verdict,
        evidence_version: resolvedVersion!,
        note: [note.trim(), ...attachments].filter(Boolean).join(" "),
        ticket_id: ticketId,
        stale_ok: ruling!.stale ?? false,
      }),
    onSuccess: (_data, verdict) => {
      setDecided(verdict);
      void qc.invalidateQueries(); // the item leaves Sign-offs and appears under Resolved
      onRuled?.(verdict);
    },
  });

  // Reset the local ruling state whenever the card is pointed at a DIFFERENT criterion. One card
  // instance is reused across criteria (the ruling drawer's next sign-off, G3a's doc-reader
  // SignoffPane) — without this, criterion B would inherit A's decided/note/error and hide its own
  // controls (second-opinion finding, G3a run 2026-09-08). Keyed by id so a stable criterion keeps
  // its just-recorded "Recorded: …" state.
  useEffect(() => {
    setDecided(null);
    setNote("");
    setRewording(false);
    mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [criterion.id]);

  const shownVerdict: Verdict = decided ?? criterion.verdict;
  const error = mutation.error instanceof BoardApiError ? mutation.error.message : mutation.error ? String(mutation.error) : null;

  return (
    <section className={styles.card} data-testid="criterion-card" aria-label="Criterion">
      <div className={styles.label}>YOUR CRITERION</div>
      <div className={styles.chipRow}>
        <span className={`${styles.chip} ${styles[shownVerdict]}`} data-testid="verdict-chip" data-verdict={shownVerdict}>
          {WORD[shownVerdict]}
        </span>
        <span className={styles.checkedBy}>
          {criterion.check} · {criterion.checked_by ?? "unassigned"}
        </span>
      </div>

      <p className={styles.text}>{criterion.text}</p>
      <div className={styles.id}>{criterion.id}</div>

      {!ruling ? (
        <>
          {criterion.evidence_ref ? (
            <button
              className={styles.evidenceLink}
              type="button"
              onClick={() => onOpenEvidence?.(criterion.evidence_ref!)}
            >
              Open evidence <Icon name="external" />
            </button>
          ) : null}
          {canReword && ticketId && criterion.verdict === "pending" ? (
            rewording ? (
              <RewordCriterion
                criterionId={criterion.id}
                ticketId={ticketId}
                current={criterion.text}
                onDone={() => setRewording(false)}
              />
            ) : (
              <button
                className={styles.evidenceLink}
                type="button"
                data-testid="reword-open"
                onClick={() => setRewording(true)}
              >
                Reword
              </button>
            )
          ) : null}
        </>
      ) : decided ? (
        <p className={styles.recorded} role="status">
          Recorded: <strong>{WORD[decided]}</strong>. Ticket advancement depends on the remaining checks.
        </p>
      ) : (
        <div className={styles.ruling}>
          <p className={styles.condition}>
            Your verification is not recorded. The report is evidence; recording a verdict is your
            decision, and it names the version you read.
          </p>
          <label className={styles.noteLabel} htmlFor={`note-${criterion.id}`}>
            NOTE TO THE AUTHOR
          </label>
          <textarea
            id={`note-${criterion.id}`}
            className={styles.note}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional for Approve; required for Needs work."
            rows={3}
            data-testid="note"
          />
          {attachments.length > 0 ? (
            <div className={styles.attachments} data-testid="note-attachments">
              Attached with the note:{" "}
              {attachments.map((id) => (
                <span key={id} className={styles.attachment} data-testid="staged-artifact">
                  {id}
                </span>
              ))}
            </div>
          ) : null}
          {error ? (
            <p className={styles.error} role="alert">
              {error} — your note is kept; try again.
            </p>
          ) : null}
          <div className={styles.actions}>
            <button
              className={styles.secondary}
              type="button"
              disabled={note.trim().length === 0 || mutation.isPending || resolvedVersion == null}
              onClick={() => mutation.mutate("fail")}
              data-testid="needs-work"
            >
              Needs work
            </button>
            <button
              className={styles.primary}
              type="button"
              disabled={mutation.isPending || resolvedVersion == null}
              onClick={() => mutation.mutate("pass")}
              data-testid="approve"
            >
              Approve criterion
            </button>
          </div>
          <p className={styles.footer}>
            Records pass or fail for this criterion. Ticket advancement depends on the remaining checks.
          </p>
        </div>
      )}
    </section>
  );
}
