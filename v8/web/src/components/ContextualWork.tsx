import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { identity } from "../auth/identity";
import { useDocDrawer } from "./DocDrawer";
import { Icon } from "./Icon";
import ui from "./ui.module.css";
import styles from "./ContextualWork.module.css";

// The source-bound viewers behind the header's links row (design-a2e5369133 §Files/History):
// Files & evidence and History read GET /v1/tickets/{id}/contextual and render inside the one
// drawer (WorkHeader) or as the dedicated /records page (RecordsPage). An older board without the
// route degrades to a designed empty state with the board's reason, never a blank pane.

export interface WorkContext {
  ticket_id: string; title: string; kind: string; status: string; owner: string | null; requester: string; assignee: string | null;
  design_ref: string | null; scope: string; truncated: boolean;
  blockers?: { id: string; title: string; status: string }[];
  unresolved_asks?: { id: string; kind: string; to: string }[];
  gates: { id: string; data: { gate: string } }[];
  records: { type: string; group: string; relation: string; record: { id: string; title?: string; note?: string; version?: number; scope?: string; filename?: string } }[];
  events: { id: string; created_at: string; created_by: string; kind: string; data: Record<string, unknown> }[];
}

export function useWorkContext(ticketId: string, category = "all") {
  return useQuery({
    queryKey: ["contextual", ticketId, category],
    queryFn: () => api<WorkContext>(`/v1/tickets/${encodeURIComponent(ticketId)}/contextual?category=${encodeURIComponent(category)}`),
    retry: false,
  });
}

/** The header's "Needs attention" line: open gates, unanswered asks, blockers — board facts only. */
export function attentionLine(data: Pick<WorkContext, "gates" | "unresolved_asks" | "blockers" | "status">): string {
  return [
    ...data.gates.map((g) => g.data.gate.replaceAll("_", " ")),
    data.unresolved_asks?.length ? `${data.unresolved_asks.length} unanswered request${data.unresolved_asks.length === 1 ? "" : "s"}` : "",
    data.blockers?.length ? `Blocked by: ${data.blockers.map((b) => b.title).join(", ")}` : data.status === "blocked" ? "Blocked" : "",
  ].filter(Boolean).join(" · ");
}

function outcome(data: Record<string, unknown>): string {
  if (typeof data.text === "string") return data.text;
  if (typeof data.answer === "string") return data.answer;
  if (data.from && data.to) return `${String(data.from)} → ${String(data.to)}`.replaceAll("_", " ");
  if (data.verdict) return `Verdict: ${String(data.verdict)}`;
  if (typeof data.request === "object" && data.request) {
    const review = data.request as Record<string, unknown>;
    return `${String(review.decision ?? "Document comment").replaceAll("_", " ")} · ${String(review.design_ref)} v${String(review.reviewed_version)}`;
  }
  return typeof data.note === "string" ? data.note : "";
}

const GROUPS = ["Design", "References", "Evidence", "Deliverables", "Other"];

/** Files & evidence: records grouped, with a designed empty state (owner defect: blank pane). */
export function FilesViewer({ ticketId }: { ticketId: string }): React.JSX.Element {
  const query = useWorkContext(ticketId);
  const { openDoc } = useDocDrawer();
  if (query.isPending) return <p className={ui.empty}>Loading files…</p>;
  if (query.isError) return <Unavailable what="files" reason={(query.error as Error).message} />;
  const records = query.data.records;
  if (records.length === 0) {
    return <div className={styles.emptyState} data-testid="files-empty">
      <Icon name="files" size={24} />
      <h3>Nothing attached yet</h3>
      <p>Drop a file into the composer or press Attach on a message to add evidence here. Documents the architect links (design, strategy, notes) appear under Design and References.</p>
    </div>;
  }
  return <div className={styles.content}>
    {GROUPS.filter((g) => records.some((r) => r.group === g)).map((group) => <section key={group} className={styles.group}>
      <h3>{group}</h3>
      <ul className={styles.rows}>{records.filter((r) => r.group === group).map((r, i) => <li key={`${r.record.id}:${i}`} className={styles.row}>
        <Icon name={r.type === "doc" ? "design" : "attach"} size={18} />
        {r.type === "doc"
          ? <button className={styles.rowLink} onClick={() => openDoc(r.record.id)}>{r.record.title ?? r.record.id}{r.record.version ? ` · v${r.record.version}` : ""}</button>
          : <Link className={styles.rowLink} to={`/artifact/${encodeURIComponent(r.record.id)}`}>{r.record.filename || r.record.note || r.record.id}</Link>}
        <span className={styles.rowMeta}>{r.relation.replaceAll("_", " ")} · {r.record.scope === "global" || r.record.scope?.startsWith("domain:") ? "shared" : "this work"}</span>
      </li>)}</ul>
    </section>)}
  </div>;
}

/** History: the ticket's events by category, newest first, plain outcome lines. */
export function HistoryViewer({ ticketId }: { ticketId: string }): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "all";
  const query = useWorkContext(ticketId, category);
  return <div className={styles.content}>
    <label className={styles.category}>Show <select value={category} onChange={(e) => setParams((old) => { const p = new URLSearchParams(old); p.set("category", e.target.value); return p; }, { replace: true })}>
      {[["all", "All history"], ["conversation", "Conversation"], ["decisions", "Decisions"], ["status", "Status & assignments"], ["documents", "Documents/evidence"], ["activity", "Activity"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    {query.isPending ? <p className={ui.empty}>Loading history…</p> : null}
    {query.isError ? <Unavailable what="history" reason={(query.error as Error).message} /> : null}
    {query.data ? (query.data.events.length === 0
      ? <div className={styles.emptyState} data-testid="history-empty"><Icon name="history" size={24} /><h3>No events in this category yet</h3><p>Status moves, assignments, decisions and messages are recorded here as they happen.</p></div>
      : <>
        {query.data.truncated ? <p className={ui.empty}>Showing the newest 200 events in this category.</p> : null}
        <ol className={styles.events}>{query.data.events.map((event) => <li key={event.id} className={styles.event}>
          <div className={styles.eventHead}>
            <strong>{event.kind.replaceAll("_", " ")}</strong>
            <span>{String(event.data.by ?? event.data.from ?? (event.created_by || "Actor unknown"))}</span>
            <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time>
          </div>
          {outcome(event.data) ? <p>{outcome(event.data)}</p> : null}
          <details className={ui.fold}><summary>Technical details</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details>
        </li>)}</ol>
      </>) : null}
  </div>;
}

function Unavailable({ what, reason }: { what: string; reason: string }): React.JSX.Element {
  return <div className={styles.emptyState} role="alert" data-testid={`${what}-unavailable`}>
    <Icon name="warning" size={24} />
    <h3>This board cannot list {what} yet</h3>
    <p>{reason}. The board serving this page predates the records route; the conversation and actions still work.</p>
  </div>;
}

/** The dedicated /records/:id page ("Open in tab" from the drawer). */
export function ContextualWork({ ticketId, dedicated = false }: { ticketId: string; dedicated?: boolean }): React.JSX.Element {
  const [params] = useSearchParams();
  const view = params.get("view") === "history" ? "history" : "files";
  const query = useWorkContext(ticketId);
  const title = query.data?.title ?? ticketId;
  const source = `/${query.data?.kind === "epic" ? "epic" : "ticket"}/${encodeURIComponent(ticketId)}?as=${encodeURIComponent(identity())}`;
  return <section className={styles.dedicated} data-dedicated={dedicated || undefined}>
    <h1>{view === "history" ? "History" : "Files & evidence"} · {title}</h1>
    <p><Link to={source}>Back to source: {title}</Link></p>
    {view === "history" ? <HistoryViewer ticketId={ticketId} /> : <FilesViewer ticketId={ticketId} />}
  </section>;
}
