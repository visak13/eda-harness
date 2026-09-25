// The chat host <-> webview protocol (design-10b21760d9 §4.2; strategyll-1a201146c8 §2). One union,
// shared by both sides, versioned v:1. No field carries a token, a participant secret or a header:
// `me` is {id, handle} only. The host validates every inbound message with `parseInbound` before
// acting; anything else is dropped and logged by type only.

import type { DocsState } from './docs';
import { DOC_ID } from './docUri';
import { INBOX_KEY, INBOX_TEXT_MAX, VERDICTS, type InboxState, type InboxVerdict } from './inbox';

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
  /** C12: the message's attached artifacts (names and types only; bytes stay in the host) */
  attachments?: AttachmentRef[];
};

// -- attachments (C12 s-85dd35a166; design §13 row C12) ----------------------------------------------
export const ARTIFACT_ID = /^art-[0-9a-f]{10}$/;
export const NAME_MAX = 255;
/** At most this many attachments per message, and per resolve request. */
export const ATTACH_MAX = 20;
/** One attachment of a message, as the board lists it. `image`: the board serves it inline (png/jpeg/gif/webp). */
export type AttachmentRef = { id: string; name: string; contentType: string; image: boolean };
/** What the host learned about an artifact when the view asked (lazily, for rows in view): its size, and for
 *  an image a downscaled `data:` URI. `file`: shown as a file row (not an image, or over the thumbnail caps). */
/** `retry`: a passing failure (board unreachable, worker timeout): shown now, never cached, asked again on the next render. */
export type ArtifactInfo = { id: string; size: number | null; thumb: string | null; state: 'thumb' | 'file' | 'error'; note?: string; retry?: true };
/** A staged upload waiting in the open thread's composer; the host holds it until a send carries it. */
export type PendingAttachment = { id: string; name: string; size: number; contentType: string };
/** A valid attachment file name: 1..255 chars, no control characters. */
export const isAttachName = (n: string) => n.length > 0 && n.length <= NAME_MAX && !/[\u0000-\u001f\u007f]/.test(n);

export type TicketRef = { id: string; kind: string; title: string; status: string };
export type StoryRow = TicketRef & { unread: number; /** C5: commits naming the story or its tasks */ commits?: number };

// -- change cards (C5 s-ab8e69650e; design §4.2, strategyll-86c5b5068f §3) ---------------------------
export const SHA = /^[0-9a-f]{40}$/;
/** A git repo-relative path: `/`-separated, not absolute, no drive, no `..` segment, no NUL/backslash. */
export const isRepoPath = (p: string) =>
  p.length > 0 && p.length <= 4096 && !/[\\\0]/.test(p) && !p.startsWith('/') && !/^[A-Za-z]:/.test(p) && !p.split('/').includes('..');

// -- #-tags (C11 s-35ccc6d35f): a tag is a backticked repo-relative path in the text ----------------
/** A path a #-tag can carry and a link can open: repo-relative, no backtick or control character, no trailing `/`. */
export const isTagPath = (p: string) => isRepoPath(p) && !/[`\u0000-\u001f\u007f]/.test(p) && !p.endsWith('/');
export type PathKind = 'file' | 'folder';
/** One #-picker row. `path` has no trailing `/`; the inserted token adds it for a folder. */
export type PathHit = { path: string; kind: PathKind };
/** At most this many paths per `checkPaths` */
export const CHECK_PATHS_MAX = 200;

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
  /** C13: the commit names the open thread's own ticket set, so the Chat tab shows it as a marker; the
   *  rest of an epic scope's commits (its stories') show only in the Commits tab */
  thread?: boolean;
  /** C13: at epic scope, the story the commit belongs to (named directly or through one of its tasks);
   *  null: it names the epic itself. The view labels the card with the story's title. */
  story?: string | null;
};
/** The live uncommitted chip: the shared tree's working tree + index vs HEAD. Names no seat (dec-8dfe3d97af).
 *  C9 option (a): rows the open epic touched come first, flagged; `scoped` counts them (null: no scope). */
export type UncommittedCard = {
  files: CardFile[]; more: number; total: number; at: string;
  scoped: number | null;
  /** what `scoped` is measured against: the picked epic, the picked story with its tasks (C14), or a lone ticket */
  scope: 'epic' | 'story' | 'ticket' | null;
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
  /** C5/C13: the open scope's change cards (newest first; `thread` marks the Chat markers), the epic's
   *  unlinked commits, the live uncommitted card */
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
  /** C12: the open thread's staged uploads, and what the host already knows about its artifacts */
  pending?: PendingAttachment[];
  artifacts?: ArtifactInfo[];
  /** C15: what waits on the viewer in the open scope (null: signed out, or nothing picked) */
  inbox?: InboxState | null;
  /** C16: the open scope's linked docs (null: signed out, or nothing picked) */
  docs?: DocsState | null;
};

export type HostToView =
  | ChatState
  | { type: 'append'; v: 1; ticketId: string; items: ChatMessage[] }
  | { type: 'prepend'; v: 1; ticketId: string; items: ChatMessage[]; hasOlder: boolean }
  | { type: 'stories'; v: 1; stories: StoryRow[] }
  /** C5/C13: new commits for the open scope (live on a HEAD move) */
  | { type: 'commits'; v: 1; ticketId: string; items: CommitCard[]; unlinked: CommitCard[] }
  | { type: 'uncommitted'; v: 1; card: UncommittedCard | null }
  | { type: 'feed'; v: 1; status: FeedStatus }
  | { type: 'sent'; v: 1; ticketId: string; id: string }
  | { type: 'sendFailed'; v: 1; ticketId: string; text: string }
  /** a Tag selection put a chip in `ticketId`'s composer (null: the chip is gone); `focus` moves focus to the composer */
  | { type: 'insertCode'; v: 1; ticketId: string; chip: ChipView | null; focus: boolean }
  | { type: 'error'; v: 1; text: string }
  /** C11: the #-picker rows for the `findPaths` with this `seq` (the view drops a stale answer); C13: `up`
   *  is the query one level up from the level listed (null at the git root or for a fuzzy answer) */
  | { type: 'paths'; v: 1; seq: number; items: PathHit[]; up?: string | null }
  /** C11: what each checked path is in this workspace; `missing` ones stay plain text */
  | { type: 'pathKinds'; v: 1; kinds: Record<string, PathKind>; missing: string[] }
  /** C12: sizes/thumbnails the view asked for */
  | { type: 'artifacts'; v: 1; ticketId: string; items: ArtifactInfo[] }
  /** C12: the open thread's staged uploads changed (the whole list) */
  | { type: 'pending'; v: 1; ticketId: string; pending: PendingAttachment[] }
  /** C12: an upload was refused; the draft is untouched */
  | { type: 'attachFailed'; v: 1; ticketId: string; name: string; text: string }
  /** C15: the open scope's Inbox (the whole list; `ticketId` is the scope it was read for) */
  | { type: 'inbox'; v: 1; ticketId: string; inbox: InboxState }
  /** C15: a row's write settled: ok, the row left the list; not ok, `text` is why (the board's own words) */
  | { type: 'inboxDone'; v: 1; key: string; ok: boolean; text: string }
  /** C16: the open scope's Docs list (the whole list; `ticketId` is the scope it was read for) */
  | { type: 'docs'; v: 1; ticketId: string; docs: DocsState };

export type ViewToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'pickTicket'; id?: string }
  | { v: 1; type: 'loadOlder' }
  /** `ticketId` is the thread the user sees: the host refuses a send whose ticket is not the open one */
  | { v: 1; type: 'send'; ticketId: string; text: string; kind: SendKind; to?: string; replyTo?: string; chipId?: string;
      /** C12: staged uploads the host holds for this thread; with some, `text` may be empty */
      attachmentIds?: string[] }
  /** the user removed the composer's code chip */
  | { v: 1; type: 'dropCode'; ticketId: string; chipId: string }
  | { v: 1; type: 'openCode'; messageId: string }
  | { v: 1; type: 'openBoard'; ticketId: string; messageId?: string }
  /** C5: a file row (`path`) opens vscode.diff, the card itself (no path) the multi-diff */
  | { v: 1; type: 'openDiff'; sha: string; path?: string }
  /** `scoped`: the multi-diff opens only the rows the open epic touched (C9) */
  | { v: 1; type: 'openUncommitted'; path?: string; scoped?: true }
  | { v: 1; type: 'signIn' }
  /** C11: the #-picker's query (the text after `#`); `seq` pairs the answer */
  | { v: 1; type: 'findPaths'; q: string; seq: number }
  /** C11: inline code spans in rendered messages that look like paths: which exist here? */
  | { v: 1; type: 'checkPaths'; paths: string[] }
  /** C11: a path link: a file opens in the editor, a folder reveals in the Explorer */
  | { v: 1; type: 'openPath'; path: string }
  /** C12: upload a file for `ticketId`'s composer (clip, drop or paste) */
  | { v: 1; type: 'attach'; ticketId: string; name: string; bytes: Uint8Array }
  | { v: 1; type: 'dropAttachment'; ticketId: string; id: string }
  /** C12: size/thumbnail for attachments now in view (the host answers with `artifacts`) */
  | { v: 1; type: 'resolveArtifacts'; ids: string[] }
  /** C12: open an attachment of a message in the open thread (full size in an editor tab, or save) */
  | { v: 1; type: 'openArtifact'; messageId: string; id: string }
  /** C15: reply to a question row (an answer to its asker, threaded under it) */
  | { v: 1; type: 'inboxAnswer'; key: string; text: string }
  /** C15: pass or fail a sign-off row, for the evidence version the row showed */
  | { v: 1; type: 'inboxVerdict'; key: string; verdict: InboxVerdict; note: string; version: number }
  /** C15: rule on a gate row */
  | { v: 1; type: 'inboxGate'; key: string; text: string }
  /** C15: a sign-off row's evidence in an editor tab; a design gate's review on the board */
  | { v: 1; type: 'inboxOpen'; key: string }
  | { v: 1; type: 'inboxRefresh' }
  /** C16: a listed doc opens in the EDP reader at its current version */
  | { v: 1; type: 'docsOpen'; id: string }
  /** C16: compare two versions of a listed doc (the host asks which) */
  | { v: 1; type: 'docsCompare'; id: string }
  | { v: 1; type: 'docsRefresh' };

const TYPES = new Set(['ready', 'pickTicket', 'loadOlder', 'send', 'dropCode', 'openCode', 'openBoard', 'signIn']);
const PATH_TYPES = new Set(['findPaths', 'checkPaths', 'openPath']);
const HANDLE = /^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$/;
const DIFF_TYPES = new Set(['openDiff', 'openUncommitted']);
const ATTACH_TYPES = new Set(['attach', 'dropAttachment', 'resolveArtifacts', 'openArtifact']);
const INBOX_TYPES = new Set(['inboxAnswer', 'inboxVerdict', 'inboxGate', 'inboxOpen', 'inboxRefresh', 'docsOpen', 'docsCompare', 'docsRefresh']);
/** The webview refuses a file over this before posting it: a transport guard for postMessage memory,
 *  NOT the upload rule (the board's cap and type allowlist decide, and their refusal is shown). */
export const ATTACH_TRANSPORT_MAX = 64 * 1024 * 1024;

/** The inbound gate. `handles` are the ids/handles of the last `people` list sent to the view (a
 *  `to` must be one of them). Only the known keys of each type are copied out: extra keys are
 *  ignored, never spread into a request. */
export function parseInbound(raw: unknown, handles: ReadonlySet<string> = new Set()): ViewToHost | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (r.v !== PROTOCOL_V || typeof r.type !== 'string' || !(TYPES.has(r.type) || DIFF_TYPES.has(r.type) || PATH_TYPES.has(r.type) || ATTACH_TYPES.has(r.type) || INBOX_TYPES.has(r.type))) return null;
  const str = (k: string) => (typeof r[k] === 'string' ? (r[k] as string) : undefined);
  switch (r.type) {
    case 'ready': case 'loadOlder': case 'signIn': case 'inboxRefresh': case 'docsRefresh':
      return { v: 1, type: r.type };
    case 'docsOpen': case 'docsCompare': {
      const id = str('id');
      return id && DOC_ID.test(id) ? { v: 1, type: r.type, id } : null;
    }
    case 'inboxAnswer': case 'inboxGate': {
      const key = str('key'), text = str('text');
      const want = r.type === 'inboxAnswer' ? 'q:' : 'g:';
      if (!key || !INBOX_KEY.test(key) || !key.startsWith(want) || text === undefined || !text.trim() || text.length > INBOX_TEXT_MAX) return null;
      return { v: 1, type: r.type, key, text };
    }
    case 'inboxVerdict': {
      const key = str('key'), verdict = str('verdict'), note = str('note') ?? '', version = r.version;
      if (!key || !INBOX_KEY.test(key) || !key.startsWith('c:') || !verdict || !(VERDICTS as readonly string[]).includes(verdict)) return null;
      if (note.length > INBOX_TEXT_MAX || (verdict === 'fail' && !note.trim())) return null;
      if (typeof version !== 'number' || !Number.isSafeInteger(version) || version < 1) return null;
      return { v: 1, type: 'inboxVerdict', key, verdict: verdict as InboxVerdict, note, version };
    }
    case 'inboxOpen': {
      const key = str('key');
      return key && INBOX_KEY.test(key) && !key.startsWith('q:') ? { v: 1, type: 'inboxOpen', key } : null;
    }
    case 'pickTicket': {
      if (r.id === undefined) return { v: 1, type: 'pickTicket' };
      const id = str('id');
      return id && TICKET_ID.test(id) ? { v: 1, type: 'pickTicket', id } : null;
    }
    case 'send': {
      const text = str('text'), kind = str('kind'), ticketId = str('ticketId');
      if (!ticketId || !TICKET_ID.test(ticketId)) return null;
      const att = r.attachmentIds === undefined ? [] : artifactIds(r.attachmentIds);
      if (!att) return null;
      if (text === undefined || (!text.trim() && !att.length) || text.length > TEXT_MAX) return null;
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
      if (att.length) out.attachmentIds = att;
      return out;
    }
    case 'attach': {
      const ticketId = str('ticketId'), name = str('name');
      if (!ticketId || !TICKET_ID.test(ticketId) || !name || !isAttachName(name)) return null;
      const b = r.bytes;
      const bytes = b instanceof Uint8Array ? b : b instanceof ArrayBuffer ? new Uint8Array(b)
        : ArrayBuffer.isView(b) ? new Uint8Array(b.buffer, b.byteOffset, b.byteLength) : null;
      if (!bytes || bytes.byteLength === 0 || bytes.byteLength > ATTACH_TRANSPORT_MAX) return null;
      return { v: 1, type: 'attach', ticketId, name, bytes };
    }
    case 'dropAttachment': {
      const ticketId = str('ticketId'), id = str('id');
      return ticketId && TICKET_ID.test(ticketId) && id && ARTIFACT_ID.test(id) ? { v: 1, type: 'dropAttachment', ticketId, id } : null;
    }
    case 'resolveArtifacts': {
      const ids = artifactIds(r.ids);
      return ids && ids.length ? { v: 1, type: 'resolveArtifacts', ids } : null;
    }
    case 'openArtifact': {
      const m = str('messageId'), id = str('id');
      return m && MESSAGE_ID.test(m) && id && ARTIFACT_ID.test(id) ? { v: 1, type: 'openArtifact', messageId: m, id } : null;
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
    case 'findPaths': {
      const q = str('q'), seq = r.seq;
      if (q === undefined || q.length > 1024 || /[`\r\n]/.test(q)) return null;
      return typeof seq === 'number' && Number.isSafeInteger(seq) && seq >= 0 ? { v: 1, type: 'findPaths', q, seq } : null;
    }
    case 'checkPaths': {
      const ps = r.paths;
      if (!Array.isArray(ps) || ps.length > CHECK_PATHS_MAX) return null;
      if (!ps.every(p => typeof p === 'string' && isTagPath(p))) return null;
      return { v: 1, type: 'checkPaths', paths: [...new Set(ps as string[])] };
    }
    case 'openPath': {
      const p = str('path');
      return p && isTagPath(p) ? { v: 1, type: 'openPath', path: p } : null;
    }
  }
  return null;
}

/** 1..ATTACH_MAX distinct well-formed artifact ids, or null. */
function artifactIds(raw: unknown): string[] | null {
  if (!Array.isArray(raw) || raw.length > ATTACH_MAX) return null;
  if (!raw.every(x => typeof x === 'string' && ARTIFACT_ID.test(x))) return null;
  return [...new Set(raw as string[])];
}

/** A refused `send` still gets an answer, so the composer never stays stuck: its ticket id when it
 *  is well-formed (the view ignores answers for other threads). */
export function refusedSendTicket(raw: unknown): string | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const r = raw as Record<string, unknown>;
  return r.type === 'send' && typeof r.ticketId === 'string' && TICKET_ID.test(r.ticketId) ? r.ticketId : undefined;
}

/** A refused `attach` is answered too (C12), so the view's upload count never sticks: the ticket and a
 *  display name when both are usable. */
export function refusedAttach(raw: unknown): { ticketId: string; name: string } | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const r = raw as Record<string, unknown>;
  if (r.type !== 'attach' || typeof r.ticketId !== 'string' || !TICKET_ID.test(r.ticketId)) return undefined;
  return { ticketId: r.ticketId, name: typeof r.name === 'string' ? r.name.replace(/[\u0000-\u001f\u007f]/g, '_').slice(0, NAME_MAX) : 'file' };
}

/** A refused Inbox write is answered too (C15), so its row's buttons never stay disabled. */
export function refusedInbox(raw: unknown): string | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const r = raw as Record<string, unknown>;
  return (r.type === 'inboxAnswer' || r.type === 'inboxGate' || r.type === 'inboxVerdict') && typeof r.key === 'string' && INBOX_KEY.test(r.key) ? r.key : undefined;
}

/** The inbound type for a log line (never the payload). */
export const inboundType = (raw: unknown) =>
  raw && typeof raw === 'object' ? String((raw as Record<string, unknown>).type).slice(0, 32) : typeof raw;
