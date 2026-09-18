import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import type { SignoffRow, UploadedArtifact } from "../api/types";
import { getDocHtml } from "../api/endpoints";
import { Drawer } from "./Drawer";
import { Markdown } from "./Markdown";
import { CriterionCard } from "./CriterionCard";
import { useDropUpload } from "./useDropUpload";
import { identity } from "../auth/identity";
import styles from "./RulingDrawer.module.css";
import { Icon } from "./Icon";

// The ruling body (design §6/§14, folded S6). It is the `children` of the shared Drawer (G3a):
// evidence on the left (the engineer's report, at the version this ruling froze) and the owner's
// criterion on the right (the shared CriterionCard in `ruling` mode). The verdict names the frozen
// version; if a newer version has since landed, the reader content is NOT swapped silently — a
// banner asks the owner to inspect first, and only an explicit "rule on the older version anyway"
// enables the verdict (which then sends stale_ok). Nothing is preselected; Esc/close and focus
// restore are the Drawer's job.

export interface RulingDrawerProps {
  signoff: SignoffRow | null; // null → closed
  kOfN?: { k: number; n: number };
  onClose: () => void;
  onRuled?: () => void;
  returnFocusTo?: HTMLElement | null;
}

export function RulingDrawer({ signoff, kOfN, onClose, onRuled, returnFocusTo }: RulingDrawerProps): React.JSX.Element {
  const [staleAck, setStaleAck] = useState(false);
  const docId = signoff?.doc?.id ?? null;
  // "Rule on vN anyway" is an acknowledgement of ONE document's newer version — it never carries
  // over to the next sign-off (adversary finding #3, 2026-09-10).
  const signoffKey = signoff?.criterion.id ?? null;
  // Promise #19: a file dropped anywhere on the ruling body uploads against the sign-off's ticket
  // (the composer's one upload path) and is staged with the ruling note — never carried over to
  // the next sign-off.
  const [staged, setStaged] = useState<string[]>([]);
  useEffect(() => {
    setStaleAck(false);
    setStaged([]);
  }, [signoffKey]);
  const onUploaded = useCallback((art: UploadedArtifact) => setStaged((s) => [...s, art.id]), []);
  const drop = useDropUpload(signoff?.ticket.id ?? "", onUploaded);
  const frozen = signoff?.doc?.version ?? 0;

  // Freeze: fetch exactly the version this ruling opened. `versions` still lists ALL versions, so
  // a newer one that lands is detectable without swapping the (frozen) reader content.
  const doc = useQuery({
    queryKey: ["doc-frozen", docId, frozen],
    queryFn: () => getDocHtml(docId!, frozen),
    enabled: Boolean(signoff && docId),
    retry: false,
  });

  const latest = doc.data ? Math.max(...doc.data.versions) : frozen;
  const newer = latest > frozen;
  const canRule = !newer || staleAck;

  const title = (
    <span className={styles.titleRow}>
      Review owner sign-off
      {signoff ? <span className={styles.crumb}>{signoff.ticket.title}</span> : null}
      {kOfN ? <span className={styles.kofn}>{kOfN.k} of {kOfN.n} sign-offs</span> : null}
    </span>
  );

  return (
    <Drawer open={Boolean(signoff)} onClose={onClose} title={title} returnFocusTo={returnFocusTo}>
      {signoff ? (
        <div
          className={`${styles.grid} ${styles.dropTarget} ${drop.dragOver ? styles.dragging : ""}`}
          data-testid="ruling-grid"
          {...drop.dropProps}
        >
          {drop.dragOver ? (
            <div className={styles.veil} data-testid="drop-veil">
              Drop to attach to your ruling
            </div>
          ) : null}
          <div className={styles.evidence} data-testid="ruling-evidence">
            <div className={styles.evLabel}>
              EVIDENCE · {signoff.doc?.doc_type?.toUpperCase() ?? "REPORT"}
              {signoff.doc ? <span className={styles.versionPill}>v{signoff.doc.version}</span> : null}
            </div>
            <h2 className={styles.evTitle}>{signoff.doc?.title ?? signoff.ticket.title}</h2>
            <div className={styles.author}>
              <span className={styles.avatar} aria-hidden="true">
                {(signoff.ticket.assignee ?? "?").slice(0, 1).toUpperCase()}
              </span>
              by {signoff.ticket.assignee ?? "the assignee"}
            </div>
            {doc.data ? <Markdown html={doc.data.html} /> : <p className={styles.loading}>Loading evidence…</p>}
            {signoff.doc ? (
              <Link
                className={styles.fullReport}
                to={`/doc/${encodeURIComponent(signoff.doc.id)}?version=${frozen}&as=${encodeURIComponent(identity())}`}
              >
                Full report <Icon name="external" />
              </Link>
            ) : null}
          </div>

          <div className={styles.pane} data-testid="ruling-pane">
            {newer ? (
              <div className={styles.newerBanner} role="alert" data-testid="newer-version-banner">
                A newer version (v{latest}) landed while this was open. The reader still shows the
                version you opened (v{frozen}). Inspect it before you rule.
                {!staleAck ? (
                  <button className={styles.staleBtn} type="button" onClick={() => setStaleAck(true)}>
                    Rule on v{frozen} anyway
                  </button>
                ) : null}
              </div>
            ) : null}
            {drop.error ? (
              <p className={styles.uploadError} role="alert">
                Upload failed: {drop.error}. Your note is kept.
              </p>
            ) : null}
            <CriterionCard
              criterion={signoff.criterion}
              ticketId={signoff.ticket.id}
              attachments={staged}
              ruling={canRule ? { evidenceVersion: frozen, stale: newer } : undefined}
              onRuled={() => {
                onRuled?.();
                onClose();
              }}
            />
          </div>
        </div>
      ) : null}
    </Drawer>
  );
}
