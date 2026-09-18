import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { identity } from "../auth/identity";
import { Drawer } from "./Drawer";
import { useDocDrawer } from "./DocDrawer";
import { Icon } from "./Icon";
import ui from "./ui.module.css";
import styles from "./ContextualWork.module.css";
interface WorkContext {
  ticket_id: string; title: string; kind: string; status: string; owner: string | null; requester: string; assignee: string | null;
  design_ref: string | null; scope: string; truncated: boolean;
  blockers?: { id: string; title: string; status: string }[];
  unresolved_asks?: { id: string; kind: string; to: string }[];
  gates: { id: string; data: { gate: string } }[];
  records: { type: string; group: string; relation: string; record: { id: string; title?: string; note?: string; version?: number; scope?: string } }[];
  events: { id: string; created_at: string; created_by: string; kind: string; data: Record<string, unknown> }[];
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
export function ContextualWork({ ticketId, dedicated = false }: { ticketId: string; dedicated?: boolean }): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const { openDoc } = useDocDrawer();
  const view = params.get("view");
  const category = params.get("category") ?? "all";
  const query = useQuery({ queryKey: ["contextual", ticketId, category], queryFn: () => api<WorkContext>(`/v1/tickets/${encodeURIComponent(ticketId)}/contextual?category=${encodeURIComponent(category)}`) });
  const request = params.get("request");
  const openedRequest = useRef<string | null>(null);
  const gate = query.data?.gates.find((g) => g.id === request && g.data.gate === "design_signoff");
  useEffect(() => {
    if (gate && query.data?.design_ref && openedRequest.current !== request && !params.get("doc")) {
      openedRequest.current = request;
      setParams((old) => { const next = new URLSearchParams(old); next.set("doc", query.data!.design_ref!); return next; }, { replace: true });
    }
  }, [gate, query.data?.design_ref, request]); // route request opens the source-bound review, never answers it
  function choose(next: string | null) {
    setParams((old) => { const p = new URLSearchParams(old); if (next) p.set("view", next); else p.delete("view"); return p; });
  }
  if (query.isPending) return <p>Loading context…</p>;
  if (query.isError) return <p role="alert">Could not load context: {query.error.message}</p>;
  const data = query.data;
  const attention = [
    ...data.gates.map((g) => g.data.gate.replaceAll("_", " ")),
    data.unresolved_asks?.length ? `${data.unresolved_asks.length} unanswered request${data.unresolved_asks.length === 1 ? "" : "s"}` : "",
    data.blockers?.length ? `Blocked by: ${data.blockers.map((b) => b.title).join(", ")}` : data.status === "blocked" ? "Blocked" : "",
  ].filter(Boolean).join(" · ") || (data.unresolved_asks ? "No open requests" : "No open gates");
  const source = `/${data.kind === "epic" ? "epic" : "ticket"}/${encodeURIComponent(ticketId)}`;
  const content = <div className={styles.content}>
    <p>{data.scope}</p>
    <Link to={`${source}?as=${encodeURIComponent(identity())}`}>Back to source: {data.title}</Link>
    {!dedicated ? <Link target="_blank" rel="noopener" to={`/records/${encodeURIComponent(ticketId)}?${new URLSearchParams({ view: view ?? "files", category, as: identity() })}`}>Open in tab</Link> : null}
    {view === "history" ? <>
      <label>History category <select value={category} onChange={(e) => setParams((old) => { const p = new URLSearchParams(old); p.set("category", e.target.value); return p; })}>
        {[["all", "All history"], ["conversation", "Conversation"], ["decisions", "Decisions"], ["status", "Status & assignments"], ["documents", "Documents/evidence"], ["activity", "Activity"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      {data.truncated ? <p>Showing the newest 200 events in this category.</p> : null}
      <ul>{data.events.map((event) => <li key={event.id}>
        <strong>{event.kind.replaceAll("_", " ")}</strong> · {String(event.data.by ?? event.data.from ?? (event.created_by || "Actor unknown"))} · <time>{new Date(event.created_at).toLocaleString()}</time>
        {outcome(event.data) ? <p>{outcome(event.data)}</p> : null}
        <details><summary>Technical details</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details>
      </li>)}</ul>
    </> : ["Design", "References", "Evidence", "Deliverables", "Other"].map((group) => <section key={group}>
      <h2>{group}</h2>
      <ul>{data.records.filter((r) => r.group === group).map((r, i) => <li key={`${r.record.id}:${i}`}>
        {r.type === "doc" ? <button className={ui.button} onClick={() => openDoc(r.record.id)}>{r.record.title ?? r.record.id} {r.record.version ? `v${r.record.version}` : ""}</button> : <Link to={`/artifact/${encodeURIComponent(r.record.id)}`}>{r.record.note || r.record.id}</Link>}
        <span> {r.type} · {r.relation} · {r.record.scope === "global" || r.record.scope?.startsWith("domain:") ? "Shared/global" : ticketId}</span>
      </li>)}</ul>
    </section>)}
  </div>;
  if (dedicated) return <section><h1>{view === "history" ? "History" : "Files & evidence"} · {data.title}</h1>{content}</section>;
  return <>
    <dl className={styles.meta}><div><dt>Owner</dt><dd>{data.owner ?? "Unknown"}</dd></div><div><dt>Requester</dt><dd>{data.requester || "Unknown"}</dd></div><div><dt>Assigned</dt><dd>{data.assignee ?? "Unassigned"}</dd></div><div><dt>Attention</dt><dd>{attention}</dd></div></dl>
    <nav className={styles.links} aria-label="Work context">
      {data.design_ref ? <button className={ui.button} onClick={() => openDoc(data.design_ref!)}><Icon name="design" /> Design {data.gates.some((g) => g.data.gate === "design_signoff") ? "· review requested" : ""}</button> : null}
      <button className={ui.button} onClick={() => choose("files")}>Files & evidence</button>
      <button className={ui.button} onClick={() => choose("history")}>History</button>
      <a href="#work-details">Work</a>
    </nav>
    <Drawer open={!params.get("doc") && !params.get("compose") && (view === "files" || view === "history")} title={view === "history" ? "History" : "Files & evidence"} onClose={() => choose(null)}>{content}</Drawer>
  </>;
}
