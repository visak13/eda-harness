// The chat host <-> webview protocol (design-10b21760d9 §4.2; strategyll-1a201146c8 §2). One union,
// shared by both sides, versioned v:1. No field carries a token, a participant secret or a header:
// `me` is {id, handle} only. The host validates every inbound message with `parseInbound` before
// acting; anything else is dropped and logged by type only.

export const PROTOCOL_V = 1 as const;

export const SEND_KINDS = ['note', 'question', 'steer', 'finding', 'answer'] as const;
export type SendKind = (typeof SEND_KINDS)[number];

export const TEXT_MAX = 32_768;
export const TICKET_ID = /^(epic|s|t)-[0-9a-f]{10}$/;
export const MESSAGE_ID = /^m-[0-9a-f]{10}$/;

export type CodeContext = {
  repo_root: string; path: string; line_start: number; line_end: number;
  commit: string | null; dirty: boolean; snippet: string; snippet_sha: string;
};

/** One thread row as the view renders it (the board's thread row / message, normalised). */
export type ChatMessage = {
  type: 'message'; seq: number; id: string; ticket_id: string; created_at: string; created_by: string;
  to: string | null; kind: string; text: string; reply_to: string | null; code_context: CodeContext | null;
};

export type TicketRef = { id: string; kind: string; title: string; status: string };
export type StoryRow = TicketRef & { unread: number };

/** An @-list row, labelled in the host (strategyll-5e3ecdb625 §2): the view sets it with textContent. */
export type PersonRow = {
  id: string; handle: string; type: 'human' | 'agent'; role: string;
  seat_ticket: string | null; seat_title: string | null; seat_state: string | null;
  /** 0 = seat on the open ticket, 1 = seat on the open epic or one of its stories, 2 = human, 3 = other seat */
  rank: number;
  /** "role · ticket id · ticket title" for agents, "human" for people */
  detail: string;
};

export type FeedStatus = 'connecting' | 'live' | 'reconnecting' | 'polling' | 'signed-out' | 'stopped';

export type ChatState = {
  type: 'state'; v: 1;
  me: { id: string; handle: string } | null;
  /** the open thread; null = nothing picked yet */
  ticket: TicketRef | null;
  /** the epic the open thread belongs to (the ticket itself when an epic is open) */
  epic: TicketRef | null;
  stories: StoryRow[];
  architect: string | null;
  people: PersonRow[];
  items: ChatMessage[];
  hasOlder: boolean;
  feed: FeedStatus;
  notice: string | null;
};

export type HostToView =
  | ChatState
  | { type: 'append'; v: 1; ticketId: string; items: ChatMessage[] }
  | { type: 'prepend'; v: 1; ticketId: string; items: ChatMessage[]; hasOlder: boolean }
  | { type: 'stories'; v: 1; stories: StoryRow[] }
  | { type: 'feed'; v: 1; status: FeedStatus }
  | { type: 'sent'; v: 1; ticketId: string; id: string }
  | { type: 'sendFailed'; v: 1; ticketId: string; text: string }
  | { type: 'error'; v: 1; text: string };

export type ViewToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'pickTicket'; id?: string }
  | { v: 1; type: 'loadOlder' }
  /** `ticketId` is the thread the user sees: the host refuses a send whose ticket is not the open one */
  | { v: 1; type: 'send'; ticketId: string; text: string; kind: SendKind; to?: string; replyTo?: string }
  | { v: 1; type: 'openCode'; messageId: string }
  | { v: 1; type: 'openBoard'; ticketId: string; messageId?: string }
  | { v: 1; type: 'signIn' };

const TYPES = new Set(['ready', 'pickTicket', 'loadOlder', 'send', 'openCode', 'openBoard', 'signIn']);
const HANDLE = /^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$/;

/** The inbound gate. `handles` are the ids/handles of the last `people` list sent to the view (a
 *  `to` must be one of them). Only the known keys of each type are copied out: extra keys are
 *  ignored, never spread into a request. */
export function parseInbound(raw: unknown, handles: ReadonlySet<string> = new Set()): ViewToHost | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (r.v !== PROTOCOL_V || typeof r.type !== 'string' || !TYPES.has(r.type)) return null;
  const str = (k: string) => (typeof r[k] === 'string' ? (r[k] as string) : undefined);
  switch (r.type) {
    case 'ready': case 'loadOlder': case 'signIn':
      return { v: 1, type: r.type };
    case 'pickTicket': {
      if (r.id === undefined) return { v: 1, type: 'pickTicket' };
      const id = str('id');
      return id && TICKET_ID.test(id) ? { v: 1, type: 'pickTicket', id } : null;
    }
    case 'send': {
      const text = str('text'), kind = str('kind'), ticketId = str('ticketId');
      if (!ticketId || !TICKET_ID.test(ticketId)) return null;
      if (text === undefined || !text.trim() || text.length > TEXT_MAX) return null;
      if (!kind || !(SEND_KINDS as readonly string[]).includes(kind)) return null;
      const out: ViewToHost = { v: 1, type: 'send', ticketId, text, kind: kind as SendKind };
      if (r.to !== undefined && r.to !== '') {
        const to = str('to');
        if (!to || !HANDLE.test(to) || !handles.has(to)) return null;
        out.to = to;
      }
      if (r.replyTo !== undefined && r.replyTo !== '') {
        const rt = str('replyTo');
        if (!rt || !MESSAGE_ID.test(rt)) return null;
        out.replyTo = rt;
      }
      return out;
    }
    case 'openCode': {
      const id = str('messageId');
      return id && MESSAGE_ID.test(id) ? { v: 1, type: 'openCode', messageId: id } : null;
    }
    case 'openBoard': {
      const t = str('ticketId');
      if (!t || !TICKET_ID.test(t)) return null;
      if (r.messageId === undefined) return { v: 1, type: 'openBoard', ticketId: t };
      const m = str('messageId');
      return m && MESSAGE_ID.test(m) ? { v: 1, type: 'openBoard', ticketId: t, messageId: m } : null;
    }
  }
  return null;
}

/** A refused `send` still gets an answer, so the composer never stays stuck: its ticket id when it
 *  is well-formed (the view ignores answers for other threads). */
export function refusedSendTicket(raw: unknown): string | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const r = raw as Record<string, unknown>;
  return r.type === 'send' && typeof r.ticketId === 'string' && TICKET_ID.test(r.ticketId) ? r.ticketId : undefined;
}

/** The inbound type for a log line (never the payload). */
export const inboundType = (raw: unknown) =>
  raw && typeof raw === 'object' ? String((raw as Record<string, unknown>).type).slice(0, 32) : typeof raw;
