// Typed endpoint functions for the G3a destinations (design §4.1/§4.2). One function per
// board view/write the Epics, Epic, Ticket, Doc and Library pages call. Reads unwrap via
// `api<T>()`; writes go through `postJson` so the Composer/verdict paths can read the board's
// resolution `hint`. Query strings are built here (never string-concatenated in the page) so a
// filter change is one place, and an absent filter is omitted rather than sent as "".
import { api, apiEnvelope, postJson } from "./client";
import type {
  ActivityDay,
  ConversationRow,
  ReplyRow,
  DecisionsHome,
  DocHtml,
  EpicPage,
  EpicSummaryRow,
  Library,
  MessageKind,
  MessageSent,
  PersonRow,
  ResolvedRow,
  ResolveResult,
  TicketPage,
  TicketRecord,
  TicketsTable,
  TicketStatus,
  TicketTransitions,
  UploadedArtifact,
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

export const getEpicPage = (id: string, include?: string | null) =>
  api<EpicPage>(`/v1/epics/${encodeURIComponent(id)}/page${qs({ include })}`);

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

export const getTicketPage = (id: string, include?: string | null) =>
  api<TicketPage>(`/v1/tickets/${encodeURIComponent(id)}/page${qs({ include })}`);

export const getDocHtml = (id: string, version?: number | null) =>
  api<DocHtml>(`/v1/docs/${encodeURIComponent(id)}/html${qs({ version })}`);

export const getActivity = (limit?: number) => api<ActivityDay[]>(`/v1/activity${qs({ limit })}`);

export const getLibrary = (epic?: string | null) => api<Library>(`/v1/library${qs({ epic })}`);

// ------------------------------------------------------------------ Decisions home reads
export const getDecisions = () => api<DecisionsHome>("/v1/me/decisions");
export const getResolved = (limit?: number) => api<ResolvedRow[]>(`/v1/me/decisions/resolved${qs({ limit })}`);
export const getPeople = () => api<PersonRow[]>("/v1/me/people");
export const getConversations = () => api<ConversationRow[]>("/v1/me/conversations");
/** GET /v1/me/replies — replies to the viewer with the words they answer (human report m-3d3a36455f). */
export const getReplies = (limit?: number) => api<ReplyRow[]>(`/v1/me/replies${qs({ limit })}`);

// ------------------------------------------------------------------ writes

export interface SendMessage {
  ticket_id: string;
  kind: MessageKind;
  text: string;
  to?: string | null;
  reply_to?: string | null;
  artifacts?: string[];
}
/** POST /v1/messages — returns the sent message (with unresolved_mentions) and the board's
 *  recipient-resolution note (envelope hint), which the Composer shows verbatim. */
export const sendMessage = (b: SendMessage) => postJson<MessageSent>("/v1/messages", b);

/** POST /v1/messages/resolve — the wake preview (design §16.1). Nothing is sent; `wakes`/`plan`
 *  are the delivery plan the board WOULD use, so the preview cannot drift from delivery. */
export interface ResolveBody {
  ticket_id: string;
  to?: string | null;
  kind: MessageKind;
  /** The draft body — its @mentions join the preview exactly as they join delivery (round 2 #7). */
  text?: string;
}
export const resolveMessage = async (b: ResolveBody): Promise<ResolveResult> =>
  (await apiEnvelope<ResolveResult>("/v1/messages/resolve", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(b),
  })).value;

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
  postJson<{ criterion: Record<string, unknown>; message: string | null }>("/v1/me/verdict", b);

/** POST /v1/gates/{ticket}/{gate}/open — open a gate on a ticket (design §5, §16). The gate kind
 *  is the decision being asked for; the optional note frames it. The board wakes/holds as needed. */
export const openGate = (ticketId: string, gate: string, note: string) =>
  postJson<Record<string, unknown>>(
    `/v1/gates/${encodeURIComponent(ticketId)}/${encodeURIComponent(gate)}/open`,
    { note },
  );

/** POST /v1/gates/{ticket}/{gate}/answer — answer an open gate (design §5). */
export const answerGate = (ticketId: string, gate: string, answer: string) =>
  postJson<Record<string, unknown>>(
    `/v1/gates/${encodeURIComponent(ticketId)}/${encodeURIComponent(gate)}/answer`,
    { answer },
  );

/** POST /v1/artifacts/upload (multipart, design §18.1). The browser sets the multipart boundary,
 *  so we send FormData with NO content-type header. Returns the STAGED artifact; its id goes into
 *  the composer draft as `art-<id>` and is finalised when the message posts. */
export const uploadArtifact = async (
  file: File,
  ticketId: string,
  note = "",
): Promise<UploadedArtifact> => {
  const form = new FormData();
  form.append("file", file);
  form.append("ticket_id", ticketId);
  form.append("note", note);
  return (await apiEnvelope<UploadedArtifact>("/v1/artifacts/upload", { method: "POST", body: form })).value;
};

// The status edges the board offers THIS viewer on a ticket (the status control reads legality
// from the server, never a client copy of the rules — design §16, "one implementation").
export const getTicketTransitions = (id: string) =>
  api<TicketTransitions>(`/v1/tickets/${encodeURIComponent(id)}/transitions`);

/** PATCH /v1/tickets/{id} — the status move (and, where the board requires it, the assignee it is
 *  set with). Goes through postJson so a blocked move surfaces the board's resolution hint. */
export const patchTicket = (
  id: string,
  b: { status?: TicketStatus; assignee?: string | null; design_ref?: string | null },
) => postJson<TicketRecord>(`/v1/tickets/${encodeURIComponent(id)}`, b, "PATCH");

// Add an acceptance criterion to a ticket. The board DERIVES checked_by from the ticket (§24.1) and
// returns a hint when it overrides a passed-in value — the control shows that hint verbatim.
export const createCriterion = (b: {
  ticket_id: string;
  text: string;
  check: string;
  checked_by?: string | null;
}) => postJson<Record<string, unknown>>("/v1/criteria", b);

/** PATCH /v1/criteria/{id} — reword a criterion's text (the same route the verdict path uses). */
export const rewordCriterion = (id: string, text: string) =>
  postJson<Record<string, unknown>>(`/v1/criteria/${encodeURIComponent(id)}`, { text }, "PATCH");

/** POST /v1/links — attach a doc (or any object) to the ticket with a named relation. */
export const createLink = (b: { from_id: string; to_id: string; relation: string }) =>
  postJson<Record<string, unknown>>("/v1/links", b);

/** PATCH /v1/docs/{id} — revise a doc's body/title; the board records it as a new version. */
export const updateDoc = (id: string, b: { body_md?: string; title?: string }) =>
  postJson<Record<string, unknown>>(`/v1/docs/${encodeURIComponent(id)}`, b, "PATCH");
