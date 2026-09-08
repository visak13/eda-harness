// JSON shapes for the board's view API (src/edp8/api_views.py, design §4.1).
//
// These are the UNWRAPPED `value` types — `api<T>()` in client.ts strips the {ok,value,hint}
// envelope, so a caller writes `api<DecisionsHome>("/v1/me/decisions")` and gets T directly.
// One interface per endpoint, mirroring the Python views.* return exactly (enums arrive as
// their .value string, datetimes as ISO strings). Kept in this file so a shape drift is a
// TypeScript error at the call site, not a runtime `undefined`.

// --------------------------------------------------------------------------- primitives

export type ISODateString = string;
export type Verdict = "pending" | "passed" | "failed";

export interface CriterionView {
  id: string;
  text: string;
  check: string;
  checked_by: string | null;
  verdict: Verdict;
  evidence_ref: string | null;
  evidence_version: number | null;
}

export interface CritCounts {
  passed: number;
  failed: number;
  pending: number;
  total: number;
}

export interface MessageView {
  id: string;
  by: string;
  to: string | null;
  kind: string;
  text: string;
  at: ISODateString;
  reply_to: string | null;
}

export interface WaitingReason {
  reason: string;
  presence: string | null; // seat presence, never folded into the reason
  latest_status: string | null;
}

// --------------------------------------------------------------------------- /v1/me/decisions

export interface SignoffRow {
  criterion: CriterionView;
  ticket: { id: string; title: string; epic_id: string; epic_title: string; assignee: string | null };
  doc: { id: string; title: string; doc_type: string; version: number } | null;
  excerpt: string;
}

export interface QuestionRow {
  id: string;
  ticket_id: string;
  created_by: string;
  to: string | null;
  kind: string;
  text: string;
  asker: { type: string; role: string; seat_state: string | null; note: string };
  [k: string]: unknown; // inbox rows carry additional board fields verbatim
}

export interface GateRow {
  ticket_id: string;
  gate: string;
  by: string;
  note: string | null;
  opened_at: ISODateString;
  epic: string;
}

export interface DecisionsHome {
  signoffs: SignoffRow[];
  questions: QuestionRow[];
  gates: GateRow[];
  counts: { signoffs: number; questions: number; gates: number };
}

export type ResolvedRow =
  | { at: ISODateString; kind: "verdict"; ticket_id: string; criterion: string; verdict: string }
  | { at: ISODateString; kind: "gate"; ticket_id: string; gate: string; answer: string };

// --------------------------------------------------------------------------- /v1/me/*

export interface PersonRow {
  id: string;
  handle: string;
  type: "human" | "agent";
  role: string;
  seat_ticket: string | null;
  seat_state: string | null;
  label: string;
  self: boolean;
}

export interface ConversationRow {
  ticket_id: string;
  title: string;
  epic_id: string | null;
  unread: boolean;
  last: { by: string; text: string; at: ISODateString } | null;
}

export interface Summary {
  participant: Record<string, unknown>;
  avatar_id: string | null;
  counts: { waiting_on_you: number; open_gates: number; conversations: number };
  last_seq: number;
}

export interface AvatarState {
  avatar_id: string | null;
  kind: "human" | "role" | "system";
  catalog?: AvatarCatalogEntry[];
}

export interface AvatarCatalogEntry {
  id: string;
  name: string;
  svg: string;
}

// --------------------------------------------------------------------------- epics / tickets

export interface EpicSummaryRow {
  id: string;
  title: string;
  status: string;
  created_at: ISODateString;
  criteria: CritCounts;
  open_gates: number;
  waiting_reason: WaitingReason;
  assigned_seats: string[];
  latest_status: string | null;
}

export interface TicketTableRow {
  id: string;
  epic_id: string | null;
  title: string;
  kind: string;
  work_type: string;
  status: string;
  assignee: string | null;
  tags: string[];
  criteria: CritCounts;
  blocked_by: string[];
}

export interface TicketsTable {
  rows: TicketTableRow[];
  count: number;
}

export interface EpicPage {
  board: Record<string, unknown>;
  words: string | null;
  counts: Record<string, unknown> | null;
  thread: MessageView[];
  docs: Record<string, unknown>[];
  open_gates: unknown[];
}

export interface DocSummaryRelated extends Record<string, unknown> {
  relation: string | null;
}

export interface TicketPage {
  ticket: Record<string, unknown>;
  epic_id: string;
  criteria: CriterionView[];
  docs: DocSummaryRelated[];
  thread: MessageView[];
  assignee: { id: string | null; handle: string | null; role: string | null };
  waiting_reason: WaitingReason;
}

// --------------------------------------------------------------------------- docs / activity / library

export interface DocHtml {
  id: string;
  title: string;
  doc_type: string;
  scope: string;
  owner_role: string;
  version: number;
  versions: number[];
  html: string; // sanitised
  signoff_criterion: { id: string; text: string; ticket_id: string } | null;
}

export interface ActivityDay {
  day: string;
  events: { line: string; subject_id: string; kind: string; at: ISODateString }[];
}

export interface Library {
  docs: Record<string, unknown>[];
  artifacts: Record<string, unknown>[];
  links: Record<string, unknown>[];
}

// --------------------------------------------------------------------------- POST /v1/messages

export interface MessageSent extends Record<string, unknown> {
  id: string;
  unresolved_mentions: string[]; // @handles that match no participant — nobody was woken for these
}
