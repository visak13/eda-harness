// JSON shapes for the board's view API (src/edp8/api_views.py, design §4.1).
//
// These are the UNWRAPPED `value` types — `api<T>()` in client.ts strips the {ok,value,hint}
// envelope, so a caller writes `api<DecisionsHome>("/v1/me/decisions")` and gets T directly.
// One interface per endpoint, mirroring the Python views.* return exactly (enums arrive as
// their .value string, datetimes as ISO strings). Kept in this file so a shape drift is a
// TypeScript error at the call site, not a runtime `undefined`.

// --------------------------------------------------------------------------- primitives

export type ISODateString = string;
// Board Verdict enum .value strings (schemas.py Verdict): passed→"pass", failed→"fail".
// The JSON view API returns these verbatim, so the client renders them, never "passed".
export type Verdict = "pending" | "pass" | "fail";

// Board MessageKind enum (schemas.py MessageKind) — the kinds a Composer can post. Shared
// primitive kept here so the Composer (G2) and the epic/ticket pages (G3a) agree on one union.
export type MessageKind =
  | "question"
  | "answer"
  | "steer"
  | "status"
  | "finding"
  | "deviation"
  | "note";

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

// The recursive kanban/tree node from board.board() (board.py). `criteria` is a "N/M" string
// (passed/total); `gates` are open gate names; `blocked_by` the ids of non-done blockers.
export interface EpicTreeNode {
  id: string;
  kind: string;
  work_type: string;
  title: string;
  status: string;
  assignee: string | null;
  criteria: string;
  gates: string[];
  blocked_by: string[];
  children: EpicTreeNode[];
}

export interface EpicBoard {
  epic: EpicTreeNode;
  counts: Record<string, number>; // status.value → count over the epic + descendants
  ready: string[];
  in_review: string[];
  open_gates: [string, string][]; // [ticket_id, gate]
  words: string;
}

export interface DocSummary extends Record<string, unknown> {
  id: string;
  doc_type: string;
  title: string;
  version: number;
  scope: string;
  summary: string;
  full: string;
}

export interface EpicPage {
  board: EpicBoard;
  words: string | null;
  counts: Record<string, number> | null;
  thread: MessageView[];
  docs: DocSummary[];
  open_gates: [string, string][];
}

export interface DocSummaryRelated extends DocSummary {
  relation: string | null;
}

// The ticket record (Ticket.model_dump). Extra fields arrive verbatim; the ones the page
// renders are named so a shape drift is a TS error, not a blank cell.
export interface TicketRecord extends Record<string, unknown> {
  id: string;
  kind: string;
  work_type: string;
  title: string;
  description: string;
  status: string;
  assignee: string | null;
  tags: string[];
  design_ref: string | null;
  epic_id: string | null;
}

export interface TicketPage {
  ticket: TicketRecord;
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

export interface ArtifactRow extends Record<string, unknown> {
  id: string;
  form: string;
  uri: string;
  note: string;
  created_by: string;
  created_at: ISODateString;
}

export interface LinkRow extends Record<string, unknown> {
  id: string;
  from_id: string;
  to_id: string;
  relation: string;
  created_by: string;
}

export interface Library {
  docs: DocSummary[];
  artifacts: ArtifactRow[];
  links: LinkRow[];
}

// --------------------------------------------------------------------------- POST /v1/messages

export interface MessageSent extends Record<string, unknown> {
  id: string;
  unresolved_mentions: string[]; // @handles that match no participant — nobody was woken for these
}
