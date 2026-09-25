// Bounded C7 reproductions: assert the observed faulty behavior, not acceptance.
import { expect, it, vi } from 'vitest';
import { FeedClient } from '../src/core/feed';
import { InboxHost } from '../src/vscode/inbox';
import type { Board } from '../src/core/api';

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
