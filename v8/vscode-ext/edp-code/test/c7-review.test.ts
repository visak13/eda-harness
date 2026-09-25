// Bounded C7 reproductions: assert the observed faulty behavior, not acceptance.
import { expect, it, vi } from 'vitest';
import { FeedClient } from '../src/core/feed';
import { InboxHost } from '../src/vscode/inbox';
import type { Board } from '../src/core/api';
import { ChatController } from '../src/vscode/chat';
import { ThreadStore } from '../src/core/thread';
import { locateInSource as extensionLocate } from '../src/core/quoteMatch';
import { locateInSource as webLocate } from '../../../web/src/components/quoteMatch';

const creds = async () => ({ participant: 'review', token: 'throwaway' });

it('C7: a feed awaiting HTTP headers has no watchdog', async () => {
  vi.useFakeTimers();
  const f = vi.fn((_url: unknown, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const client = new FeedClient({ baseUrl: 'http://127.0.0.1:1', creds, fetch: f as never, onEvent() {}, readTimeoutMs: 45000 });
  try {
    client.start();
    await vi.advanceTimersByTimeAsync(90000);
    expect(f).toHaveBeenCalledTimes(1);
    expect(client.status).toBe('connecting');
    expect(client.pendingTimers).toBe(0);
    expect(f.mock.calls[0][1].signal?.aborted).toBe(false);
  } finally { client.dispose(); await vi.advanceTimersByTimeAsync(0); vi.useRealTimers(); }
});

it('C7: ready-then-EOF on every stream never reaches polling fallback', async () => {
  vi.useFakeTimers();
  const urls: string[] = [];
  const f = vi.fn(async (url: unknown) => {
    urls.push(String(url));
    return new Response(': ready 100\n\n', { status: 200 });
  });
  const client = new FeedClient({ baseUrl: 'http://127.0.0.1:1', creds, fetch: f as never, onEvent() {}, backoffMs: 10, random: () => .5 });
  try {
    client.start();
    await vi.advanceTimersByTimeAsync(100);
    expect(urls.length).toBeGreaterThan(3);
    expect(urls.some(u => u.includes('/v1/events'))).toBe(false);
    expect(client.since).toBe(100);
  } finally { client.dispose(); await vi.advanceTimersByTimeAsync(0); vi.useRealTimers(); }
});

it('C7: same-scope Inbox keeps the previous identity question after a 403', async () => {
  let refused = false;
  const board = { decisions: async () => {
    if (refused) throw Object.assign(new Error('forbidden'), { status: 403 });
    return { questions: [{ id: 'm-1111111111', ticket_id: 's-0123456789', text: 'owner-private question', created_by: 'arch', created_at: '2026-09-25T00:00:00Z', kind: 'question' }], signoffs: [], gates: [], counts: {} };
  } } as unknown as Board;
  const sc = { id: 's-0123456789', ids: new Set(['s-0123456789']), titles: new Map([['s-0123456789', 'Story']]) };
  const h = new InboxHost(() => board, () => 'http://127.0.0.1:1', () => sc, () => {}, async () => {}, () => {}, () => {});
  try {
    await h.open();
    expect(h.snapshot(sc.id)?.items).toHaveLength(1);
    refused = true;
    await h.open();
    expect(h.snapshot(sc.id)?.error).toContain('forbidden');
    expect(h.snapshot(sc.id)?.items).toHaveLength(1);
  } finally { h.dispose(); }
});

it('C7: message after thread snapshot but before open completes is discarded', async () => {
  const id = 's-0123456789';
  let peopleDone!: () => void;
  const people = new Promise<void>(r => { peopleDone = r; });
  let snapshotTaken!: () => void;
  const snapshot = new Promise<void>(r => { snapshotTaken = r; });
  const board = {
    ticket: async () => ({ id, title: 'Story', kind: 'story', status: 'in_progress' }),
    tickets: async () => [],
    thread: async () => { snapshotTaken(); return { thread: [], thread_total: 0, thread_before: null }; },
    message: vi.fn(),
  };
  // Call the actual open/onEvent methods; isolate only UI and unrelated indexes.
  const c = Object.assign(Object.create(ChatController.prototype), {
    opening: 0, ticket: null, epic: null, stories: [], tree: [], unread: new Map(), anchors: new Map(),
    feedStatus: 'live', readyDone: true, board: () => board,
    loadPeople: () => people, markSeen() {}, addAnchors() {}, recomputeCommits() {}, syncUnread() {},
    ctx: { workspaceState: { update: async () => {} } },
    inbox: { open: async () => {} }, docs: { open: async () => {}, has: () => false },
    decisions: { openScope: async () => {}, has: () => false },
    postState() {}, settleOpen() {}, countUnread: async () => {}, fail: vi.fn(),
  });
  const opening = c.open(id);
  await snapshot;
  await c.onEvent({ seq: 101, kind: 'message_sent', subject_id: id, data: { message: 'm-1111111111' } });
  peopleDone(); await opening;
  expect(c.fail).not.toHaveBeenCalled();
  expect(c.ticket.id).toBe(id);
  expect(board.message).not.toHaveBeenCalled();
  expect(c.store.items).toHaveLength(0);
});

it('C7: resync after 101 missed messages retains an unreachable history hole', async () => {
  const id = 's-0123456789';
  const row = (seq: number) => ({ id: `m-${String(seq).padStart(10, '0')}`, seq, by: 'arch', to: null, kind: 'note', text: `message ${seq}`, at: '2026-09-25T00:00:00Z', reply_to: null, code_context: null });
  const store = new ThreadStore(id);
  store.loadPage({ thread: [row(1)], thread_total: 1, thread_before: null });
  const c = Object.assign(Object.create(ChatController.prototype), {
    store, board: () => ({ thread: async () => ({ thread: Array.from({ length: 100 }, (_, i) => row(i + 3)), thread_total: 102, thread_before: 3 }) }),
    post: vi.fn(), provider: { noteUnseen() {} }, log: vi.fn(),
  });
  await c.reload();
  expect(c.log).not.toHaveBeenCalled();
  expect(store.items).toHaveLength(101);
  expect(store.has(row(2).id)).toBe(false);
  expect(store.before).toBeNull();
});

it('C7: both source matchers discard literal Markdown link text inside code', () => {
  for (const locate of [extensionLocate, webLocate]) {
    expect(locate('`[x](y)`', '[x](y)', '')).toBeNull();
    expect(locate('```\n[x](y)\n```', '[x](y)', '')).toBeNull();
  }
});
