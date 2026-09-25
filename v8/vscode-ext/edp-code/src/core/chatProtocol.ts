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
/** A code chip the host holds (C4): the view only ever sees this id and a display label. */
export const CHIP_ID = /^k-[0-9a-f]{12}$/;

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
export type StoryRow = TicketRef & { unread: number; /** C5: commits naming the story or its tasks */ commits?: number };

// -- change cards (C5 s-ab8e69650e; design §4.2, strategyll-86c5b5068f §3) ---------------------------
export const SHA = /^[0-9a-f]{40}$/;
/** A git repo-relative path: `/`-separated, not absolute, no drive, no `..` segment, no NUL/backslash. */
export const isRepoPath = (p: string) =>
  p.length > 0 && p.length <= 4096 && !/[\\\0]/.test(p) && !p.startsWith('/') && !/^[A-Za-z]:/.test(p) && !p.split('/').includes('..');

export type CardFile = {
  path: string; oldPath?: string; status: string; add: number | null; del: number | null;
  /** C9 uncommitted rows: a path the open epic (or lone ticket) touched */
  touched?: boolean;
};
/** One commit as a timeline card. `seat` is the EDP-Seat trailer, or the ticket's assignee (`seatVia`). */
export type CommitCard = {
  type: 'commit'; sha: string; at: string; subject: string; tickets: string[];
  attribution: 'trailer' | 'subject' | 'none'; seat: string | null; seatVia: 'trailer' | 'assignee' | null;
  files: CardFile[];
  /** files not listed on the card (the multi-diff still opens all of them) */
  more: number;
  /** false: the commit is not in this clone ("pull to see this change") */
  local: boolean;
};
/** The live uncommitted chip: the shared tree's working tree + index vs HEAD. Names no seat (dec-8dfe3d97af).
 *  C9 option (a): rows the open epic touched come first, flagged; `scoped` counts them (null: no scope). */
export type UncommittedCard = {
  files: CardFile[]; more: number; total: number; at: string;
  scoped: number | null;
  /** what `scoped` is measured against: the open thread's epic, or a lone ticket with its tasks */
  scope: 'epic' | 'ticket' | null;
};

/** An @-list row, labelled in the host (strategyll-5e3ecdb625 §2): the view sets it with textContent. */
export type PersonRow = {
  id: string; handle: string; type: 'human' | 'agent'; role: string;
  seat_ticket: string | null; seat_title: string | null; seat_state: string | null;
  /** 0 = seat on the open ticket, 1 = seat on the open epic or one of its stories, 2 = human, 3 = other seat */
  rank: number;
  /** "role · ticket id · ticket title" for agents, "human" for people */
  detail: string;
};

/** The composer's code chip as the view shows it (C4 s-a34658f02f). Display only: the anchor itself
 *  (repo_root, path, snippet_sha) stays in the host, and a send names the chip by `id`. */
export type ChipView = {
  id: string;
  /** `path:Lx-y @sha7[dirty]`, the S5 rendered anchor line */
  label: string;
  /** the first lines of the snippet, for a glance; the full snippet is what gets sent */
  preview: string;
  lines: number;
  truncated: boolean;
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
  /** C5: the open thread's change cards (newest first), the epic's collapsed unlinked commits, the live card */
  commits: CommitCard[];
  unlinked: CommitCard[];
  uncommitted: UncommittedCard | null;
  architect: string | null;
  people: PersonRow[];
  items: ChatMessage[];
  hasOlder: boolean;
  /** the open thread's code chip, if a Tag selection put one there */
  chip: ChipView | null;
  feed: FeedStatus;
  notice: string | null;
};

export type HostToView =
  | ChatState
  | { type: 'append'; v: 1; ticketId: string; items: ChatMessage[] }
  | { type: 'prepend'; v: 1; ticketId: string; items: ChatMessage[]; hasOlder: boolean }
  | { type: 'stories'; v: 1; stories: StoryRow[] }
  /** C5: new commits for the open thread (live on a HEAD move) */
  | { type: 'commits'; v: 1; ticketId: string; items: CommitCard[]; unlinked: CommitCard[] }
  | { type: 'uncommitted'; v: 1; card: UncommittedCard | null }
  | { type: 'feed'; v: 1; status: FeedStatus }
  | { type: 'sent'; v: 1; ticketId: string; id: string }
  | { type: 'sendFailed'; v: 1; ticketId: string; text: string }
  /** a Tag selection put a chip in `ticketId`'s composer (null: the chip is gone); `focus` moves focus to the composer */
  | { type: 'insertCode'; v: 1; ticketId: string; chip: ChipView | null; focus: boolean }
  | { type: 'error'; v: 1; text: string };

export type ViewToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'pickTicket'; id?: string }
  | { v: 1; type: 'loadOlder' }
  /** `ticketId` is the thread the user sees: the host refuses a send whose ticket is not the open one */
  | { v: 1; type: 'send'; ticketId: string; text: string; kind: SendKind; to?: string; replyTo?: string; chipId?: string }
  /** the user removed the composer's code chip */
  | { v: 1; type: 'dropCode'; ticketId: string; chipId: string }
  | { v: 1; type: 'openCode'; messageId: string }
  | { v: 1; type: 'openBoard'; ticketId: string; messageId?: string }
  /** C5: a file row (`path`) opens vscode.diff, the card itself (no path) the multi-diff */
  | { v: 1; type: 'openDiff'; sha: string; path?: string }
  /** `scoped`: the multi-diff opens only the rows the open epic touched (C9) */
  | { v: 1; type: 'openUncommitted'; path?: string; scoped?: true }
  | { v: 1; type: 'signIn' };

const TYPES = new Set(['ready', 'pickTicket', 'loadOlder', 'send', 'dropCode', 'openCode', 'openBoard', 'signIn']);
const HANDLE = /^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$/;
const DIFF_TYPES = new Set(['openDiff', 'openUncommitted']);

/** The inbound gate. `handles` are the ids/handles of the last `people` list sent to the view (a
 *  `to` must be one of them). Only the known keys of each type are copied out: extra keys are
 *  ignored, never spread into a request. */
export function parseInbound(raw: unknown, handles: ReadonlySet<string> = new Set()): ViewToHost | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (r.v !== PROTOCOL_V || typeof r.type !== 'string' || !(TYPES.has(r.type) || DIFF_TYPES.has(r.type))) return null;
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
      if (r.chipId !== undefined) {
        const c = str('chipId');
        if (!c || !CHIP_ID.test(c)) return null;
        out.chipId = c;
      }
      return out;
    }
    case 'dropCode': {
      const ticketId = str('ticketId'), chipId = str('chipId');
      return ticketId && TICKET_ID.test(ticketId) && chipId && CHIP_ID.test(chipId) ? { v: 1, type: 'dropCode', ticketId, chipId } : null;
    }
    case 'openDiff': {
      const sha = str('sha');
      if (!sha || !SHA.test(sha)) return null;
      if (r.path === undefined) return { v: 1, type: 'openDiff', sha };
      const p = str('path');
      return p && isRepoPath(p) ? { v: 1, type: 'openDiff', sha, path: p } : null;
    }
    case 'openUncommitted': {
      if (r.scoped !== undefined && r.scoped !== true) return null;
      if (r.path === undefined) return r.scoped ? { v: 1, type: 'openUncommitted', scoped: true } : { v: 1, type: 'openUncommitted' };
      const p = str('path');
      return p && isRepoPath(p) ? { v: 1, type: 'openUncommitted', path: p } : null;
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
