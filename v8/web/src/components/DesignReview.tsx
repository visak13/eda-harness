import { useRef, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getReviewContext, decideDesign, commentDocument } from "../api/review";
import type { SendMessage } from "../api/endpoints";
import type { MessageSent } from "../api/types";
import { identity } from "../auth/identity";
import { Composer } from "./Composer";
import { useDrawerClose } from "./Drawer";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import ui from "./ui.module.css";
import styles from "./DesignReview.module.css";
import { readDraft, writeDraft } from "./draftStorage";
import { pendingWork } from "./PendingNavigation";

// Actor/source/version-local drafts; isolated in this tab's session storage.
export function DesignReview({ docId, version, source, request, children, onLatest, title, versions, onPickVersion, tabHref, onBack }: {
  docId: string; version: number; source: string; request?: string | null; children?: React.ReactNode; onLatest?: (version: number) => void; title?: string;
  /** Every version of the doc: the state line's "Version N" menu (revision3-clean-review.png). */
  versions?: number[]; onPickVersion?: (version: number) => void;
  /** In the viewer: the "Open in tab" target. The dedicated page has none. */
  tabHref?: string;
  /** A nested doc in the viewer: back to the doc that linked it. */
  onBack?: () => void;
}): React.JSX.Element {
  const close = useDrawerClose();
  const menuRef = useRef<HTMLDetailsElement>(null);
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
  // S19 D2/D9: the viewer has ONE header — this crumb row carries Open in tab and a labelled Close.
  const tools = <div className={styles.tools}>
    {tabHref ? <Link className={styles.tool} to={tabHref} target="_blank">Open in tab <Icon name="external" size={18} /></Link> : null}
    {close ? <button type="button" className={styles.tool} onClick={close}><Icon name="close" size={18} /> Close</button> : null}
  </div>;
  const back = onBack ? <button type="button" className={styles.back} aria-label="Back" onClick={onBack}>‹</button> : null;
  const framed = close ? `${styles.review} ${styles.framed}` : styles.review;
  if (context.isPending) return <section className={framed}><div className={styles.head}><div className={styles.crumbRow}><span className={styles.crumb}>{back}Checking document context…</span>{tools}</div></div></section>;
  if (context.isError) return <section className={framed}><div className={styles.head}><div className={styles.crumbRow}><span className={styles.crumb}>{back}{title ?? docId}</span>{tools}</div></div><div className={styles.plainScroll}><p role="alert" className={styles.notice}>Cannot use this source for review: {context.error.message}. The document remains readable. <Link to={`/doc/${encodeURIComponent(docId)}?version=${version}`}>Select a linked conversation source</Link></p>{children}</div></section>;
  const ctx = context.data;
  const sourcePath = `/${ctx.source_kind === "epic" ? "epic" : "ticket"}/${encodeURIComponent(source)}`;
  const reviewOpen = Boolean(ctx.can_review && ctx.gate_event_id);
  const latestNote = version !== ctx.current_version ? `latest is v${ctx.current_version}` : null;
  const reviewNote = reviewOpen ? "Review requested" : null;
  const multi = (versions?.length ?? 0) > 1 && onPickVersion;
  // "Design · Version 3 · Review requested" (render). The version IS the menu: no second toolbar.
  const versionMenu = multi ? <details ref={menuRef} className={styles.versionsMenu} aria-label="Versions" data-testid="doc-versions-menu">
    <summary className={styles.versionsSummary} data-testid="version-now">Version {version} <Icon name="chevron" size={16} /></summary>
    <div className={styles.versionsList}>
      {versions!.map((v) => <button key={v} type="button" data-testid="version-entry" aria-pressed={v === version}
        className={`${styles.versionEntry} ${v === version ? styles.versionActive : ""}`}
        onClick={() => { if (pendingWork()) return; onPickVersion!(v); if (menuRef.current) menuRef.current.open = false; }}>
        Version {v}{v === ctx.current_version ? " · latest" : ""}</button>)}
    </div>
  </details> : <span data-testid="version-now">Version {version}</span>;
  const composeLabel = mode === "request_changes" ? "Request changes" : "Comment";
  const helpText = mode === "request_changes" ? "Request changes posts a steer to the architect in the source conversation; the design stays unapproved." : "A comment posts a note to the architect in the source conversation; it has no gate effect.";
  const where = ctx.source_kind === "epic" ? "epic" : "ticket";
  // Layout per revision3-clean-review.png: one header (crumb + Open in tab + Close, then the title
  // with its "Design · Version N · state" line and the two review actions), then the document and
  // the review panel side by side. The document column never changes width (S19 D6).
  return <section className={framed} aria-label="Document review" data-busy={approve.isPending ? "true" : undefined}>
    <div className={styles.head}>
      <div className={styles.crumbRow}>
        <nav className={styles.crumb} aria-label="Review source">
          {back}
          <Icon name="design" size={18} />
          <Link to={sourcePath} aria-label={`Back to source: ${ctx.source_title}`}>{ctx.source_title}</Link>
          <span aria-hidden="true">/</span>
          <span>Design review</span>
        </nav>
        {tools}
      </div>
      <div className={styles.titleRow}>
        <div className={styles.titleBlock}>
          {title ? <h1 className={styles.title} data-testid="review-title">{title}</h1> : null}
          <p className={styles.state} data-testid="review-state">Design · {versionMenu}{latestNote ? <> · {latestNote}</> : null}{reviewNote ? <> · {reviewNote}</> : null}</p>
        </div>
        {reviewOpen ? <div className={styles.actions}>
          {/* Approve stays disabled while unsent feedback exists: approving would strand the note (S19 D8, kept on purpose). */}
          <button className={`${ui.button} ${styles.approve}`} disabled={!ctx.can_approve || dirty || approve.isPending || sent} title={dirty ? "Send or cancel your feedback before approving" : undefined} onClick={() => { if (!pendingWork()) approve.mutate(); }}><Icon name="check" size={18} /> Approve design</button>
          <button className={`${ui.button} ${styles.request}`} disabled={!ctx.can_approve || approve.isPending} onClick={() => { if (!pendingWork()) { setMode("request_changes"); setSent(false); } }}>Request changes</button>
        </div> : null}
      </div>
    </div>
    <div className={expanded && mode ? `${styles.split} ${styles.splitExpanded}` : styles.split}>
      <div className={styles.reading}>
        {version !== ctx.current_version ? <p role="status" className={styles.notice}>Historical version — comments are allowed; approval requires the current version. {onLatest ? <button className={ui.button} onClick={() => onLatest(ctx.current_version)}>Review latest version (this version’s draft is kept)</button> : null}</p> : null}
        {approve.isError ? <p role="alert" className={styles.notice}>{approve.error.message}</p> : null}
        {sent && !mode ? <p role="status" className={styles.notice}>Design approved at v{version}.</p> : null}
        {children}
      </div>
      <aside className={styles.feedback} aria-label={mode ? composeLabel : "Your review"}>
        {mode ? <>
          <h2 className={styles.feedbackTitle}>{mode === "request_changes" ? "Request changes" : "Document comment"}</h2>
          <p className={styles.feedbackMeta}>To the {ctx.source_title} conversation<br />Regarding: {title ?? docId} · v{version}</p>
          <p className={styles.feedbackTo}><span>To</span> <span className={styles.toChip}><Avatar id="architect" size={24} /> architect</span></p>
          <p className={styles.feedbackAction}><span>Action</span> <strong>{composeLabel}</strong>
            <span className={styles.help} tabIndex={0} role="img" aria-label={helpText} title={helpText}><Icon name="help" size={18} /></span></p>
          <Composer ticketId={source} to="architect" lockRecipient hideRecipient kinds={mode === "request_changes" ? ["steer"] : ["note"]}
            variant="panel" sendLabel={mode === "request_changes" ? "Send feedback" : "Send comment"}
            onCancel={() => { if (pendingWork()) return; draft.current = { text: "", artifacts: [] }; writeDraft(key, draft.current); setDirty(false); setExpanded(false); setMode(null); }}
            submit={submit} initialText={draft.current.text} initialArtifacts={draft.current.artifacts}
            onDirtyChange={setDirty}
            onTextChange={(text) => { draft.current.text = text; writeDraft(key, { ...draft.current, mode: mode ?? undefined }); }}
            onArtifactsChange={(artifacts) => { draft.current.artifacts = artifacts; writeDraft(key, { ...draft.current, mode: mode ?? undefined }); }}
            expand={{ expanded, onToggle: () => setExpanded((x) => !x) }} />
          <div className={styles.feedbackFoot}>
            <p className={styles.feedbackNote}>Posts to the original {where} conversation. {mode === "request_changes" ? "This requests changes—it does not approve the design." : "A comment has no gate effect."}</p>
            {mode === "request_changes" ? <button type="button" className={styles.linkButton} onClick={() => { if (!pendingWork()) setMode("comment"); }}>Comment without requesting changes</button> : null}
            <p className={styles.feedbackNote}><Icon name="files" size={16} /> Your {where} draft is preserved.</p>
          </div>
        </> : <>
          <h2 className={styles.feedbackTitle}>Your review</h2>
          <p className={styles.feedbackMeta}>{reviewOpen ? `The architect asked you to review version ${version}. Approve it, or request changes — the feedback box opens here, beside the design.` : "No review is open on this version for you. You can still comment."}</p>
          <div className={styles.feedbackFoot}>
            <p className={styles.feedbackNote}>Feedback posts to the original {where} conversation, addressed to the architect. You stay in this viewer.</p>
            <button type="button" className={styles.linkButton} onClick={() => { if (!pendingWork()) { setMode("comment"); setSent(false); } }}>Comment without requesting changes</button>
            <p className={styles.feedbackNote}><Icon name="files" size={16} /> Your {where} draft is preserved.</p>
          </div>
        </>}
      </aside>
    </div>
  </section>;
}
