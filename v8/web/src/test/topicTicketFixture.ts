import { http, HttpResponse } from "msw";
import type { CriterionView, TicketPage } from "../api/types";

// S16: the ticket-page routes an owner's TopicPage reads beside /v1/topics/{id} (the topic IS a ticket of kind `topic`).

export function topicTicketPage(id: string, title: string, over: Partial<TicketPage> = {}): TicketPage {
  return {
    ticket: { id, kind: "topic", work_type: "knowledge", title, description: "", status: "in_progress", assignee: `sme.${id}`, tags: [], design_ref: null, epic_id: id },
    epic_id: id, epic_title: title, criteria: [], docs: [], thread: [], open_gates: [],
    assignee: { id: `sme.${id}`, handle: `sme.${id}`, role: "sme" },
    waiting_reason: { reason: "", presence: "alive", latest_status: "" },
    ...over,
  } as TicketPage;
}

export const SIGNOFF: CriterionView = { id: "c-t1", text: "The sme's notes cover test fixtures", check: "look", checked_by: "owner", verdict: "pending", evidence_ref: "note-t1", evidence_version: 1 } as CriterionView;

export function topicTicketHandlers(id: string, title: string, over: Partial<TicketPage> = {}) {
  const page = topicTicketPage(id, title, over);
  const ok = (value: unknown) => HttpResponse.json({ ok: true, value, hint: "" });
  return [
    http.get(`/v1/tickets/${id}/page`, () => ok(page)),
    http.get(`/v1/tickets/${id}/contextual`, () => ok({
      ticket_id: id, title, kind: "topic", status: page.ticket.status, owner: "owner", requester: "owner", assignee: page.ticket.assignee,
      blockers: [], unresolved_asks: [], design_ref: null, gates: [], scope: "", category: "all", records: [], events: [] })),
    http.get(`/v1/tickets/${id}/transitions`, () => ok({ status: page.ticket.status, transitions: [{ to: "done", allowed: true, reason: null }] })),
    http.get(`/v1/tickets/${id}/thread`, () => ok({ thread: [], thread_total: 0, thread_before: null })),
  ];
}

/** A topic page's thread rows as the ticket page serves them (the owner's topic page reads the ticket's thread). */
export function asTicketThread(rows: { id: string; created_at: string; created_by: string; to: string | null; kind: string; text: string; reply_to: string | null }[]): TicketPage["thread"] {
  return rows.map((m, i) => ({ seq: i + 1, id: m.id, by: m.created_by, to: m.to, kind: m.kind, text: m.text, at: m.created_at, reply_to: m.reply_to })) as TicketPage["thread"];
}
