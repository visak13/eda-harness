// The open thread, held by the host (strategyll-1a201146c8 §1: the host is the source of truth; the
// webview never assumes an earlier message arrived). Pure: page rows and live rows merge by message
// id, order is the board's storage seq, older pages prepend. One store per open ticket: threads are
// never merged (dec-8dfe3d97af).
import type { AttachmentRef, ChatMessage, CodeContext, QuoteView } from './chatProtocol';
import { attachmentRefs, type BoardAttachment } from './attachments';

/** A `GET /v1/tickets/{id}/thread` row. */
export type ThreadRow = {
  id: string; seq: number; by: string; to: string | null; kind: string; text: string;
  at: string; reply_to: string | null; code_context: CodeContext | null;
  /** C12: attachment cards (id, form, filename, content type), never bytes */
  attachments?: BoardAttachment[];
  /** C18/C20: verified quotes, in order (absent on a pre-C18 board) */
  quotes?: unknown;
};
/** A `GET /v1/messages/{id}` row (the live path; no seq, no html). */
export type MessageRow = {
  id: string; ticket_id: string; created_at: string; created_by: string; to: string | null;
  kind: string; text: string; reply_to: string | null; code_context?: CodeContext | null;
  /** C12: artifact ids only; the host resolves names before the row reaches the view */
  artifacts?: string[];
  quotes?: unknown;
};
export type ThreadPage = { thread: ThreadRow[]; thread_total: number; thread_before: number | null };

export const fromThreadRow = (ticketId: string, r: ThreadRow): ChatMessage => ({
  type: 'message', seq: r.seq, id: r.id, ticket_id: ticketId, created_at: r.at, created_by: r.by,
  to: r.to ?? null, kind: r.kind, text: r.text, reply_to: r.reply_to ?? null, code_context: r.code_context ?? null,
  ...withAttachments(attachmentRefs(r.attachments)), ...withQuotes(r.quotes),
});

const withAttachments = (a: AttachmentRef[]) => (a.length ? { attachments: a } : {});

const s = (x: unknown) => (typeof x === 'string' ? x : null);
const n = (x: unknown) => (typeof x === 'number' && Number.isSafeInteger(x) ? x : null);

/** C20: the board's stored quotes, shaped for the view (known fields only; a malformed row is skipped). */
export function quoteViews(raw: unknown): QuoteView[] {
  if (!Array.isArray(raw)) return [];
  const out: QuoteView[] = [];
  for (const q of raw as Record<string, unknown>[]) {
    if (!q || typeof q !== 'object' || typeof q.text !== 'string' || !['doc', 'message', 'code'].includes(q.source as string)) continue;
    const lo = (q.locator && typeof q.locator === 'object' ? q.locator : {}) as Record<string, unknown>;
    const c = q.code as Record<string, unknown> | null | undefined;
    const code = c && typeof c.path === 'string' && typeof c.repo_root === 'string' && n(c.line_start) && n(c.line_end)
      ? { repo_root: c.repo_root, path: c.path, line_start: n(c.line_start)!, line_end: n(c.line_end)!, commit: s(c.commit), dirty: c.dirty === true,
        snippet: typeof c.snippet === 'string' ? c.snippet : q.text, snippet_sha: s(c.snippet_sha) ?? '' } : null;
    out.push({ source: q.source as QuoteView['source'], id: s(q.id), version: n(q.version), author: s(q.author), text: q.text, note: s(q.note), code,
      locator: { heading: s(lo.heading), line_start: n(lo.line_start), line_end: n(lo.line_end), char_start: n(lo.char_start), char_end: n(lo.char_end) } });
  }
  return out;
}

const withQuotes = (raw: unknown) => { const q = quoteViews(raw); return q.length ? { quotes: q } : {}; };

/** `seq` comes from the feed event that announced the message. */
/** `refs`: the message's artifacts, resolved by the host (C12). */
export const fromMessageRow = (m: MessageRow, seq: number, refs: AttachmentRef[] = []): ChatMessage => ({
  type: 'message', seq, id: m.id, ticket_id: m.ticket_id, created_at: m.created_at, created_by: m.created_by,
  to: m.to ?? null, kind: m.kind, text: m.text, reply_to: m.reply_to ?? null, code_context: m.code_context ?? null,
  ...withAttachments(refs), ...withQuotes(m.quotes),
});

export class ThreadStore {
  private byId = new Map<string, ChatMessage>();
  /** the `before` cursor for the next older page; null = no older page */
  before: number | null = null;

  constructor(public readonly ticketId: string) {}

  get items(): ChatMessage[] {
    // Feed seqs and message storage seqs are different counters: order by time, then seq, then id
    return [...this.byId.values()].sort(order);
  }

  get size(): number { return this.byId.size; }
  has(id: string): boolean { return this.byId.has(id); }
  get(id: string): ChatMessage | undefined { return this.byId.get(id); }

  /** Upsert rows; returns the ones that were new (for an `append`/`prepend`). Rows for another
   *  ticket are refused: threads are never merged. */
  merge(rows: ChatMessage[]): ChatMessage[] {
    const fresh: ChatMessage[] = [];
    for (const r of rows) {
      if (r.ticket_id !== this.ticketId) continue;
      const had = this.byId.get(r.id);
      // a page row's seq is the storage seq; keep the first seq we saw so the order is stable
      this.byId.set(r.id, had ? { ...r, seq: had.seq } : r);
      if (!had) fresh.push(r);
    }
    return fresh.sort(order);
  }

  /** The newest page (replaces the cursor); returns the new rows. */
  loadPage(p: ThreadPage): ChatMessage[] {
    this.before = p.thread_before;
    return this.merge(p.thread.map(r => fromThreadRow(this.ticketId, r)));
  }

  /** An older page: returns the new rows (to prepend). */
  loadOlder(p: ThreadPage): ChatMessage[] {
    this.before = p.thread_before;
    return this.merge(p.thread.map(r => fromThreadRow(this.ticketId, r)));
  }
}

// Thread rows carry `isoformat()` times (+00:00, microseconds dropped when 0) and message rows `…Z`:
// compare instants, never strings
const t = (s: string) => { const n = Date.parse(s); return Number.isNaN(n) ? 0 : n; };

function order(a: ChatMessage, b: ChatMessage): number {
  return t(a.created_at) - t(b.created_at) || a.seq - b.seq || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}
