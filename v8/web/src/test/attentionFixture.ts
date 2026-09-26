import { http, HttpResponse } from "msw";
import type { Attention, AttentionItem, AttentionScope } from "../api/attention";

// S20 attention trail: one fixture every surface's spec renders from — an epic (epic-1) waiting on the viewer for a
// question on its own thread, a scope decision (Actions), a design sign-off (Design), an evidence sign-off on story
// s-1 (Work → s-1 → Files) and a question on story s-1 (Work → s-1 → thread); a Library topic question; a help
// thread fix; an access request (Admin). Shaped exactly like GET /v1/me/attention (edp8/attention.py).

const epic = { type: "epic" as const, id: "epic-1", title: "Galaxy site" };
const story = { id: "s-1", title: "Ship sheet" };

function item(p: Partial<AttentionItem> & Pick<AttentionItem, "kind" | "id" | "tab" | "section" | "at" | "url">): AttentionItem {
  return { since: "2026-09-27T00:00:00Z", label: p.kind, noun: p.kind, scope: epic, ticket: null,
    item: { type: p.kind === "ask" ? "message" : p.kind, id: p.id }, ...p };
}

export const ITEMS: AttentionItem[] = [
  item({ kind: "ask", id: "m-epicq", noun: "question", tab: "thread", section: "asks", at: { tab: "thread", section: "asks" },
    url: "/ui/epic/epic-1#m-epicq" }),
  item({ kind: "gate", id: "ev-scope", noun: "scope decision", tab: "actions", section: "decisions",
    at: { tab: "actions", section: "decisions" }, item: { type: "gate", id: "ev-scope", gate: "scope" },
    url: "/ui/epic/epic-1?request=ev-scope" }),
  item({ kind: "gate", id: "ev-design", noun: "design sign-off", tab: "design", section: "signoff",
    at: { tab: "design", section: "signoff" }, item: { type: "gate", id: "ev-design", gate: "design_signoff" },
    url: "/ui/epic/epic-1?request=ev-design" }),
  item({ kind: "signoff", id: "c-1", noun: "sign-off", tab: "work", section: "tickets", ticket: story,
    at: { tab: "files", section: "evidence" }, item: { type: "criterion", id: "c-1", doc: "report-1" },
    url: "/ui/ticket/s-1?doc=report-1#c-1" }),
  item({ kind: "ask", id: "m-storyq", noun: "question", tab: "work", section: "tickets", ticket: story,
    at: { tab: "thread", section: "asks" }, url: "/ui/ticket/s-1#m-storyq" }),
  item({ kind: "ask", id: "m-topicq", noun: "question", scope: { type: "topic", id: "topic-1", title: "Rendering" },
    tab: "thread", section: "asks", at: { tab: "thread", section: "asks" }, url: "/ui/library/topics/topic-1#m-topicq" }),
  item({ kind: "fix", id: "fix-1", noun: "fix to approve", scope: { type: "help", id: "topic-h1", title: "Board is slow" },
    tab: "fixes", section: "fixes", at: { tab: "fixes", section: "fixes" }, url: "/ui/library/topics/topic-h1#fix-1" }),
  item({ kind: "access_request", id: "ar-1", noun: "access request", scope: { type: "admin", id: "admin", title: "Admin" },
    tab: "teammates", section: "requests", at: { tab: "teammates", section: "requests" }, url: "/ui/admin?tab=teammates#ar-1" }),
];

function scope(s: AttentionItem["scope"], reason: string): AttentionScope {
  const rows = ITEMS.filter((i) => i.scope.id === s.id);
  const tabs: Record<string, number> = {};
  const sections: Record<string, number> = {};
  const tickets: Record<string, number> = {};
  for (const r of rows) {
    tabs[r.tab] = (tabs[r.tab] ?? 0) + 1;
    sections[`${r.tab}/${r.section}`] = (sections[`${r.tab}/${r.section}`] ?? 0) + 1;
    if (r.ticket) tickets[r.ticket.id] = (tickets[r.ticket.id] ?? 0) + 1;
  }
  return { ...s, count: rows.length, reason, latest: "2026-09-27T00:00:00Z", tabs, sections, tickets };
}

export const ATTENTION: Attention = {
  participant: "owner",
  items: ITEMS,
  scopes: [
    scope(epic, "2 questions, 1 scope decision, 1 design sign-off, 1 sign-off"),
    scope({ type: "topic", id: "topic-1", title: "Rendering" }, "1 question"),
    scope({ type: "help", id: "topic-h1", title: "Board is slow" }, "1 fix to approve"),
    scope({ type: "admin", id: "admin", title: "Admin" }, "1 access request"),
  ],
  counts: { total: 8, epics: 5, topics: 1, help: 1, admin: 1 },
};

/** The attention read answering with `value` (the full fixture by default). */
export const attentionHandler = (value: Attention = ATTENTION) =>
  http.get("/v1/me/attention", () => HttpResponse.json({ ok: true, value }));

/** The fixture after `ids` were answered: their items leave the list, as the board derives it. */
export function without(...ids: string[]): Attention {
  const items = ATTENTION.items.filter((i) => !ids.includes(i.id));
  const scopes = ATTENTION.scopes
    .map((s) => ({ ...s, count: items.filter((i) => i.scope.id === s.id).length }))
    .filter((s) => s.count > 0);
  const by = (t: string) => items.filter((i) => i.scope.type === t).length;
  return { ...ATTENTION, items, scopes,
    counts: { total: items.length, epics: by("epic") + by("quick"), topics: by("topic"), help: by("help"), admin: by("admin") } };
}
