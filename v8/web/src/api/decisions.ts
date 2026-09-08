// G2-owned typed endpoint functions for the Decisions surface (design §4.1/§4.2, §13, §14, §18.1).
// Self-contained on the envelope client (api/client.ts) so it never collides with G3a's
// api/endpoints.ts during the G2∥G3a parallel build (architect ruling m-1a5413aceb); G4 folds
// the two into one endpoints.ts. Reads unwrap via api<T>(); writes go through postJson so the
// composer/verdict paths can read the board's resolution `hint` verbatim (design §13).
import { api, apiEnvelope, postJson } from "./client";
import type {
  ConversationRow,
  DecisionsHome,
  DocHtml,
  EpicSummaryRow,
  MessageSent,
  PersonRow,
  ResolvedRow,
  Verdict,
} from "./types";
import type { MessageKind, ResolveResult, UploadedArtifact } from "./decisions.types";

function qs(params: Record<string, string | number | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

// ------------------------------------------------------------------ reads
export const getDecisions = () => api<DecisionsHome>("/v1/me/decisions");
export const getResolved = (limit?: number) => api<ResolvedRow[]>(`/v1/me/decisions/resolved${qs({ limit })}`);
export const getPeople = () => api<PersonRow[]>("/v1/me/people");
export const getConversations = () => api<ConversationRow[]>("/v1/me/conversations");
export const getEpicsSummary = () => api<EpicSummaryRow[]>("/v1/epics/summary");
export const getDocHtml = (id: string, version?: number | null) =>
  api<DocHtml>(`/v1/docs/${encodeURIComponent(id)}/html${qs({ version })}`);

// ------------------------------------------------------------------ writes
export interface SendMessageBody {
  ticket_id: string;
  kind: MessageKind;
  text: string;
  to?: string | null;
  reply_to?: string | null;
  artifacts?: string[];
}
/** POST /v1/messages — returns the sent message (with unresolved_mentions) AND the board's
 *  recipient-resolution note in `hint`, which the composer REPORTS verbatim (design §13). */
export const sendMessage = (b: SendMessageBody) => postJson<MessageSent>("/v1/messages", b);

export interface ResolveBody {
  ticket_id: string;
  to?: string | null;
  kind: MessageKind;
}
/** POST /v1/messages/resolve — the wake preview (design §16.1). Nothing is sent; `wakes`/`plan`
 *  are the delivery plan the board WOULD use, so the preview cannot drift from delivery. */
export const resolveMessage = async (b: ResolveBody): Promise<ResolveResult> =>
  (await apiEnvelope<ResolveResult>("/v1/messages/resolve", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(b),
  })).value;

export interface VerdictBody {
  criterion_id: string;
  verdict: Extract<Verdict, "pass" | "fail">;
  evidence_version: number; // required — the doc version the ruling read (design §14)
  note?: string;
  ticket_id?: string | null;
  stale_ok?: boolean;
}
/** POST /v1/me/verdict — one-click sign-off (design §14). The board refuses a stale version
 *  unless stale_ok; a note posts '[sign-off pass|fail] note' to the ticket assignee. */
export const postVerdict = (b: VerdictBody) =>
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
