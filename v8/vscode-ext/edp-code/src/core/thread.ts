// The open thread, held by the host (strategyll-1a201146c8 §1: the host is the source of truth; the
// webview never assumes an earlier message arrived). Pure: page rows and live rows merge by message
// id, order is the board's storage seq, older pages prepend. One store per open ticket: threads are
// never merged (dec-8dfe3d97af).
import type { ChatMessage, CodeContext } from './chatProtocol';

/** A `GET /v1/tickets/{id}/thread` row. */
export type ThreadRow = {
  id: string; seq: number; by: string; to: string | null; kind: string; text: string;
  at: string; reply_to: string | null; code_context: CodeContext | null;
};
/** A `GET /v1/messages/{id}` row (the live path; no seq, no html). */
export type MessageRow = {
  id: string; ticket_id: string; created_at: string; created_by: string; to: string | null;
  kind: string; text: string; reply_to: string | null; code_context?: CodeContext | null;
};
export type ThreadPage = { thread: ThreadRow[]; thread_total: number; thread_before: number | null };

export const fromThreadRow = (ticketId: string, r: ThreadRow): ChatMessage => ({
  type: 'message', seq: r.seq, id: r.id, ticket_id: ticketId, created_at: r.at, created_by: r.by,
  to: r.to ?? null, kind: r.kind, text: r.text, reply_to: r.reply_to ?? null, code_context: r.code_context ?? null,
});

/** `seq` comes from the feed event that announced the message. */
export const fromMessageRow = (m: MessageRow, seq: number): ChatMessage => ({
  type: 'message', seq, id: m.id, ticket_id: m.ticket_id, created_at: m.created_at, created_by: m.created_by,
  to: m.to ?? null, kind: m.kind, text: m.text, reply_to: m.reply_to ?? null, code_context: m.code_context ?? null,
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
