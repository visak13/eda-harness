// Typed endpoint functions for the G3a destinations (design §4.1/§4.2). One function per
// board view/write the Epics, Epic, Ticket, Doc and Library pages call. Reads unwrap via
// `api<T>()`; writes go through `postJson` so the Composer/verdict paths can read the board's
// resolution `hint`. Query strings are built here (never string-concatenated in the page) so a
// filter change is one place, and an absent filter is omitted rather than sent as "".
import { api, postJson } from "./client";
import type {
  ActivityDay,
  DocHtml,
  EpicPage,
  EpicSummaryRow,
  Library,
  MessageSent,
  TicketPage,
  TicketsTable,
} from "./types";

function qs(params: Record<string, string | number | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export type EpicsFilter = { status?: string | null; q?: string | null };
export const getEpicsSummary = (f: EpicsFilter = {}) =>
  api<EpicSummaryRow[]>(`/v1/epics/summary${qs(f)}`);

export const getEpicPage = (id: string) => api<EpicPage>(`/v1/epics/${encodeURIComponent(id)}/page`);

export type TicketsFilter = {
  epic?: string | null;
  status?: string | null;
  kind?: string | null;
  work_type?: string | null;
  assignee?: string | null;
  tag?: string | null;
  q?: string | null;
};
export const getTicketsTable = (f: TicketsFilter = {}) =>
  api<TicketsTable>(`/v1/tickets/table${qs(f)}`);

export const getTicketPage = (id: string) =>
  api<TicketPage>(`/v1/tickets/${encodeURIComponent(id)}/page`);

export const getDocHtml = (id: string, version?: number | null) =>
  api<DocHtml>(`/v1/docs/${encodeURIComponent(id)}/html${qs({ version })}`);

export const getActivity = (limit?: number) => api<ActivityDay[]>(`/v1/activity${qs({ limit })}`);

export const getLibrary = (epic?: string | null) => api<Library>(`/v1/library${qs({ epic })}`);

// ------------------------------------------------------------------ writes

export interface SendMessage {
  ticket_id: string;
  kind: string;
  text: string;
  to?: string | null;
  reply_to?: string | null;
}
/** POST /v1/messages — returns the sent message (with unresolved_mentions) and the board's
 *  recipient-resolution note (envelope hint), which the Composer shows verbatim. */
export const sendMessage = (b: SendMessage) => postJson<MessageSent>("/v1/messages", b);

export interface Verdict {
  criterion_id: string;
  verdict: "pass" | "fail";
  evidence_version: number;
  note?: string;
  ticket_id?: string | null;
  stale_ok?: boolean;
}
/** POST /v1/me/verdict — the one-click sign-off (design §14). evidence_version is required and
 *  names the doc version read; the board refuses a stale version unless stale_ok is passed. */
export const postVerdict = (b: Verdict) =>
  postJson<{ criterion: Record<string, unknown>; message: string }>("/v1/me/verdict", b);
