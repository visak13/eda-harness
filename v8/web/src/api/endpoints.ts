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
  DocDiff,
  DocHtml,
  DocRecord,
  KnowledgeView,
  EpicPage,
  EpicSummaryRow,
  Library,
  MessageKind,
  MessageSent,
  PersonRow,
  ResolvedRow,
  ResolveResult,
  TicketPage,
  ThreadPage,
  TicketRecord,
  TicketsTable,
  TicketStatus,
  TicketTransitions,
  UploadedArtifact,
  ArtifactRecord,
  UserSettings,
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

export const getThreadPage = (id: string, before: number) =>
  api<ThreadPage>(`/v1/tickets/${encodeURIComponent(id)}/thread${qs({ before })}`);

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

/** GET /v1/artifacts/{id} — the artifact record (promise #20: the shareable /ui/artifact/:id page). */
export const getArtifact = (id: string) => api<ArtifactRecord>(`/v1/artifacts/${encodeURIComponent(id)}`);

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

/** POST /v1/artifacts/finalize (§18.1 finding 11). A file dropped on the ticket's Files card is
 *  attached straight onto the ticket — no message — so it is unstaged, linked `produced`, appears
 *  in Files & evidence and survives reload, instead of lingering staged until the 24 h sweep. */
export const finalizeArtifacts = (artifactIds: string[], ticketId: string) =>
  postJson<UploadedArtifact[]>("/v1/artifacts/finalize", { artifact_ids: artifactIds, ticket_id: ticketId });

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

/** PATCH /v1/docs/{id} — revise a doc's body/title/tags; the board records it as a new version. */
export const updateDoc = (id: string, b: { body_md?: string; title?: string; tags?: string[] }) =>
  postJson<Record<string, unknown>>(`/v1/docs/${encodeURIComponent(id)}`, b, "PATCH");

// ------------------------------------------------------------------ S-LIBRARY (design-34bf11cc07 §4.3)
/** GET /v1/knowledge — strategies, domains (all statuses, with linked tickets) and lessons. */
export const getKnowledge = () => api<KnowledgeView>("/v1/knowledge");
export const getDoc = (id: string) => api<DocRecord>(`/v1/docs/${encodeURIComponent(id)}`);
export const getDocDiff = (id: string) => api<DocDiff>(`/v1/docs/${encodeURIComponent(id)}/diff`);
/** POST /v1/docs — the owner authors a knowledge doc (active). */
export const createKnowledgeDoc = (b: { doc_type: string; title: string; body_md: string; tags: string[]; scope?: string }) =>
  postJson<DocRecord>("/v1/docs", { scope: "global", ...b });
/** Approve: a proposal for an active doc becomes its next version; a free-standing one becomes active. */
export const approveDoc = (id: string) =>
  postJson<{ doc: DocRecord; target: DocRecord | null }>(`/v1/docs/${encodeURIComponent(id)}/approve`, {});
export const rejectDoc = (id: string) =>
  postJson<{ doc: DocRecord; target: null }>(`/v1/docs/${encodeURIComponent(id)}/reject`, {});
/** POST /v1/library/import — one bounded server-side fetch of a skills.sh skill → a strategy_hl doc. */
export const importSkill = (b: { url: string; tags?: string[] }) =>
  postJson<{ doc: DocRecord; created: boolean; fetched: string }>("/v1/library/import", b);
/** DELETE /v1/links/{id} — unlink (e.g. a Library doc from an epic). */
export const deleteLink = (id: string) =>
  apiEnvelope<{ deleted: boolean }>(`/v1/links/${encodeURIComponent(id)}`, { method: "DELETE" });

/** GET / PUT /v1/me/settings — the Settings page (s-7f663c6322). Humans only; the board 403s a seat. */
export const getSettings = () => api<UserSettings>("/v1/me/settings");
export const putSettings = (b: UserSettings) => postJson<UserSettings>("/v1/me/settings", b, "PUT");
/** Ring the caller's own Slack with a test ping; the destination is read server-side from the
 *  stored settings, so the masked webhook the SPA holds is never sent. */
export const sendSlackTestPing = () => postJson<{ delivered: boolean }>("/v1/me/settings/slack/test", {});

/** Atomic explicit title + exact raw words. Omitting title preserves legacy caller behavior. */
export const createEpic = (words: string, choice?: EpicSeatChoice, title?: string) =>
  postJson<TicketRecord>("/v1/tickets", {
    kind: "epic",
    work_type: "feature",
    title: title === undefined ? words : title.trim(),
    words,
    // S-ROLES (design-34bf11cc07 §4.1): one model per role + the effort every spawn on this epic
    // inherits, recorded as `model:<role>=<id>` / `seat-effort:` tags (edp8/seat_choice.py).
    ...(choice ? { tags: epicChoiceTags(choice) } : {}),
  });

/** The per-role models and the epic-wide effort chosen in the new-epic dialog. */
export interface EpicSeatChoice {
  roleModels: Record<string, string>;
  effort: string;
}

export const epicChoiceTags = (c: EpicSeatChoice): string[] => [
  ...Object.entries(c.roleModels).filter(([r, m]) => r && m).map(([r, m]) => `model:${r}=${m}`),
  `seat-effort:${c.effort}`,
];

/** What POST /v1/quick-tasks returns: the new quick story, the engineer seat started on it (null when
 *  the pool refused the spawn after the create — `spawn_error` says why; the ticket stays open). */
export interface QuickTaskCreated {
  ticket: TicketRecord;
  seat: string | null;
  spawn_error?: string;
}

/** POST /v1/quick-tasks — S-QUICK (design-34bf11cc07 §4.2): the owner's one-step quick task. The board
 *  creates a parentless story tagged `quick` with the words verbatim, spawns `engineer.<story>` on the
 *  chosen engineer-catalog model and makes it the assignee. The model is sent only when picked. */
export const createQuickTask = (b: { title: string; words: string; model?: string | null }) =>
  postJson<QuickTaskCreated>("/v1/quick-tasks", {
    title: b.title.trim(),
    words: b.words,
    ...(b.model ? { model: b.model } : {}),
  });
