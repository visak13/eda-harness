// Simulated worker routing tests, NOT native Firefox focus evidence. No production test backdoor.
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { MessageChannel } from 'node:worker_threads';
import { it, expect, vi } from 'vitest';
const source = readFileSync(new URL('../../public/notifications-worker.js', import.meta.url), 'utf8');
function harness(actors: (string | null)[], focusFails = false) {
  const handlers = new Map<string, (event: unknown) => void>();
  const clients = actors.map((actor, i) => ({ id: `${i}`, url: 'https://board.test/ui/epics',
    focus: vi.fn(async () => { if (focusFails) throw new Error('refused'); }),
    postMessage: vi.fn((_data, ports) => { if (ports?.length) ports[0].postMessage({ actor }); }),
  }));
  const openWindow = vi.fn(async (_url: string) => {});
  const scope = { location: { origin: 'https://board.test' }, clients: { matchAll: async () => clients, openWindow },
    addEventListener: (type: string, cb: (event: unknown) => void) => handlers.set(type, cb) };
  runInNewContext(source, { self: scope, URL, MessageChannel, setTimeout, clearTimeout });
  const data = { actor: 'owner', request: 'ev-abc', url: '/ui/epic/epic-abc?request=ev-abc#m-abc' };
  const click = async (override = {}) => {
    let promise: Promise<unknown> | undefined;
    handlers.get('notificationclick')!({ notification: { data: { ...data, ...override }, close: vi.fn() }, waitUntil: (p: Promise<unknown>) => { promise = p; } });
    await promise;
  };
  return { clients, click, openWindow, handlers };
}
it('reuses only matching participant; rapid replay is coalesced and does not navigate worker-side', async () => {
  const h = harness(['other', 'owner']); await h.click(); await h.click();
  expect(h.clients[0].focus).not.toHaveBeenCalled();
  expect(h.clients[1].focus).toHaveBeenCalledTimes(1);
  expect(h.clients[1].postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'destination', actor: 'owner' }));
  expect(h.openWindow).not.toHaveBeenCalled();
});
it.each([null, '', 'malformed actor'])('unknown or malformed identity %s fails closed', async actor => {
  const h = harness([actor]); await h.click();
  expect(h.openWindow).not.toHaveBeenCalled();
});
it('focus refusal never opens another window', async () => {
  const h = harness(['owner'], true); await h.click();
  expect(h.openWindow).not.toHaveBeenCalled();
  expect(h.clients[0].postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'focus-failed' }));
});
it('client disappearance opens exactly one fresh shell with selector but no credential', async () => {
  const h = harness([]); await h.click(); await h.click();
  expect(h.openWindow).toHaveBeenCalledTimes(1);
  const url = new URL(h.openWindow.mock.calls[0][0] as unknown as string);
  expect(url.origin).toBe('https://board.test'); expect(url.searchParams.get('as')).toBe('owner');
  expect(url.searchParams.get('request')).toBe('ev-abc'); expect(url.searchParams.has('token')).toBe(false);
});
it('rejects arbitrary URLs, tokens, mismatched request IDs and non-board clients', async () => {
  const h = harness(['owner']);
  await h.click({ url: 'https://evil.test/ui/epic/epic-abc?request=ev-abc' });
  await h.click({ url: '/ui/epic/epic-abc?request=ev-abc&token=secret' });
  await h.click({ request: 'ev-other' });
  expect(h.clients[0].focus).not.toHaveBeenCalled(); expect(h.openWindow).not.toHaveBeenCalled();
  expect([...h.handlers.keys()].sort()).toEqual(['activate', 'install', 'message', 'notificationclick']);
});
