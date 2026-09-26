import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approveFix, getFixes, rejectFix, type FixProposal } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import ui from "./ui.module.css";

// S19 (design-e963c656f5 §4.14(e).5): the Help seat's proposed fixes as admin approval cards. Each card
// shows the exact route call Approve runs; nothing runs until an admin presses Approve, and a decided
// fix never runs again (the board refuses with 409). A non-admin gets 403 from /v1/fixes, so the cards
// simply do not render for them. On Needs you the cards list every open proposal; on a help thread
// (topicId) they list that thread's.

export function FixCards({ topicId }: { topicId?: string }): React.JSX.Element | null {
  const q = useQuery({
    queryKey: ["fixes", topicId ?? "all"],
    queryFn: () => getFixes({ status: "proposed", topic_id: topicId ?? null }),
    retry: false,
    refetchInterval: 10000,
  });
  if (q.isError && q.error instanceof BoardApiError && q.error.status === 403) return null;
  if (!q.data || q.data.length === 0) return null;
  return (
    <section aria-label="Fixes to approve" data-testid="fix-cards">
      <h2 className={ui.sectionLabel}>Fixes the Help seat proposes</h2>
      {q.data.map((f) => <FixCard key={f.id} fix={f} linkThread={!topicId} />)}
    </section>
  );
}

function FixCard({ fix, linkThread }: { fix: FixProposal; linkThread: boolean }): React.JSX.Element {
  const qc = useQueryClient();
  const [done, setDone] = useState<string | null>(null);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["fixes"] }); void qc.invalidateQueries({ queryKey: ["topic", fix.topic_id] }); };
  const approve = useMutation({
    mutationFn: () => approveFix(fix.id),
    onSuccess: (r) => {
      const f = r.value.fix;
      setDone(`${f.status === "applied" ? "Applied" : "Failed"}: HTTP ${f.result?.http_status ?? "?"}. The result is on the help thread.`);
      refresh();
    },
    onError: refresh,
  });
  const reject = useMutation({
    mutationFn: () => rejectFix(fix.id),
    onSuccess: () => { setDone("Rejected: nothing ran."); refresh(); },
    onError: refresh,
  });
  const busy = approve.isPending || reject.isPending || done !== null;
  const err = approve.error ?? reject.error;
  const body = fix.request.body && Object.keys(fix.request.body as object).length ? JSON.stringify(fix.request.body) : "";
  return (
    <article className={ui.card} data-testid="fix-card" data-fix={fix.id}>
      <p><strong>{fix.effect}</strong></p>
      <p className={ui.metaRow}>
        Runs exactly: <code data-testid="fix-request">{fix.request.method} {fix.request.path}{body ? ` ${body}` : ""}</code>
      </p>
      <p className={ui.metaRow}>
        Proposed by {fix.created_by} ({fix.action.kind})
        {linkThread ? <> · <Link to={`/library/topics/${encodeURIComponent(fix.topic_id)}`}>help thread</Link></> : null}
      </p>
      {done ? <p role="status" data-testid="fix-done">{done}</p> : (
        <div>
          <button type="button" className={ui.buttonPrimary} disabled={busy} data-testid="fix-approve"
            onClick={() => approve.mutate()}>Approve</button>{" "}
          <button type="button" className={ui.button} disabled={busy} data-testid="fix-reject"
            onClick={() => reject.mutate()}>Reject</button>
        </div>
      )}
      {err ? <p className={ui.banner} role="alert">{(err as BoardApiError).hint || (err as Error).message}</p> : null}
    </article>
  );
}
