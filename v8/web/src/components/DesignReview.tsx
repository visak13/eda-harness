import { useRef, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getReviewContext, decideDesign, commentDocument } from "../api/review";
import type { SendMessage } from "../api/endpoints";
import type { MessageSent } from "../api/types";
import { identity } from "../auth/identity";
import { Composer } from "./Composer";
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
  return <section className={styles.review} aria-label="Document review" data-busy={approve.isPending ? "true" : undefined}>
    <div className={styles.actions}>
      <Link to={sourcePath}>Back to source: {ctx.source_title}</Link>
      <span>{title ? <strong>{title} · </strong> : null}Reviewing v{version} · current v{ctx.current_version}</span>
      {ctx.can_review && ctx.gate_event_id ? <>
        <button className={ui.button} disabled={!ctx.can_approve || dirty || approve.isPending || sent} onClick={() => { if (!pendingWork()) approve.mutate(); }}>Approve design</button>
        <button className={ui.button} disabled={!ctx.can_approve || approve.isPending} onClick={() => { if (!pendingWork()) { setMode("request_changes"); setSent(false); } }}>Request changes</button>
      </> : <span>No active review available for this viewer.</span>}
      <button className={ui.button} onClick={() => { if (!pendingWork()) { setMode("comment"); setSent(false); } }}>Comment without requesting changes</button>
    </div>
    {version !== ctx.current_version ? <p role="status">Historical version — comments are allowed; approval requires the current version. {onLatest ? <button className={ui.button} onClick={() => onLatest(ctx.current_version)}>Review latest version (this version’s draft is kept)</button> : null}</p> : null}
    {approve.isError ? <p role="alert">{approve.error.message}</p> : null}
    {sent && !mode ? <p role="status">Design approved at v{version}.</p> : null}
    <div className={mode && !expanded ? styles.split : undefined}>
    <div className={styles.reading}>{children}</div>
    {mode ? <div className={expanded ? styles.expanded : styles.feedback}>
      <h2>{mode === "request_changes" ? "Request changes" : "Document comment"} · v{version}</h2>
      <p>Posts to {ctx.source_title}, addressed to architect. {mode === "request_changes" ? "This does not approve the design." : "No gate effect."}</p>
      <Composer ticketId={source} to="architect" lockRecipient kinds={mode === "request_changes" ? ["steer"] : ["note"]}
        submit={submit} initialText={draft.current.text} initialArtifacts={draft.current.artifacts}
        onDirtyChange={setDirty}
        onTextChange={(text) => { draft.current.text = text; writeDraft(key, { ...draft.current, mode: mode ?? undefined }); }}
        onArtifactsChange={(artifacts) => { draft.current.artifacts = artifacts; writeDraft(key, { ...draft.current, mode: mode ?? undefined }); }}
        expand={{ expanded, onToggle: () => setExpanded((x) => !x) }} />
    </div> : null}
    </div>
  </section>;
}
