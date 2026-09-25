// C26 s-7b8efb9b7a: e965e4a's viewer guards narrowed to the class the ticket names (qa m-ed30a7df6e Q1-Q5).
// Rule 1: only a 401 (or a credentials/URL change) resets the viewer; a 403 stays in its tab.
// Rule 2: identity and refresh are separate generations; a write checks identity only.
import { expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ warnings: [] as string[], status: [] as string[] }));
vi.mock('vscode', () => ({
  window: {
    showWarningMessage: (t: string) => { h.warnings.push(t); }, showErrorMessage: (t: string) => { h.warnings.push(t); },
    setStatusBarMessage: (t: string) => { h.status.push(t); },
  },
  commands: { executeCommand: async () => undefined },
}));

import { authFailed, ViewerRequests } from '../src/core/viewer';
import { BoardError, type Board } from '../src/core/api';
import { FeedClient } from '../src/core/feed';
import { InboxHost } from '../src/vscode/inbox';
import { ChatController } from '../src/vscode/chat';
import { DocReader } from '../src/vscode/reader';
import { QuoteHost } from '../src/vscode/quotes';
import { messageDraft, Tray } from '../src/core/quotes';
import type { ReaderDoc, ReaderGate } from '../src/core/reader';

/** A promise the test settles by hand: the write that is in flight while a refresh lands. */
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

const creds = async () => ({ participant: 'teammate', token: 'throwaway' });
const forbidden = () => new Response(JSON.stringify({ ok: false, error: { code: 'forbidden', message: 'teammate is not a participant of epic-0123456789' } }), { status: 403 });

it('C26 Q1: a resource 403 is the caller\'s refusal; the viewer and its other requests stay live', async () => {
  const onAuth = vi.fn();
  const f = vi.fn(async (url: unknown) => String(url).includes('/v1/decisions')
    ? forbidden() : new Response(JSON.stringify({ ok: true, value: { id: 's-0123456789' } }), { status: 200 }));
  const board = new ViewerRequests(onAuth, f as typeof fetch).board('http://127.0.0.1:1', creds, () => {});
  const err = await board.scopeDecisions('epic-0123456789').catch(e => e);
  expect(err).toMatchObject({ code: 'forbidden', status: 403 });
  expect(authFailed(err)).toBe(false);
  expect(onAuth).not.toHaveBeenCalled();
  await expect(board.ticket('s-0123456789')).resolves.toMatchObject({ id: 's-0123456789' }); // not blocked
});

it('C26 Q1: a 401 (and missing creds) is still an identity failure', () => {
  expect(authFailed(new BoardError('unauthorized', 'bad token', 401))).toBe(true);
  expect(authFailed(new BoardError('not_signed_in', 'sign in', 0))).toBe(true);
  expect(authFailed(new BoardError('forbidden', 'not a participant', 403))).toBe(false);
});

it('C26 Q1: ChatController.fail shows a 403 as an error and never clears the viewer', () => {
  const post = vi.fn(), clearViewer = vi.fn();
  const c = Object.assign(Object.create(ChatController.prototype), { post, clearViewer });
  c.fail(new BoardError('forbidden', 'teammate is not a participant of epic-0123456789', 403), 'could not use the Decisions tab');
  expect(clearViewer).not.toHaveBeenCalled();
  expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', text: expect.stringContaining('not a participant') }));
  c.fail(new BoardError('unauthorized', 'bad token', 401), 'could not send');
  expect(clearViewer).toHaveBeenCalledOnce();
});

it('C26 Q1: an Inbox 403 shows in its tab without signing out', async () => {
  const onAuthFail = vi.fn(), post = vi.fn();
  const board = { decisions: async () => { throw new BoardError('forbidden', 'not permitted', 403); } } as unknown as Board;
  const sc = { id: 's-0123456789', ids: new Set(['s-0123456789']), titles: new Map() };
  const h = new InboxHost(() => board, () => 'http://127.0.0.1:1', () => sc, post, async () => {}, onAuthFail, () => {});
  try {
    await h.open();
    expect(onAuthFail).not.toHaveBeenCalled();
    expect(h.snapshot(sc.id)).toMatchObject({ loading: false, items: [], error: expect.stringContaining('not permitted') });
  } finally { h.dispose(); }
});

it('C26 Q1: a feed 403 is retried, not a sign-out; a 401 still signs out', async () => {
  vi.useFakeTimers();
  const statuses: string[] = [];
  let code = 403;
  const f = vi.fn(async () => new Response('{}', { status: code }));
  const client = new FeedClient({ baseUrl: 'http://127.0.0.1:1', creds, fetch: f as never, onEvent() {}, onStatus: s => statuses.push(s), backoffMs: 10, random: () => .5 });
  try {
    client.start();
    await vi.advanceTimersByTimeAsync(50);
    expect(statuses).not.toContain('signed-out');
    expect(f.mock.calls.length).toBeGreaterThan(1);
    code = 401;
    await vi.advanceTimersByTimeAsync(40_000);
    expect(statuses).toContain('signed-out');
  } finally { client.dispose(); await vi.advanceTimersByTimeAsync(0); vi.useRealTimers(); }
});

// -- rule 2: a refresh never drops a write result (Q3 Inbox, Q4 reader, Q5 first Add to chat) --------------------

const STORY = 's-0123456789';
const question = { id: 'm-1111111111', ticket_id: STORY, text: 'ship it?', created_by: 'arch', created_at: '2026-09-25T00:00:00Z', kind: 'question' };

function inbox(send: () => Promise<unknown>) {
  const posts: any[] = [];
  const onAuthFail = vi.fn();
  const board = { decisions: vi.fn(async () => ({ questions: [question], signoffs: [], gates: [], counts: {} })), send: vi.fn(send) };
  const sc = { id: STORY, ids: new Set([STORY]), titles: new Map([[STORY, 'Story']]) };
  const host = new InboxHost(() => board as unknown as Board, () => 'http://127.0.0.1:1', () => sc, m => posts.push(m), async () => {}, onAuthFail, () => {});
  return { host, posts, onAuthFail, board, done: () => posts.filter(m => m.type === 'inboxDone') };
}

it('C26 Q3: an Inbox answer with a refresh landing mid-write ends busy and removes the row', async () => {
  const w = deferred<unknown>();
  const t = inbox(() => w.promise);
  try {
    await t.host.open();
    const key = t.host.snapshot(STORY)!.items[0].key;
    const answering = t.host.answer(key, 'yes, ship it');
    await vi.waitFor(() => expect(t.board.send).toHaveBeenCalledOnce());
    await t.host.refresh(); // the feed event the answer itself causes
    w.resolve({ id: 'm-2222222222' });
    await answering;
    expect(t.done()).toEqual([{ type: 'inboxDone', v: 1, key, ok: true, text: 'Answered @arch.' }]);
    expect(t.host.snapshot(STORY)!.items).toHaveLength(0);
  } finally { t.host.dispose(); }
});

it('C26 Q3: an Inbox refusal with a refresh landing mid-write is shown on the row, not hidden', async () => {
  const w = deferred<unknown>();
  const t = inbox(() => w.promise);
  try {
    await t.host.open();
    const key = t.host.snapshot(STORY)!.items[0].key;
    const answering = t.host.answer(key, 'yes');
    await vi.waitFor(() => expect(t.board.send).toHaveBeenCalledOnce());
    await t.host.refresh();
    w.reject(new BoardError('forbidden', 'you may not answer on this ticket', 403));
    await answering;
    expect(t.done()).toEqual([{ type: 'inboxDone', v: 1, key, ok: false, text: 'you may not answer on this ticket' }]);
    expect(t.onAuthFail).not.toHaveBeenCalled();
  } finally { t.host.dispose(); }
});

it('C26 Q3 keeps C7: another identity mid-write still drops the old write result', async () => {
  const w = deferred<unknown>();
  const t = inbox(() => w.promise);
  try {
    await t.host.open();
    const answering = t.host.answer(t.host.snapshot(STORY)!.items[0].key, 'yes');
    await vi.waitFor(() => expect(t.board.send).toHaveBeenCalledOnce());
    t.host.clear(); // ChatController.clearViewer
    w.resolve({ id: 'm-2222222222' });
    await answering;
    expect(t.done()).toEqual([]);
  } finally { t.host.dispose(); }
});

const rdoc: ReaderDoc = { id: 'design-aaaaaaaaaa', title: 'D', docType: 'design', status: 'proposed', version: 12, versions: [11, 12], current: 12, body: '# D', proposes: null, resolution: null };
const rgate: ReaderGate = { ticketId: 'epic-0000000001', ticketTitle: 'E', gateEventId: 'ev-1', canApprove: true, canReview: true, currentVersion: 12, designRef: rdoc.id };

function reader(decide: () => Promise<unknown>) {
  const p: any = { id: rdoc.id, version: 12, ready: true, posts: [] as any[], next: () => 1, current: () => true, panel: { title: '' },
    state: { type: 'doc', v: 1, doc: rdoc, gate: rgate, gateError: null, canResolve: false, diff: null, comments: null, loading: false, error: null } };
  p.post = (m: unknown) => p.posts.push(m);
  const onAuthFail = vi.fn();
  const r: any = Object.assign(Object.create(DocReader.prototype), { viewer: 0, panels: new Set([p]), active: null, sources: new Map(), reveals: new Map(),
    board: () => ({ decide: vi.fn(decide) }), onAuthFail, log() {} });
  r.load = vi.fn(async () => {}); // the write's own re-read after it settles
  const refresh = () => r.set(p, { doc: { ...rdoc }, gate: { ...rgate } }); // a feed-triggered load: the same version, new objects
  return { r, p, onAuthFail, refresh, done: () => p.posts.filter((m: any) => m.type === 'done') };
}

it('C26 Q4: reader Approve with a refresh landing mid-write shows its result', async () => {
  const w = deferred<unknown>();
  const t = reader(() => w.promise);
  const approving = t.r.approve(t.p);
  t.refresh();
  w.resolve({});
  await approving;
  expect(t.done()).toEqual([{ type: 'done', v: 1, what: 'approve', ok: true, text: `Approved ${rdoc.id} v12.` }]);
  expect(t.r.load).toHaveBeenCalledWith(t.p);
});

it('C26 Q4: reader Request changes refused mid-refresh shows the refusal (busy ends)', async () => {
  h.warnings = [];
  const w = deferred<unknown>();
  const t = reader(() => w.promise);
  const asking = t.r.requestChanges(t.p, 'fix §3');
  t.refresh();
  w.reject(new BoardError('stale', 'the design is now v13', 409));
  await asking;
  expect(t.done()).toEqual([{ type: 'done', v: 1, what: 'requestChanges', ok: false, text: 'the design is now v13' }]);
  expect(h.warnings).toEqual(['EDP: the design is now v13']);
  expect(t.onAuthFail).not.toHaveBeenCalled();
});

it('C26 Q4 keeps C7: reset() (another identity) mid-write drops the old write result', async () => {
  const w = deferred<unknown>();
  const t = reader(() => w.promise);
  const approving = t.r.approve(t.p);
  t.r.reset();
  w.resolve({});
  await approving;
  expect(t.done()).toEqual([]);
});

function quoteHost(pick: (q: any) => Promise<string | undefined>) {
  const data = new Map<string, unknown>();
  let open: { id: string; title: string } | null = null;
  const q: any = Object.assign(Object.create(QuoteHost.prototype), {
    tray: new Tray(), identity: null, invalid: new Map(), markers: new Map(),
    ctx: { workspaceState: { get: (k: string) => data.get(k), update: async (k: string, v: unknown) => { data.set(k, v); } } },
    ctl: { dispose() {} }, controller: () => ({ dispose() {} }), syncMarkers() {}, syncNotes() {}, updateStatus() {}, post() {},
    chat: { onMarks() {}, target: () => open, pick: async () => { const id = await pick(q); if (id) open = { id, title: 'Story' }; return id; } },
  });
  return q;
}
const A = { origin: 'http://127.0.0.1:9400', participant: 'owner' };
const draft = () => messageDraft({ id: 'm-1111111111', text: 'a passage to quote', created_by: 'arch' }, 'a passage to quote', '', 'why?');

it('C26 Q5: the first Add to chat, with the chat never opened, survives the first chat boot and adds the quote', async () => {
  const q = quoteHost(async host => { host.setIdentity(A); return STORY; }); // the pick boots the chat: identity null -> A
  await expect(q.add(draft())).resolves.toBe(STORY);
  expect(q.chips(STORY)).toHaveLength(1);
  expect(q.chips(STORY)[0].note).toBe('why?');
});

it('C26 Q5 keeps C7: an identity switch during the pick drops the quote, said on the status bar', async () => {
  h.status = [];
  const q = quoteHost(async host => { host.setIdentity({ ...A, participant: 'other' }); return STORY; });
  q.setIdentity(A);
  await expect(q.add(draft())).resolves.toBeUndefined();
  expect(q.chips(STORY)).toHaveLength(0);
  q.setIdentity(A);
  expect(q.chips(STORY)).toHaveLength(0); // nothing landed in A's tray either
  expect(h.status).toEqual(['EDP: the board sign-in changed, so the quote was not added']);
});
