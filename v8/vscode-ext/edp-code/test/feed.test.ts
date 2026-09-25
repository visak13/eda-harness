import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FeedStatus } from '../src/core/chatProtocol';
import { FeedClient, type FeedEvent } from '../src/core/feed';

const TOKEN = 'feed-secret-tok-9f2c';
const creds = async () => ({ participant: 'owner', token: TOKEN });

function stream() {
  let c!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(x) { c = x; } });
  const enc = new TextEncoder();
  return { body, push: (s: string) => c.enqueue(enc.encode(s)), end: () => c.close() };
}

type Call = { url: string; headers: Record<string, string> };

/** A fake fetch: each /v1/feed call takes the next scripted response. */
function fakeFetch(feeds: (() => Response | Promise<Response>)[], events: () => unknown[] = () => []) {
  const calls: Call[] = [];
  const f = vi.fn(async (u: URL | string, init?: RequestInit) => {
    const url = String(u);
    calls.push({ url, headers: init?.headers as Record<string, string> });
    if (url.includes('/v1/events')) return new Response(JSON.stringify({ ok: true, value: events() }), { status: 200 });
    const next = feeds.shift();
    if (!next) return new Promise<Response>((_, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))));
    return next();
  });
  return { f: f as unknown as typeof fetch, calls };
}

function client(f: typeof fetch, extra: Partial<ConstructorParameters<typeof FeedClient>[0]> = {}) {
  const events: FeedEvent[] = [];
  const statuses: FeedStatus[] = [];
  const logs: string[] = [];
  const ready: number[] = [];
  let resyncs = 0;
  const c = new FeedClient({
    baseUrl: 'http://127.0.0.1:9400', creds, fetch: f, onEvent: e => events.push(e), onStatus: s => statuses.push(s),
    onReady: n => ready.push(n), onResync: () => { resyncs++; }, log: l => logs.push(l), random: () => 0.5, ...extra,
  });
  return { c, events, statuses, logs, ready, resyncs: () => resyncs };
}

const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('FeedClient', () => {
  it('sends X-Participant + X-Token with watch=true, adopts the ready cursor, skips seq <= since', async () => {
    const s = stream();
    const { f, calls } = fakeFetch([() => new Response(s.body, { status: 200 })]);
    const t = client(f);
    t.c.start(-1);
    await flush();
    expect(calls[0].url).toBe('http://127.0.0.1:9400/v1/feed?since=-1&watch=true');
    expect(calls[0].headers['X-Participant']).toBe('owner');
    expect(calls[0].headers['X-Token']).toBe(TOKEN);
    s.push(': ready 100\n\n');
    await flush();
    expect(t.ready).toEqual([100]);
    expect(t.c.since).toBe(100);
    expect(t.statuses).toContain('live');
    s.push('data: {"seq":99,"kind":"message_sent"}\n\ndata: {"seq":101,"kind":"message_sent","subject_id":"s-b00dbbcdea"}\n\n');
    await flush();
    expect(t.events.map(e => e.seq)).toEqual([101]);
    s.push('data: {"seq":101,"kind":"message_sent"}\n\n'); // replayed
    await flush();
    expect(t.events).toHaveLength(1);
    t.c.dispose();
  });

  it('a resync reconnects at once from the resync cursor (no backoff) and asks for a reload', async () => {
    const a = stream(), b = stream();
    const { f, calls } = fakeFetch([() => new Response(a.body), () => new Response(b.body)]);
    const t = client(f);
    t.c.start(-1);
    await flush();
    a.push(': ready 10\n\n: resync 40\n\n');
    await flush();
    expect(t.resyncs()).toBe(1);
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain('since=40');
    t.c.dispose();
  });

  it('a drop reconnects from the last seq; two failures fall back to polling /v1/events', async () => {
    const a = stream();
    let polled: unknown[] = [{ seq: 12, kind: 'message_sent', subject_id: 's-b00dbbcdea' }];
    const { f, calls } = fakeFetch([
      () => new Response(a.body),
      () => new Response('nope', { status: 502 }),
    ], () => { const v = polled; polled = []; return v; });
    const t = client(f, { backoffMs: 1000 });
    t.c.start(-1);
    await flush();
    a.push(': ready 10\n\ndata: {"seq":11}\n\n');
    await flush();
    a.end(); // the server closed after real traffic: failure 1
    await flush();
    expect(t.statuses).toContain('reconnecting');
    await vi.advanceTimersByTimeAsync(1000);
    expect(calls[1].url).toContain('since=11');
    await flush(); // 502: failure 2 -> poll
    expect(calls[2].url).toBe('http://127.0.0.1:9400/v1/events?since=11&limit=200&watch=true');
    expect(calls[2].headers['X-Token']).toBe(TOKEN);
    await flush();
    expect(t.events.map(e => e.seq)).toEqual([11, 12]);
    expect(t.statuses).toContain('polling');
    t.c.dispose();
    expect(t.c.pendingTimers).toBe(0);
  });

  it('a cold start with the board down never polls from 0 (no history replay); it keeps retrying the stream', async () => {
    const { f, calls } = fakeFetch([
      () => new Response('down', { status: 502 }), () => new Response('down', { status: 502 }), () => new Response('down', { status: 502 }),
    ]);
    const t = client(f, { backoffMs: 1000 });
    t.c.start(-1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(calls.some(c => c.url.includes('/v1/events'))).toBe(false);
    expect(calls.filter(c => c.url.includes('/v1/feed?since=-1')).length).toBeGreaterThanOrEqual(3);
    t.c.dispose();
    expect(t.c.pendingTimers).toBe(0);
  });

  it('45 s of silence aborts the stream and counts a failure', async () => {
    const a = stream();
    const { f, calls } = fakeFetch([() => new Response(a.body)]);
    const t = client(f);
    t.c.start(-1);
    await flush();
    a.push(': ready 5\n\n');
    await flush();
    await vi.advanceTimersByTimeAsync(44_000);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(t.logs.some(l => /no bytes for 45s/.test(l))).toBe(true);
    expect(t.statuses).toContain('reconnecting');
    t.c.dispose();
  });

  it('401 stops the client: signed-out, no retry loop', async () => {
    const { f, calls } = fakeFetch([() => new Response('{}', { status: 401 })]);
    const t = client(f);
    t.c.start(-1);
    await flush();
    expect(t.statuses).toContain('signed-out');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls).toHaveLength(1);
    expect(t.c.pendingTimers).toBe(0);
  });

  it('refuses to send creds to a non-loopback http board', async () => {
    const { f, calls } = fakeFetch([]);
    const t = client(f, { baseUrl: 'http://10.0.0.5:9400' });
    t.c.start(-1);
    await flush();
    expect(calls).toHaveLength(0);
    expect(t.statuses).toContain('signed-out');
  });

  it('dispose() aborts the stream and leaves zero pending timers; a second start opens no second stream', async () => {
    const a = stream();
    const { f, calls } = fakeFetch([() => new Response(a.body)]);
    const t = client(f);
    t.c.start(-1);
    t.c.start(-1);
    await flush();
    a.push(': ready 1\n\n');
    await flush();
    expect(calls).toHaveLength(1);
    expect(t.c.pendingTimers).toBeGreaterThan(0); // the read watchdog
    t.c.dispose();
    await flush();
    expect(t.c.pendingTimers).toBe(0);
    expect(t.statuses.at(-1)).toBe('stopped');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls).toHaveLength(1);
  });

  it('logs never carry the token or event text', async () => {
    const a = stream();
    const { f } = fakeFetch([() => new Response(a.body)]);
    const t = client(f);
    t.c.start(-1);
    await flush();
    a.push(': ready 1\n\ndata: {"seq":2,"data":{"text":"private words"}}\n\n');
    await flush();
    a.end();
    await flush();
    t.c.dispose();
    const all = t.logs.join('\n');
    expect(all).not.toContain(TOKEN);
    expect(all).not.toContain('private words');
  });
});
