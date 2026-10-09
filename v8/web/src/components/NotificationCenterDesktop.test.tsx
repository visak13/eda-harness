import { afterEach, beforeEach, it, expect, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { server } from '../test/setup';
import { http, okJson, renderRoute } from '../pages/testUtils';
import { NotificationCenter, NotificationPanel } from './NotificationCenter';
import { attentionChanged } from '../live/notificationEvents';

// S11 (s-9277bcebc9): the desktop window raises native toasts through the shell bridge for the same attention rows
// the browser shows. The browser path (service worker + Notification permission) is covered by
// NotificationCenter.test.tsx and stays untouched; here the shell path, and that a browser never touches the bridge.

vi.mock('../live/useDraftGuard', () => ({ useDraftGuard: () => ({ hasDirty: () => false }) }));

let cursor = 4;
let count = 1;
const row = { request: 'ev-new', url: '/ui/epic/epic-one?request=ev-new#m-hello' };
const register = vi.fn(async () => ({ active: { state: 'activated', postMessage: vi.fn() } }));
const requestPermission = vi.fn(async () => 'granted');
let api: { notify: ReturnType<typeof vi.fn>; ping: ReturnType<typeof vi.fn>; open_external: ReturnType<typeof vi.fn> };

function asDesktop(toast = true) {
  api = {
    notify: vi.fn(async () => ({ ok: true })),
    ping: vi.fn(async () => ({ shell: 'heronry-desktop', platform: 'win32', toast })),
    open_external: vi.fn(async () => true),
  };
  (window as unknown as { pywebview: unknown }).pywebview = { api };
}

beforeEach(() => {
  cursor = 4; count = 1; localStorage.clear(); vi.clearAllMocks();
  vi.spyOn(document, 'hasFocus').mockReturnValue(false);
  vi.stubGlobal('isSecureContext', true);
  vi.stubGlobal('Notification', { permission: 'default', requestPermission });
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: {
    register, addEventListener: () => {}, removeEventListener: () => {} } });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  server.use(http.get('/v1/me/notifications', ({ request }) => {
    const params = new URL(request.url).searchParams;
    const since = Number(params.get('since'));
    return okJson({ participant: 'owner', cursor, requests: since >= 0 && since < cursor ? Array.from({ length: count }, (_, i) => ({ ...row, request: `ev-new-${i}` })) : [] });
  }));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); delete (window as unknown as { pywebview?: unknown }).pywebview; });

function mount() { renderRoute('/epics', '/epics', <NotificationCenter actor="owner"><NotificationPanel /></NotificationCenter>); }

it('desktop: Enable needs no browser permission or worker, only a tray that can toast', async () => {
  asDesktop();
  mount();
  expect(screen.getByText(/shown as Windows notifications while the app runs/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Enable notifications' }));
  await screen.findByRole('button', { name: 'Disable notifications' });
  expect(api.ping).toHaveBeenCalled();
  expect(requestPermission).not.toHaveBeenCalled();
  expect(register).not.toHaveBeenCalled();
  expect(localStorage.getItem('edp8.notifications.owner')).toBe('enabled');
});

it('desktop: a tray that cannot raise toasts is said plainly and nothing is enabled', async () => {
  asDesktop(false);
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'Enable notifications' }));
  await screen.findByText('The desktop tray cannot raise notifications on this system.');
  expect(localStorage.getItem('edp8.notifications.owner')).toBeNull();
});

it('desktop: the Test button raises a toast through the bridge', async () => {
  asDesktop();
  localStorage.setItem('edp8.notifications.owner', 'enabled');
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Send test notification' }));
  await screen.findByText('Test notification sent. It appears as a Windows notification.');
  expect(api.notify).toHaveBeenCalledWith('Board notification test', 'Desktop notifications work while the app runs.');
  expect(register).not.toHaveBeenCalled();
});

it('desktop: a new attention row raises exactly one generic toast; the backlog and a replay do not', async () => {
  asDesktop();
  localStorage.setItem('edp8.notifications.owner', 'enabled');
  mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 60)); });
  expect(api.notify).not.toHaveBeenCalled(); // the first poll only sets the cursor (no backlog)
  cursor = 5; act(() => attentionChanged());
  await waitFor(() => expect(api.notify).toHaveBeenCalledTimes(1));
  // privacy: the toast never carries the message text, only that something needs attention
  expect(api.notify).toHaveBeenCalledWith('Board needs your attention', 'Open the board to view your request.');
  act(() => attentionChanged());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  expect(api.notify).toHaveBeenCalledTimes(1);
  expect(register).not.toHaveBeenCalled();
});

it('desktop: a burst of rows is one combined toast, a refused toast is not retried, and the cursor moves on', async () => {
  asDesktop();
  api.notify.mockResolvedValue({ ok: false, reason: 'rate-limited' });
  localStorage.setItem('edp8.notifications.owner', 'enabled');
  mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 60)); });
  count = 7; cursor = 5; act(() => attentionChanged());
  await waitFor(() => expect(api.notify).toHaveBeenCalledTimes(1));
  expect(api.notify).toHaveBeenCalledWith('7 requests need you', 'Open the board to view your request.');
  act(() => attentionChanged());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  expect(api.notify).toHaveBeenCalledTimes(1); // the same rows are not offered again on the next poll
});

it('desktop: no toast while this window has focus (as in the browser), and those rows are still consumed', async () => {
  asDesktop();
  const focus = vi.spyOn(document, 'hasFocus').mockReturnValue(true);
  localStorage.setItem('edp8.notifications.owner', 'enabled');
  mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 60)); });
  cursor = 5; act(() => attentionChanged());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  expect(api.notify).not.toHaveBeenCalled();
  focus.mockReturnValue(false);
  act(() => attentionChanged());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  expect(api.notify).not.toHaveBeenCalled(); // seen while focused, not deferred into a later toast
});

it('desktop: Disable stops toasts', async () => {
  asDesktop();
  localStorage.setItem('edp8.notifications.owner', 'enabled');
  mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 60)); });
  fireEvent.click(screen.getByRole('button', { name: 'Disable notifications' }));
  cursor = 6; act(() => attentionChanged());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  expect(api.notify).not.toHaveBeenCalled();
});

it('browser: no bridge is ever called, and the worker path still needs an explicit Enable and permission', async () => {
  mount();
  expect(screen.getByText(/Keep a board tab open; no delivery when the browser is closed/)).toBeInTheDocument();
  expect(requestPermission).not.toHaveBeenCalled();
  expect(register).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Enable notifications' }));
  await waitFor(() => expect(requestPermission).toHaveBeenCalledTimes(1));
  expect((window as unknown as { pywebview?: unknown }).pywebview).toBeUndefined();
});
