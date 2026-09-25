// C26 s-7b8efb9b7a: e965e4a's viewer guards narrowed to the class the ticket names (qa m-ed30a7df6e Q1-Q5).
// Rule 1: only a 401 (or a credentials/URL change) resets the viewer; a 403 stays in its tab.
// Rule 2: identity and refresh are separate generations; a write checks identity only.
import { expect, it, vi } from 'vitest';
import { authFailed, ViewerRequests } from '../src/core/viewer';
import { BoardError, type Board } from '../src/core/api';
import { FeedClient } from '../src/core/feed';
import { InboxHost } from '../src/vscode/inbox';
import { ChatController } from '../src/vscode/chat';

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
