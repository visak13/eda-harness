// Bounded C7 reproductions: regressions for the owner-picked fixes.
import { expect, it, vi } from 'vitest';
import { FeedClient } from '../src/core/feed';
import { InboxHost } from '../src/vscode/inbox';
import type { Board } from '../src/core/api';
import { ChatController } from '../src/vscode/chat';
import { ThreadStore } from '../src/core/thread';
import { locateInSource as extensionLocate } from '../src/core/quoteMatch';
import { locateInSource as webLocate } from '../../../web/src/components/quoteMatch';
import { DocReader } from '../src/vscode/reader';

const creds = async () => ({ participant: 'review', token: 'throwaway' });

it('C7: a feed awaiting HTTP headers times out and retries', async () => {
  vi.useFakeTimers();
  const f = vi.fn((_url: unknown, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const client = new FeedClient({ baseUrl: 'http://127.0.0.1:1', creds, fetch: f as never, onEvent() {}, readTimeoutMs: 45000 });
  try {
    client.start();
    await vi.advanceTimersByTimeAsync(90000);
    expect(f.mock.calls.length).toBeGreaterThan(1);
    expect(f.mock.calls[0][1].signal?.aborted).toBe(true);
    client.dispose();
    expect(client.pendingTimers).toBe(0);
  } finally { client.dispose(); await vi.advanceTimersByTimeAsync(0); vi.useRealTimers(); }
});

it('C7: ready-then-EOF on every stream reaches polling fallback', async () => {
  vi.useFakeTimers();
  const urls: string[] = [];
  const f = vi.fn(async (url: unknown) => {
    urls.push(String(url));
    return new Response(String(url).includes('/v1/events') ? JSON.stringify({ value: [] }) : ': ready 100\n\n', { status: 200 });
  });
  const client = new FeedClient({ baseUrl: 'http://127.0.0.1:1', creds, fetch: f as never, onEvent() {}, backoffMs: 10, random: () => .5 });
  try {
    client.start();
    await vi.advanceTimersByTimeAsync(100);
    expect(urls.length).toBeGreaterThanOrEqual(3);
    expect(urls.some(u => u.includes('/v1/events'))).toBe(true);
    expect(client.since).toBe(100);
  } finally { client.dispose(); await vi.advanceTimersByTimeAsync(0); vi.useRealTimers(); }
});

it('C7: same-scope Inbox clears the previous identity question after a 403', async () => {
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
    expect(h.snapshot(sc.id)?.items).toHaveLength(0);
  } finally { h.dispose(); }
});

it('C7: message after thread snapshot but before open completes is replayed after the snapshot', async () => {
  const id = 's-0123456789';
  let peopleDone!: () => void;
  const people = new Promise<void>(r => { peopleDone = r; });
  let snapshotTaken!: () => void;
  const snapshot = new Promise<void>(r => { snapshotTaken = r; });
  const board = {
    ticket: async () => ({ id, title: 'Story', kind: 'story', status: 'in_progress' }),
    tickets: async () => [],
    thread: async () => { snapshotTaken(); return { thread: [], thread_total: 0, thread_before: null }; },
    message: vi.fn(async () => ({ id: 'm-1111111111', ticket_id: id, created_at: '2026-09-25T00:00:00Z', created_by: 'arch', text: 'arrived in the gap', kind: 'note' })),
  };
  // Call the actual open/onEvent methods; isolate only UI and unrelated indexes.
  const c = Object.assign(Object.create(ChatController.prototype), {
    opening: 0, viewer: 0, attach: { refs: async () => [] }, post: vi.fn(), provider: { noteUnseen() {} }, ticket: null, epic: null, stories: [], tree: [], unread: new Map(), anchors: new Map(),
    feedStatus: 'live', readyDone: true, board: () => board,
    loadPeople: () => people, markSeen() {}, addAnchors() {}, recomputeCommits() {}, syncUnread() {},
    ctx: { workspaceState: { update: async () => {} } },
    inbox: { open: async () => {}, schedule() {} }, docs: { open: async () => {}, has: () => false },
    decisions: { openScope: async () => {}, has: () => false, schedule() {} },
    postState() {}, settleOpen() {}, countUnread: async () => {}, fail: vi.fn(),
  });
  const opening = c.open(id);
  await snapshot;
  await c.onEvent({ seq: 101, kind: 'message_sent', subject_id: id, data: { message: 'm-1111111111' } });
  peopleDone(); await opening;
  expect(c.fail).not.toHaveBeenCalled();
  expect(c.ticket.id).toBe(id);
  expect(board.message).toHaveBeenCalledWith('m-1111111111');
  expect(c.store.items).toHaveLength(1);
});

it('C7: resync after 101 missed messages keeps the missing page reachable', async () => {
  const id = 's-0123456789';
  const row = (seq: number) => ({ id: `m-${String(seq).padStart(10, '0')}`, seq, by: 'arch', to: null, kind: 'note', text: `message ${seq}`, at: '2026-09-25T00:00:00Z', reply_to: null, code_context: null });
  const store = new ThreadStore(id);
  store.loadPage({ thread: [row(1)], thread_total: 1, thread_before: null });
  const c = Object.assign(Object.create(ChatController.prototype), {
    store, board: () => ({ thread: async () => ({ thread: Array.from({ length: 100 }, (_, i) => row(i + 3)), thread_total: 102, thread_before: 3 }) }),
    post: vi.fn(), postState: vi.fn(), provider: { noteUnseen() {} }, log: vi.fn(),
  });
  await c.reload();
  expect(c.log).not.toHaveBeenCalled();
  expect(store.items).toHaveLength(101);
  expect(store.has(row(2).id)).toBe(false);
  expect(store.before).toBe(3);
  store.loadOlder({ thread: [row(1), row(2)], thread_total: 102, thread_before: null });
  expect(store.items).toHaveLength(102);
  expect(store.before).toBeNull();
});

it('C7: both source matchers retain literal Markdown link text inside code', () => {
  for (const locate of [extensionLocate, webLocate]) {
    expect(locate('`[x](y)`', '[x](y)', '')?.text).toBe('[x](y)');
    expect(locate('```\n[x](y)\n```', '[x](y)', '')?.text).toBe('[x](y)');
  }
});

it('C7: refreshing a reader with 401 clears doc content and proposal actions', async () => {
  const refused = async () => { throw Object.assign(new Error('unauthorized'), { status: 401 }); };
  const r = Object.assign(Object.create(DocReader.prototype), { board: () => ({ doc: refused, latestDoc: refused }), onAuthFail: vi.fn() });
  const p = { id: 'design-1111111111', version: 1, state: { doc: { body: 'old private document' }, canResolve: true }, next: () => 1, current: () => true, post: vi.fn() };
  await r.load(p);
  expect(p.state).toMatchObject({ doc: null, canResolve: false, error: 'Sign in to the board to read this doc.' });
  expect(r.onAuthFail).toHaveBeenCalledOnce();
});

it('C7: viewer invalidation aborts requests and rejects delayed bodies and old chained writes', async () => {
  const { ViewerRequests } = await import('../src/core/viewer');
  let release!: (value: unknown) => void;
  let signal!: AbortSignal;
  const f = vi.fn(async (_input: unknown, init?: RequestInit) => {
    signal = init!.signal!;
    return { status: 200, json: () => new Promise(r => { release = r; }) } as Response;
  });
  const requests = new ViewerRequests(() => requests.invalidate(), f as typeof fetch);
  const board = requests.board('http://127.0.0.1:1', creds, () => {});
  const pending = board.ticket('s-0123456789');
  await vi.waitFor(() => expect(release).toBeTypeOf('function'));
  requests.invalidate();
  expect(signal.aborted).toBe(true);
  release({ ok: true, value: { id: 'old-private-ticket' } });
  await expect(pending).rejects.toMatchObject({ code: 'viewer_changed' });
  await expect(board.ticket('s-0123456789')).rejects.toMatchObject({ code: 'viewer_changed' });
  expect(f).toHaveBeenCalledTimes(1);
});

it('C7: a 403 invalidates the whole viewer, even when a caller would swallow its error', async () => {
  const { ViewerRequests } = await import('../src/core/viewer');
  const cleared = vi.fn(() => requests.invalidate());
  const f = vi.fn(async () => new Response('{}', { status: 403 }));
  const requests = new ViewerRequests(cleared, f as typeof fetch);
  const board = requests.board('http://127.0.0.1:1', creds, () => {});
  await board.docsOf('epic-0123456789').catch(() => []);
  expect(cleared).toHaveBeenCalledOnce();
  await expect(board.docResolve('design-0123456789', true, 1)).rejects.toMatchObject({ code: 'viewer_changed' });
  expect(f).toHaveBeenCalledTimes(1);
});

it('C7: quote trays partition normalized origins and participants and restore only their own drafts', async () => {
  const { QuoteHost, trayKey } = await import('../src/vscode/quotes');
  const { Tray, messageDraft } = await import('../src/core/quotes');
  const data = new Map<string, unknown>();
  const q = Object.assign(Object.create(QuoteHost.prototype), {
    tray: new Tray(), identity: null, gen: 0, invalid: new Map(), markers: new Map(),
    ctx: { workspaceState: { get: (k: string) => data.get(k), update: async (k: string, v: unknown) => { data.set(k, v); } } },
    ctl: { dispose() {} }, controller: () => ({ dispose() {} }), syncMarkers() {}, updateStatus() {}, post() {},
    chat: { onMarks() {}, target: () => ({ id: 's-0123456789', title: 'story' }) },
  });
  const a = { origin: 'https://board.example:443/a', participant: 'owner' };
  q.setIdentity(a);
  const draft = messageDraft({ id: 'm-1111111111', text: 'passage', created_by: 'arch' }, 'passage', '', 'private A');
  await q.add(draft);
  expect(q.chips('s-0123456789')).toHaveLength(1);
  q.setIdentity({ ...a, participant: 'other' });
  expect(q.chips('s-0123456789')).toHaveLength(0);
  q.setIdentity({ ...a, origin: 'https://other.example' });
  expect(q.chips('s-0123456789')).toHaveLength(0);
  q.setIdentity({ ...a, origin: 'https://board.example/' });
  expect(q.chips('s-0123456789')[0].note).toBe('private A');
  expect(trayKey(a.origin, a.participant)).toBe(trayKey('https://board.example/', 'owner'));
  q.setIdentity(null);
  expect(q.chips('s-0123456789')).toHaveLength(0);
});

it('C7: viewer reset clears every store and cancels an already queued event', async () => {
  const cleared: string[] = [];
  const clear = (name: string) => ({ clear: () => cleared.push(name) });
  const c = Object.assign(Object.create(ChatController.prototype), {
    viewer: 0, opening: 4, opened: 3, pendingEvents: { generation: 4, events: [{}] },
    cancelViewer: () => cleared.push('requests'), chain: Promise.resolve(), log() {},
    refs: clear('refs'), reader: { reset: () => cleared.push('reader') }, docProvider: clear('sources'),
    feed: { dispose: () => cleared.push('feed') },
    inbox: clear('inbox'), docs: clear('docs'), decisions: clear('decisions'), attach: clear('attachments'),
    quotes: { setIdentity: (x: unknown) => { expect(x).toBeNull(); cleared.push('quotes'); } },
    unread: new Map([['private', 1]]), chips: new Map([['private', 1]]), anchors: new Map([['private', 1]]), titles: new Map([['private', 'title']]),
    ticket: { id: 'private' }, store: {}, me: { id: 'owner' }, people: [{}], tree: [{}], postState: vi.fn(),
  });
  const queued = vi.fn();
  c.enqueue(queued, 'old event');
  c.clearViewer();
  await c.chain;
  expect(queued).not.toHaveBeenCalled();
  expect(cleared.sort()).toEqual(['attachments', 'decisions', 'docs', 'feed', 'inbox', 'quotes', 'reader', 'refs', 'requests', 'sources']);
  expect(c).toMatchObject({ ticket: null, me: null, store: undefined, pendingEvents: undefined, people: [], tree: [], feedStatus: 'signed-out', opening: 5, opened: 5 });
  expect(c.titles.size + c.anchors.size + c.chips.size + c.unread.size).toBe(0);
});

it('C7: an older read started before resync cannot erase the new gap cursor', async () => {
  const store = new ThreadStore('s-0123456789'); store.before = 10;
  let finish!: (page: unknown) => void;
  const c = Object.assign(Object.create(ChatController.prototype), {
    store, board: () => ({ thread: () => new Promise(r => { finish = r; }) }), post: vi.fn(), fail: vi.fn(), addAnchors() {},
  });
  const pending = c.loadOlder();
  store.loadPage({ thread: [], thread_total: 200, thread_before: 110 });
  finish({ thread: [], thread_total: 200, thread_before: null });
  await pending;
  expect(store.before).toBe(110);
  expect(c.post).toHaveBeenCalledWith(expect.objectContaining({ hasOlder: true }));
});

it('C7: a newer pick wins while the first page and its buffered events are pending', async () => {
  const old = 's-0123456789', next = 's-1123456789';
  let finish!: (page: unknown) => void;
  const board = {
    ticket: async (id: string) => ({ id, title: id, kind: 'story', status: 'in_progress' }), tickets: async () => [],
    thread: async (id: string) => id === old ? new Promise(r => { finish = r; }) : { thread: [], thread_total: 0, thread_before: null },
    message: vi.fn(),
  };
  const c = Object.assign(Object.create(ChatController.prototype), {
    opening: 0, viewer: 0, ticket: null, epic: null, stories: [], tree: [], unread: new Map(), anchors: new Map(),
    feedStatus: 'live', readyDone: true, board: () => board, loadPeople: async () => {},
    markSeen() {}, addAnchors() {}, recomputeCommits() {}, syncUnread() {},
    ctx: { workspaceState: { update: async () => {} } }, inbox: { open: async () => {} },
    docs: { open: async () => {}, has: () => false }, decisions: { openScope: async () => {}, has: () => false },
    postState() {}, settleOpen() {}, countUnread: async () => {}, fail: vi.fn(),
  });
  const first = c.open(old);
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
  await c.onEvent({ seq: 101, kind: 'message_sent', subject_id: old, data: { message: 'm-1111111111' } });
  await c.open(next);
  finish({ thread: [], thread_total: 0, thread_before: null }); await first;
  expect(c.ticket.id).toBe(next);
  expect(c.store.ticketId).toBe(next);
  expect(c.store.items).toHaveLength(0);
  expect(board.message).not.toHaveBeenCalled();
  expect(c.fail).not.toHaveBeenCalled();
});

it('C7: a first frame just before EOF does not reset failures, even after slow headers/body startup', async () => {
  vi.useFakeTimers();
  const urls: string[] = [];
  const enc = new TextEncoder();
  const f = async (url: unknown) => {
    urls.push(String(url));
    if (String(url).includes('/v1/events')) return new Response(JSON.stringify({ value: [] }));
    return new Response(new ReadableStream({ start(c) {
      setTimeout(() => c.enqueue(enc.encode(': ready 100\n\n')), 40);
      setTimeout(() => c.close(), 41);
    } }));
  };
  const client = new FeedClient({ baseUrl: 'http://127.0.0.1:1', creds, fetch: f as typeof fetch, onEvent() {}, healthyAfterMs: 30, backoffMs: 1, random: () => .5 });
  try {
    client.start(); await vi.advanceTimersByTimeAsync(90);
    expect(urls.filter(u => u.includes('/v1/feed'))).toHaveLength(2);
    expect(urls.some(u => u.includes('/v1/events'))).toBe(true);
  } finally { client.dispose(); vi.useRealTimers(); }
});
