import { useRef, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getReviewContext, decideDesign, commentDocument } from "../api/review";
import type { SendMessage } from "../api/endpoints";
import type { MessageSent } from "../api/types";
import { identity } from "../auth/identity";
import { Composer } from "./Composer";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import ui from "./ui.module.css";
import styles from "./DesignReview.module.css";
import { readDraft, writeDraft } from "./draftStorage";
import { pendingWork } from "./PendingNavigation";

// Actor/source/version-local drafts; isolated in this tab's session storage.
export function DesignReview({ docId, version, source, request, children, onLatest, title }: {
  docId: string; version: number; source: string; request?: string | null; children?: React.ReactNode; onLatest?: (version: number) => void; title?: string;
}): React.JSX.Element {
  const key = `${identity()}:${source}:${docId}:${version}`;
  const draft = useRef(readDraft(key) ?? { text: "", artifacts: [] });
  const [mode, setMode] = useState<"comment" | "request_changes" | null>(draft.current.text ? draft.current.mode ?? "comment" : null);
  const [dirty, setDirty] = useState(Boolean(draft.current.text || draft.current.artifacts.length));
  const [sent, setSent] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const action = useRef<{ signature: string; key: string } | null>(draft.current.pendingAction ?? null);
  const qc = useQueryClient();
  const context = useQuery({ queryKey: ["review-context", source, docId, version, request], queryFn: () => getReviewContext(docId, source, version, request), retry: false });
  function idempotency(signature: string) {
    if (action.current?.signature !== signature) action.current = { signature, key: crypto.randomUUID() };
    draft.current.pendingAction = action.current;
    writeDraft(key, { ...draft.current, mode: mode ?? undefined });
    return action.current.key;
  }
  const approve = useMutation({
    mutationFn: () => decideDesign({ ticket_id: source, design_ref: docId, reviewed_version: version,
      gate_event_id: context.data!.gate_event_id!, decision: "approve", idempotency_key: idempotency(`approve:${context.data!.gate_event_id}`) }),
    onSuccess: () => { setSent(true); void context.refetch(); void qc.invalidateQueries({ queryKey: ["epic", source] }); },
    onError: () => { void context.refetch(); },
  });
  async function submit(body: SendMessage) {
    const common = { ticket_id: source, design_ref: docId, reviewed_version: version, artifacts: body.artifacts,
      idempotency_key: idempotency(JSON.stringify({ mode, text: body.text, artifacts: body.artifacts, gate: mode === "request_changes" ? context.data?.gate_event_id : null })) };
    const result = await (mode === "request_changes"
      ? decideDesign({ ...common, gate_event_id: context.data!.gate_event_id!, decision: "request_changes", feedback: body.text })
      : commentDocument({ ...common, text: body.text })).catch((error) => { void context.refetch(); throw error; });
    setSent(mode === "request_changes"); action.current = null;
    void context.refetch();
    delete draft.current.pendingAction;
    writeDraft(key, draft.current);
    return { ...result, value: { id: result.value.message_id, unresolved_mentions: result.value.unresolved_mentions ?? [] } as unknown as MessageSent,
      hint: (mode === "request_changes" ? "Changes requested in the source conversation. Design remains unapproved." : "Comment posted to the source conversation.") + (result.value.delivery_note ? ` ${result.value.delivery_note}` : "") };
  }
  if (context.isPending) return <p>Checking document context…</p>;
  if (context.isError) return <><p role="alert">Cannot use this source for review: {context.error.message}. The document remains readable. <Link to={`/doc/${encodeURIComponent(docId)}?version=${version}`}>Select a linked conversation source</Link></p>{children}</>;
  const ctx = context.data;
  const sourcePath = `/${ctx.source_kind === "epic" ? "epic" : "ticket"}/${encodeURIComponent(source)}`;
  const reviewOpen = Boolean(ctx.can_review && ctx.gate_event_id);
  const stateLine = [`Version ${version}`, version !== ctx.current_version ? `latest is v${ctx.current_version}` : "Latest", reviewOpen ? "Review requested" : null].filter(Boolean).join(" · ");
  // Header per revision3-clean-review.png: source / Design review crumb, the document title with a
  // "Design · Version N · state" line, and the two review actions on the right.
  return <section className={styles.review} aria-label="Document review" data-busy={approve.isPending ? "true" : undefined}>
    <div className={styles.head}>
      <nav className={styles.crumb} aria-label="Review source">
        <Icon name="design" size={18} />
        <Link to={sourcePath} aria-label={`Back to source: ${ctx.source_title}`}>{ctx.source_title}</Link>
        <span aria-hidden="true">/</span>
        <span>Design review</span>
      </nav>
      <div className={styles.titleRow}>
        <div className={styles.titleBlock}>
          {title ? <h1 className={styles.title} data-testid="review-title">{title}</h1> : null}
          <p className={styles.state} data-testid="review-state">Design · {stateLine}</p>
        </div>
        <div className={styles.actions}>
          {reviewOpen ? <>
            <button className={`${ui.button} ${styles.approve}`} disabled={!ctx.can_approve || dirty || approve.isPending || sent} onClick={() => { if (!pendingWork()) approve.mutate(); }}><Icon name="check" size={16} /> Approve design</button>
            <button className={`${ui.button} ${styles.request}`} disabled={!ctx.can_approve || approve.isPending} onClick={() => { if (!pendingWork()) { setMode("request_changes"); setSent(false); } }}>Request changes</button>
          </> : <span className={styles.muted}>No active review available for this viewer.</span>}
          <button className={ui.button} onClick={() => { if (!pendingWork()) { setMode("comment"); setSent(false); } }}>Comment without requesting changes</button>
        </div>
      </div>
    </div>
    {version !== ctx.current_version ? <p role="status" className={styles.notice}>Historical version — comments are allowed; approval requires the current version. {onLatest ? <button className={ui.button} onClick={() => onLatest(ctx.current_version)}>Review latest version (this version’s draft is kept)</button> : null}</p> : null}
    {approve.isError ? <p role="alert" className={styles.notice}>{approve.error.message}</p> : null}
    {sent && !mode ? <p role="status" className={styles.notice}>Design approved at v{version}.</p> : null}
    <div className={mode && !expanded ? styles.split : undefined}>
    <div className={styles.reading}>{children}</div>
    {mode ? <div className={expanded ? styles.expanded : styles.feedback}>
      <h2 className={styles.feedbackTitle}>{mode === "request_changes" ? "Request changes" : "Document comment"}</h2>
      <p className={styles.feedbackMeta}>To the {ctx.source_title} conversation<br />Regarding: {title ?? docId} · v{version}</p>
      <p className={styles.feedbackTo}><span>To</span> <span className={styles.toChip}><Avatar id="architect" size={20} /> architect</span></p>
      <p className={styles.feedbackAction}><span>Action</span> <strong>{mode === "request_changes" ? "Request changes" : "Comment"}</strong></p>
      <Composer ticketId={source} to="architect" lockRecipient hideRecipient kinds={mode === "request_changes" ? ["steer"] : ["note"]}
        submit={submit} initialText={draft.current.text} initialArtifacts={draft.current.artifacts}
        onDirtyChange={setDirty}
        onTextChange={(text) => { draft.current.text = text; writeDraft(key, { ...draft.current, mode: mode ?? undefined }); }}
        onArtifactsChange={(artifacts) => { draft.current.artifacts = artifacts; writeDraft(key, { ...draft.current, mode: mode ?? undefined }); }}
        expand={{ expanded, onToggle: () => setExpanded((x) => !x) }} />
      <p className={styles.feedbackNote}>Posts to the original {ctx.source_kind === "epic" ? "epic" : "ticket"} conversation. {mode === "request_changes" ? "This requests changes — it does not approve the design." : "A comment has no gate effect."}
        {mode === "request_changes" ? <> <button type="button" className={styles.linkButton} onClick={() => { if (!pendingWork()) setMode("comment"); }}>Comment instead, without requesting changes</button></> : null}</p>
      <p className={styles.feedbackNote}><Icon name="files" size={16} /> Your {ctx.source_kind === "epic" ? "epic" : "ticket"} draft is preserved.</p>
    </div> : null}
    </div>
  </section>;
}
