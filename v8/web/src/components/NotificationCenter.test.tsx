import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { server } from '../test/setup';
import { http, okJson, renderRoute } from '../pages/testUtils';
import { NotificationCenter, NotificationPanel } from './NotificationCenter';
import { attentionChanged } from '../live/notificationEvents';

let dirty = false;
const guard = { hasDirty: () => dirty };
vi.mock('../live/useDraftGuard', () => ({ useDraftGuard: () => guard }));
const requestPermission = vi.fn(async () => 'granted');
const workerPost = vi.fn((_data, ports) => ports[0].postMessage({ shown: true }));
const register = vi.fn(async () => ({ active: { state: 'activated', postMessage: workerPost } }));
let messages: EventTarget;
let permission = 'default';
let cursor = 4;
let available = true;
const row = { request: 'ev-new', url: '/ui/epic/epic-one?request=ev-new#m-hello' };
class Channel {
  port1 = { onmessage: null as ((event: { data: unknown }) => void) | null, close: () => {} };
  port2 = { postMessage: (data: unknown) => this.port1.onmessage?.({ data }) };
}
beforeEach(() => {
  dirty = false; permission = 'default'; cursor = 4; available = true;
  localStorage.clear(); vi.clearAllMocks();
  messages = new EventTarget();
  vi.stubGlobal('isSecureContext', true);
  vi.stubGlobal('Notification', { get permission() { return permission; }, requestPermission });
  vi.stubGlobal('MessageChannel', Channel);
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { register,
    addEventListener: messages.addEventListener.bind(messages), removeEventListener: messages.removeEventListener.bind(messages) } });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  server.use(http.get('/v1/me/notifications', ({ request }) => {
    expect(request.headers.get('X-Participant')).toBeTruthy();
    const params = new URL(request.url).searchParams;
    return okJson({ participant: 'owner', cursor, requests: available && (params.has('request') || (Number(params.get('since')) >= 0 && Number(params.get('since')) < cursor)) ? [row] : [] });
  }));
});
afterEach(() => vi.unstubAllGlobals());
// The effects live in the headless provider; the UI moved into NotificationPanel (S10
// c-1165c735b6). The panel is rendered as the provider's child (as AppShell places it in the
// account menu) so these assertions keep exercising the same buttons and status.
function mount() { renderRoute('/epics', '/epics', <NotificationCenter actor="owner"><NotificationPanel /></NotificationCenter>); }
function destination(actor = 'owner') {
  act(() => messages.dispatchEvent(new MessageEvent('message', { data: { protocol: 'edp8-notifications-v1', type: 'destination', actor, ...row } })));
}
it('never prompts or registers on mount; explicit enable and test use generic worker protocol', async () => {
  mount();
  expect(requestPermission).not.toHaveBeenCalled(); expect(register).not.toHaveBeenCalled();
  permission = 'granted';
  fireEvent.click(screen.getByRole('button', { name: 'Enable notifications' }));
  await waitFor(() => expect(register).toHaveBeenCalled());
  expect(requestPermission).toHaveBeenCalledTimes(1);
  expect(workerPost).not.toHaveBeenCalled(); // initial backlog suppressed
  fireEvent.click(screen.getByRole('button', { name: 'Send test notification' }));
  await screen.findByText('Test notification sent. Click it to focus this tab.');
  expect(workerPost.mock.calls[0][0]).toMatchObject({ actor: 'owner', test: true, type: 'show' });
  expect(JSON.stringify(workerPost.mock.calls)).not.toMatch(/X-Token|PRIVATE BODY/);
});
it('existing feed wakes polling without backlog; replay does not reshow, disable stops it', async () => {
  permission = 'granted'; localStorage.setItem('edp8.notifications.owner', 'enabled'); mount();
  await waitFor(() => expect(register).toHaveBeenCalled());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
  cursor = 5; act(() => attentionChanged());
  await waitFor(() => expect(workerPost).toHaveBeenCalledTimes(1));
  act(() => attentionChanged());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 300)); });
  expect(workerPost).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Disable notifications' }));
  cursor = 6; act(() => attentionChanged());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 300)); });
  expect(workerPost).toHaveBeenCalledTimes(1);
});
it('holds dirty draft destination, reauthorizes before explicit navigation', async () => {
  dirty = true; mount(); destination();
  const open = await screen.findByRole('button', { name: 'Open waiting request' });
  expect(screen.queryByTestId('elsewhere')).toBeNull();
  fireEvent.click(open); expect(screen.queryByTestId('elsewhere')).toBeNull();
  dirty = false; fireEvent.click(open);
  await screen.findByTestId('elsewhere');
});
it('wrong identity and resolved clicks never navigate', async () => {
  mount(); destination('other');
  expect(screen.queryByTestId('elsewhere')).toBeNull();
  available = false; destination();
  await screen.findByText(/This request is resolved or unavailable/);
  expect(screen.queryByTestId('elsewhere')).toBeNull();
});
it('disable invalidates an authorization already waiting for the server', async () => {
  permission = 'granted'; localStorage.setItem('edp8.notifications.owner', 'enabled'); mount();
  await waitFor(() => expect(register).toHaveBeenCalled());
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const started = vi.fn();
  server.use(http.get('/v1/me/notifications', async ({ request }) => {
    if (new URL(request.url).searchParams.has('request')) { started(); await held; }
    return okJson({ participant: 'owner', cursor, requests: [row] });
  }));
  const reply = vi.fn();
  act(() => messages.dispatchEvent(new MessageEvent('message', { data: { protocol: 'edp8-notifications-v1', type: 'authorize', request: row.request }, ports: [{ postMessage: reply } as unknown as MessagePort] })));
  await waitFor(() => expect(started).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button', { name: 'Disable notifications' }));
  await act(async () => release());
  await waitFor(() => expect(reply).toHaveBeenCalledWith({ actor: null }));
});
it('controller replacement reacquires the worker without resetting the delivery cursor', async () => {
  permission = 'granted'; localStorage.setItem('edp8.notifications.owner', 'enabled'); mount();
  await waitFor(() => expect(register).toHaveBeenCalledTimes(1));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
  cursor = 5;
  act(() => messages.dispatchEvent(new Event('controllerchange')));
  await waitFor(() => expect(register).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(workerPost).toHaveBeenCalledTimes(1));
});
it('denied, offline and insecure states remain truthful with Needs you fallback', async () => {
  permission = 'denied'; mount();
  expect(screen.getByRole('status')).toHaveTextContent('Notifications blocked');
  expect(screen.getByRole('link', { name: 'Needs you' })).toHaveAttribute('href', '/me');
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
  act(() => window.dispatchEvent(new Event('offline')));
  expect(screen.getByRole('status')).toHaveTextContent('Offline');
  vi.stubGlobal('isSecureContext', false);
  act(() => window.dispatchEvent(new Event('offline')));
  expect(screen.getByRole('status')).toHaveTextContent('HTTPS or localhost');
});
