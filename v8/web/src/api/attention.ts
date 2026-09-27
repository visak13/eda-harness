import { useQuery } from "@tanstack/react-query";
import { api, postJson } from "./client";

// S20 attention trail (design-e963c656f5 §4.18): GET /v1/me/attention is the ONE list of what waits on the viewer,
// each item with its path — scope (epic | quick | topic | admin) → tab (a page opener: actions | design | files | work,
// or the page's own thread / fixes) → section → ticket row → item. Every dot in the app reads this list through the
// helpers below; no surface computes its own rule. A board without the route (older build) yields no dots.

export type AttentionTab = "actions" | "design" | "files" | "work" | "thread" | "fixes" | "teammates";

export interface AttentionItem {
  kind: "ask" | "gate" | "signoff" | "fix" | "access_request";
  id: string;
  since: string;
  label: string;
  noun: string;
  /** `help` is a help thread: a topic the Library never lists, reached from the rail's Ask for help. */
  scope: { type: "epic" | "quick" | "topic" | "help" | "admin"; id: string; title: string };
  tab: AttentionTab;
  section: string;
  /** The child ticket holding the item (a story or a task: the epic's Work tree lists both as rows). */
  ticket: { id: string; title: string } | null;
  /** Where the item sits on the page that holds it (the ticket page for a child ticket's item). */
  at: { tab: AttentionTab; section: string };
  item: { type: string; id: string; gate?: string; doc?: string | null };
  url: string;
}

export interface AttentionScope {
  type: AttentionItem["scope"]["type"];
  id: string;
  title: string;
  count: number;
  reason: string;
  latest: string;
  tabs: Record<string, number>;
  sections: Record<string, number>;
  tickets: Record<string, number>;
}

export interface Attention {
  participant: string;
  items: AttentionItem[];
  scopes: AttentionScope[];
  counts: { total: number; epics: number; topics: number; help: number; admin: number };
}

export const EMPTY_ATTENTION: Attention = {
  participant: "", items: [], scopes: [], counts: { total: 0, epics: 0, topics: 0, help: 0, admin: 0 },
};

/** The ["me", …] key: the live feed refetches it on every board event, so a dot clears once its item is answered. */
export const ATTENTION_KEY = ["me", "attention"] as const;

export const getAttention = () => api<Attention>("/v1/me/attention");

export function useAttention(): Attention {
  const q = useQuery({ queryKey: ATTENTION_KEY, queryFn: getAttention, retry: false });
  const d = q.data;
  return d && Array.isArray(d.items) && Array.isArray(d.scopes) && d.counts ? d : EMPTY_ATTENTION;
}

/** The items a page holds: on an epic/quick/topic page its own and its tickets' (they sit behind Work); on a child
 *  ticket's page its own, at their opener. `tab`/`section` are resolved for THIS page. */
export interface PageItem extends AttentionItem { pageTab: AttentionTab; pageSection: string }

export function pageItems(att: Attention, pageId: string): PageItem[] {
  const out: PageItem[] = [];
  for (const it of att.items) {
    if (it.ticket?.id === pageId) out.push({ ...it, pageTab: it.at.tab, pageSection: it.at.section });
    else if (it.scope.id === pageId) out.push({ ...it, pageTab: it.tab, pageSection: it.section });
  }
  return out;
}

/** The asks waiting on the viewer in THIS page's own thread (not its child tickets'), oldest first. */
export function threadAsks(att: Attention, pageId: string): PageItem[] {
  return pageItems(att, pageId).filter((i) => i.kind === "ask" && i.pageTab === "thread");
}

/** The newest item waiting on a ticket row: the Work drawer's row link lands on it (steer m-4ed69369cb). */
export function newestFor(items: PageItem[], ticketId: string): PageItem | undefined {
  return items.filter((i) => i.pageTab === "work" && i.ticket?.id === ticketId)
    .reduce<PageItem | undefined>((a, b) => (!a || b.since >= a.since ? b : a), undefined);
}

/** v34 item 6 (owner m-1a09573d3d): dismiss asks without replying. A pure attention write — no message, no seat
 *  woken; the caller refetches the ["me", …] reads so the dots, counts and highlights clear together. */
export const dismissAsks = (ids: string[]) =>
  postJson<{ dismissed: string[] }>("/v1/me/attention/dismiss", { ids }).then((r) => r.value);

export function countWhere(items: PageItem[], tab: AttentionTab, section?: string): number {
  return items.filter((i) => i.pageTab === tab && (section === undefined || i.pageSection === section)).length;
}

/** Items behind the Work opener on a scope page, per ticket row. */
export function ticketCount(items: PageItem[], ticketId: string): number {
  return items.filter((i) => i.pageTab === "work" && i.ticket?.id === ticketId).length;
}

/** The SPA path (no /ui prefix) that opens a scope's page. */
export function scopePath(s: Pick<AttentionScope, "type" | "id">): string {
  const id = encodeURIComponent(s.id);
  if (s.type === "topic" || s.type === "help") return `/library/topics/${id}`;
  if (s.type === "quick") return `/ticket/${id}`;
  if (s.type === "admin") return "/admin?tab=teammates";
  return `/epic/${id}`;
}

/** An item's deep link as an SPA path. */
export const itemPath = (it: Pick<AttentionItem, "url">) => it.url.replace(/^\/ui(?=\/)/, "");

export function attentionLabel(n: number): string {
  return `needs your attention: ${n}`;
}
