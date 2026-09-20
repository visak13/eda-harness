import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api/client';
import { attention, type AttentionRequest } from '../api/notifications';
import { useDraftGuard } from '../live/useDraftGuard';
import { onAttentionChanged } from '../live/notificationEvents';
import { pendingWork } from './PendingNavigation';
import styles from './NotificationCenter.module.css';
import { Icon } from './Icon';

const protocol = 'edp8-notifications-v1';
const supported = () => window.isSecureContext && 'Notification' in window && 'serviceWorker' in navigator;
const pref = (actor: string) => `edp8.notifications.${actor}`;
function enabledFor(actor: string): boolean {
  try { return localStorage.getItem(pref(actor)) === 'enabled'; } catch { return false; }
}
export function notificationState(enabled: boolean): string {
  if (!window.isSecureContext) return 'Notifications require HTTPS or localhost.';
  if (!('Notification' in window) || !('serviceWorker' in navigator)) return 'This browser does not support board notifications.';
  if (!navigator.onLine) return 'Offline — notifications cannot receive new requests.';
  if (Notification.permission === 'denied') return 'Notifications blocked. Change browser permissions to enable them.';
  if (Notification.permission !== 'granted') return 'Notifications are not enabled. Permission is requested only when you choose Enable.';
  return enabled ? 'Notifications enabled while a board tab stays open.' : 'Notifications are off for this participant.';
}
async function worker(): Promise<ServiceWorker> {
  const registration = await navigator.serviceWorker.register('/ui/notifications-worker.js', { scope: '/ui/' });
  const active = registration.active ?? registration.installing ?? registration.waiting;
  if (!active) throw new Error('Notification worker unavailable');
  if (active.state !== 'activated') await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { active.removeEventListener('statechange', change); reject(new Error('Notification worker timed out')); }, 10000);
    const change = () => {
      if (active.state === 'activated' || active.state === 'redundant') {
        clearTimeout(timer); active.removeEventListener('statechange', change);
        if (active.state === 'activated') resolve(); else reject(new Error('Notification worker unavailable'));
      }
    };
    active.addEventListener('statechange', change); change();
  });
  return registration.active ?? active;
}
export async function showAttention(target: ServiceWorker, actor: string, row: AttentionRequest, test = false): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => { channel.port1.close(); reject(new Error('Notification worker did not respond. Use Needs you.')); }, 10000);
    channel.port1.onmessage = event => {
      clearTimeout(timer); channel.port1.close();
      if (event.data?.error) reject(new Error(event.data.error)); else resolve();
    };
    target.postMessage({ protocol, type: 'show', actor, ...row, test }, [channel.port2]);
  });
}

// S10 criterion c-1165c735b6 / revision3-clean-usage: Notifications is NOT a rail item. The worker
// poll and the S5 request-authorization must keep running whenever a board tab is open, so the
// EFFECTS live in a headless provider (NotificationCenter) mounted once in the shell, while the UI
// (Enable / Disable / Test / status) is rendered by NotificationPanel INSIDE the account menu.
// Request-level statuses and a waiting destination surface globally (a toast), independent of the
// menu, because a request can arrive while the menu is closed.
interface NotificationApi {
  enabled: boolean;
  status: string;
  busy: boolean;
  supported: boolean;
  pending: AttentionRequest | null;
  enable: () => void;
  disable: () => void;
  test: () => void;
  openPending: () => void;
  dismissPending: () => void;
}
const NotificationCtx = createContext<NotificationApi | null>(null);

/** The account-menu UI. Reads the shared notification state from context; renders nothing outside a
 *  provider. The account menu is itself the disclosure, so there is no rail row / <details> here. */
export function NotificationPanel(): React.JSX.Element | null {
  const n = useContext(NotificationCtx);
  if (!n) return null;
  const configStatus = !(n.status.startsWith('Request ') || n.status.startsWith('Could not') || n.status.startsWith('This request'));
  return <section className={styles.root} aria-label="Board notifications" data-testid="notification-panel">
    <h3 className={styles.heading}><Icon name="warning" size={16} /> Notifications</h3>
    <p>Private alerts for new questions and approval requests. Keep a board tab open; no delivery when the browser is closed.</p>
    <div className={styles.actions}>
      {!n.enabled ? <button disabled={n.busy || !n.supported} onClick={n.enable}>Enable notifications</button> : <>
        <button onClick={n.disable}>Disable notifications</button>
        <button disabled={n.busy} onClick={n.test}>Send test notification</button>
      </>}
      <Link to="/me">Needs you</Link>
    </div>
    {configStatus ? <p role="status">{n.status}</p> : null}
  </section>;
}

/** The worker holds selectors only. Every identity challenge and click rechecks server authority. */
export function NotificationCenter({ actor, children }: { actor: string; children?: React.ReactNode }): React.JSX.Element {
  const navigate = useNavigate();
  const { hasDirty } = useDraftGuard();
  const [enabled, setEnabled] = useState(() => enabledFor(actor));
  const [status, setStatus] = useState(() => notificationState(enabled));
  const [pending, setPending] = useState<AttentionRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const enabledRef = useRef(enabled);
  const authorizationGeneration = useRef(0);
  const changeEnabled = useCallback((value: boolean) => {
    enabledRef.current = value; authorizationGeneration.current += 1; setEnabled(value);
  }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  // The provider is not remounted by key on identity change (that would remount the whole shell), so
  // reset its per-participant selectors when `actor` changes — a re-login must not carry the previous
  // person's enabled/status/pending. The poll and message effects re-subscribe via their `actor` dep.
  const actorRef = useRef(actor);
  useEffect(() => {
    if (actorRef.current === actor) return;   // skip the initial mount
    actorRef.current = actor;
    const on = enabledFor(actor);
    enabledRef.current = on; authorizationGeneration.current += 1;
    setEnabled(on); setStatus(notificationState(on)); setPending(null);
  }, [actor]);
  const open = useCallback(async (request: string, initial = false) => {
    const landing = new URL(window.location.href);
    try {
      const value = await attention(-1, request);
      if (!alive.current || value.participant !== actor) return;
      const row = value.requests.find(item => item.request === request);
      if (!row) { setPending(null); setStatus('This request is resolved or unavailable to this participant. Use Needs you.'); return; }
      const current = new URL(window.location.href);
      const destination = new URL(row.url, window.location.origin);
      if (initial) {
        // Authorization validates the landing; it must not replay navigation over a
        // viewer opened meanwhile, a dismissed viewer, or a later user destination.
        if (current.pathname !== landing.pathname || current.searchParams.get('request') !== request) return;
        if (current.pathname === destination.pathname && current.searchParams.get('request') === destination.searchParams.get('request')) {
          setStatus('Request opened in this tab.'); return;
        }
      }
      if (hasDirty() || pendingWork()) {
        setPending(row); setStatus('Request ready. Finish or save your current draft, then open it here. Your draft has not moved.');
      } else { setPending(null); setStatus('Request opened in this tab.'); navigate(row.url.replace(/^\/ui/, '')); }
    } catch { if (alive.current) setStatus('Could not authorize this request. Check your connection or identity; use Needs you.'); }
  }, [actor, hasDirty, navigate]);
  useEffect(() => {
    if (!supported()) return;
    let stopped = false;
    const listener = (event: MessageEvent) => {
      if (event.data?.protocol !== protocol) return;
      if (event.data.type === 'destination') {
        if (event.data.actor === actor && !event.data.test) void open(event.data.request);
        else if (event.data.actor === actor) setStatus('Notification test clicked — this existing tab was reused.');
      } else if (event.data.type === 'identify' || event.data.type === 'authorize') {
        void (async () => {
          try {
            if (event.data.type === 'authorize') {
              if (!enabledRef.current || Notification.permission !== 'granted') throw new Error('disabled');
              const generation = authorizationGeneration.current;
              const value = await attention(-1, event.data.test ? undefined : event.data.request);
              if (stopped || generation !== authorizationGeneration.current || !enabledRef.current || Notification.permission !== 'granted') throw new Error('disabled');
              const row = value.requests.find(item => item.request === event.data.request);
              event.ports[0]?.postMessage({ actor: value.participant, url: row?.url });
            } else {
              const value = await api<{ participant: { id: string } }>('/v1/whoami');
              if (!stopped) event.ports[0]?.postMessage({ actor: value.participant.id });
            }
          } catch { if (!stopped) event.ports[0]?.postMessage({ actor: null }); }
        })();
      } else if (event.data.type === 'focus-failed') setStatus('Browser could not focus this tab. No extra tab was opened. Use Needs you.');
    };
    navigator.serviceWorker.addEventListener('message', listener);
    return () => { stopped = true; navigator.serviceWorker.removeEventListener('message', listener); };
  }, [actor, open]);
  // A toast whose original client disappeared opens a fresh shell without credentials.
  useEffect(() => {
    const request = new URL(location.href).searchParams.get('request');
    if (request) void open(request, true);
  }, []); // only initial load; normal source navigation remains S3's responsibility
  useEffect(() => {
    let stopped = false;
    let running = false;
    let cursor = -1;
    let target: ServiceWorker | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refreshState = () => { if (!stopped) setStatus(notificationState(enabled)); };
    const poll = async () => {
      if (running || !enabled || !supported() || Notification.permission !== 'granted') { refreshState(); return; }
      running = true;
      try {
        if (!navigator.onLine) { refreshState(); return; }
        if (!target || target.state === 'redundant') target = await worker();
        for (let pages = 0; pages < 20 && !stopped; pages++) {
          const value = await attention(cursor);
          if (stopped || value.participant !== actor) return;
          for (const row of value.requests) {
            if (stopped) return;
            if (!target || target.state === 'redundant') target = await worker();
            await showAttention(target, actor, row);
          }
          const prior = cursor; cursor = value.cursor;
          if (prior < 0 || cursor === prior) break;
        }
        refreshState();
      } catch { target = null; if (!stopped) setStatus('Notifications not receiving requests. Check permission, identity or connection; use Needs you.'); }
      finally { running = false; }
    };
    const schedule = () => { if (!timer) timer = setTimeout(() => { timer = undefined; void poll(); }, 250); };
    const unsubscribe = onAttentionChanged(schedule);
    const interval = setInterval(() => { void poll(); }, 30000);
    const storage = (event: StorageEvent) => { if (event.key === pref(actor)) changeEnabled(enabledFor(actor)); };
    const replaced = () => { target = null; schedule(); };
    navigator.serviceWorker?.addEventListener('controllerchange', replaced);
    window.addEventListener('online', schedule); window.addEventListener('offline', refreshState);
    window.addEventListener('focus', schedule); window.addEventListener('storage', storage);
    void poll();
    return () => {
      stopped = true; unsubscribe(); clearInterval(interval); clearTimeout(timer);
      window.removeEventListener('online', schedule); window.removeEventListener('offline', refreshState);
      window.removeEventListener('focus', schedule); window.removeEventListener('storage', storage);
      navigator.serviceWorker?.removeEventListener('controllerchange', replaced);
    };
  }, [actor, enabled, changeEnabled]);
  const enable = async () => {
    if (!supported()) return;
    setBusy(true);
    try {
      const permission = await Notification.requestPermission(); // direct user gesture, never mount
      if (permission === 'granted') {
        localStorage.setItem(pref(actor), 'enabled'); changeEnabled(true);
      }
      setStatus(notificationState(permission === 'granted'));
    } catch { setStatus('Could not enable notifications. Browser storage or permission is unavailable.'); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true);
    try {
      const request = `ev-test-${crypto.randomUUID()}`;
      await showAttention(await worker(), actor, { request, url: `/ui/ticket/test?request=${request}` }, true);
      setStatus('Test notification sent. Click it to focus this tab.');
    } catch { setStatus('Could not send test notification. Check browser permission; use Needs you.'); }
    finally { setBusy(false); }
  };
  const disable = useCallback(() => {
    try { localStorage.removeItem(pref(actor)); } catch { /* session disable still works */ }
    changeEnabled(false);
  }, [actor, changeEnabled]);
  const requestStatus = status.startsWith('Request ') || status.startsWith('Could not') || status.startsWith('This request');
  const value: NotificationApi = {
    enabled, status, busy, supported: supported(), pending,
    enable: () => void enable(), disable, test: () => void test(),
    openPending: () => { if (pending) void open(pending.request); },
    dismissPending: () => { setPending(null); setStatus(notificationState(enabled)); },
  };
  return <NotificationCtx.Provider value={value}>
    {children}
    {/* Request-level status and a waiting destination surface globally — a request can arrive with
        the account menu closed, so these do not live in NotificationPanel. */}
    {(requestStatus || pending) ? <div className={styles.toast} aria-live="polite" data-testid="notification-toast">
      {requestStatus ? <p role="status">{status}</p> : null}
      {pending ? <div className={styles.actions}>
        <button onClick={value.openPending}>Open waiting request</button>
        <button onClick={value.dismissPending}>Dismiss destination</button>
      </div> : null}
    </div> : null}
  </NotificationCtx.Provider>;
}
