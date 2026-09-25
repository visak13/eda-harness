// The board feed from the Node extension host (strategyll-1a201146c8 §4). A port of the SPA's
// web/src/live/feed.ts, not new semantics: fetch-stream `/v1/feed?watch=true` with X-Participant +
// X-Token (EventSource cannot send them), `: ready N` / `: resync N` adopt the cursor, a resync
// reconnects at once and asks the caller to reload, a 45 s silent read is a failure, backoff 1 s
// doubling to 30 s with ±20 % jitter, two failures in a row poll `/v1/events` every 5 s for 30 s, a
// 401/403 stops (no retry loop on auth), and dispose() aborts the stream and clears every timer.
// No `vscode` import: fetch, creds and the log sink are injected. Logs never carry headers or text.
import { unsafeBoardUrl, type Creds } from './api';
import type { FeedStatus } from './chatProtocol';
import { cursorMark, sseParser } from './sse';

export type FeedEvent = { seq: number; id?: string; kind?: string; subject_id?: string; data?: Record<string, unknown>; [k: string]: unknown };

export type FeedOptions = {
  baseUrl: string;
  creds: () => Promise<Creds | undefined>;
  fetch?: typeof fetch;
  onEvent: (e: FeedEvent) => void;
  onStatus?: (s: FeedStatus) => void;
  /** the first `: ready` of every connection (the cursor where the server's replay ended) */
  onReady?: (cursor: number) => void;
  /** the server dropped events for this stream (`: resync`): reload what is on screen */
  onResync?: () => void;
  log?: (line: string) => void;
  readTimeoutMs?: number;
  backoffMs?: number;
  maxBackoffMs?: number;
  pollEveryMs?: number;
  pollForMs?: number;
  random?: () => number;
};

class AuthStop extends Error {}

export class FeedClient {
  private stopped = false;
  private started = false;
  private ctrl: AbortController | null = null;
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private wakers = new Set<() => void>();
  private failures = 0;
  since = -1;
  status: FeedStatus = 'connecting';

  constructor(private o: FeedOptions) {}

  /** Start streaming from `since` (-1 = now). Idempotent: a second call opens no second stream. */
  start(since = -1): void {
    if (this.started || this.stopped) return;
    this.started = true;
    this.since = since;
    void this.run();
  }

  dispose(): void {
    this.stopped = true;
    this.ctrl?.abort();
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    for (const w of this.wakers) w();
    this.wakers.clear();
    this.setStatus('stopped');
  }

  /** Pending timers (tests prove dispose() leaves none). */
  get pendingTimers(): number { return this.timers.size; }

  private setStatus(s: FeedStatus) {
    if (this.status === s) return;
    this.status = s;
    this.o.onStatus?.(s);
  }

  private log(line: string) { this.o.log?.(line); }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => {
      if (this.stopped) return resolve();
      const done = () => { clearTimeout(t); this.timers.delete(t); this.wakers.delete(done); resolve(); };
      const t = setTimeout(done, ms);
      this.timers.add(t);
      this.wakers.add(done);
    });
  }

  private async headers(): Promise<Record<string, string>> {
    const refused = unsafeBoardUrl(this.o.baseUrl);
    if (refused) throw new AuthStop(refused);
    const c = await this.o.creds();
    if (!c) throw new AuthStop('not signed in');
    return { 'X-Participant': c.participant, 'X-Token': c.token, Accept: 'text/event-stream' };
  }

  private url(p: string) { return new URL(p, this.o.baseUrl); }

  private deliver(ev: FeedEvent) {
    if (typeof ev.seq === 'number') {
      if (ev.seq <= this.since) return; // a reconnect replay can never deliver twice
      this.since = ev.seq;
    }
    try { this.o.onEvent(ev); } catch (e) { this.log(`feed: handler error ${(e as Error)?.name ?? 'error'}`); }
  }

  /** One connection. Resolves 'resync' | 'eof'; throws on failure. */
  private async connect(): Promise<'resync' | 'eof'> {
    const f = this.o.fetch ?? fetch;
    const ctrl = (this.ctrl = new AbortController());
    const res = await f(this.url(`/v1/feed?since=${this.since}&watch=true`), {
      headers: await this.headers(), signal: ctrl.signal, redirect: 'manual',
    });
    if (res.status === 401 || res.status === 403) throw new AuthStop(`feed ${res.status}`);
    if (!res.ok || !res.body) throw new Error(`feed ${res.status}`);
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let progressed = false;
    let outcome: 'resync' | undefined;
    const parse = sseParser(fr => {
      progressed = true;
      this.failures = 0;
      if (fr.data === undefined) {
        const m = cursorMark(fr.comment);
        if (!m) return; // ping
        this.since = Math.max(this.since, m.cursor);
        if (m.mark === 'ready') { this.setStatus('live'); this.log(`feed connected since=${this.since}`); this.o.onReady?.(this.since); }
        else outcome = 'resync';
        return;
      }
      try { this.deliver(JSON.parse(fr.data) as FeedEvent); } catch { this.log('feed: unparsable frame'); }
    });
    const readTimeout = this.o.readTimeoutMs ?? 45_000;
    while (!this.stopped) {
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      const silent = new Promise<never>((_, reject) => {
        watchdog = setTimeout(() => reject(new Error(`no bytes for ${readTimeout / 1000}s`)), readTimeout);
        this.timers.add(watchdog);
      });
      let chunk: ReadableStreamReadResult<string>;
      try {
        chunk = await Promise.race([reader.read(), silent]);
      } catch (e) {
        ctrl.abort();
        throw e;
      } finally {
        clearTimeout(watchdog); this.timers.delete(watchdog!);
      }
      if (chunk.done) {
        if (!progressed) throw new Error('closed before any frame'); // premature EOF
        return 'eof';
      }
      parse(chunk.value);
      if (outcome === 'resync') { ctrl.abort(); return 'resync'; }
    }
    return 'eof';
  }

  private async pollFor(ms: number): Promise<void> {
    const f = this.o.fetch ?? fetch;
    const until = Date.now() + ms;
    this.setStatus('polling');
    this.log('feed poll fallback');
    while (!this.stopped && Date.now() < until) {
      try {
        const res = await f(this.url(`/v1/events?since=${Math.max(this.since, 0)}&limit=200&watch=true`), {
          headers: await this.headers(), signal: AbortSignal.timeout(10_000), redirect: 'manual',
        });
        if (res.status === 401 || res.status === 403) throw new AuthStop(`events ${res.status}`);
        if (res.ok) {
          const body = (await res.json()) as { value?: FeedEvent[] };
          for (const ev of body.value ?? []) if (!this.stopped) this.deliver(ev);
        }
      } catch (e) {
        if (e instanceof AuthStop) throw e;
        this.log(`feed poll error ${(e as Error)?.name ?? 'error'}`);
      }
      await this.sleep(this.o.pollEveryMs ?? 5_000);
    }
  }

  private async run(): Promise<void> {
    let delay = this.o.backoffMs ?? 1_000;
    const max = this.o.maxBackoffMs ?? 30_000;
    const rnd = this.o.random ?? Math.random;
    while (!this.stopped) {
      try {
        const how = await this.connect();
        if (this.stopped) break;
        if (how === 'resync') {
          this.log(`feed resync since=${this.since}`);
          this.o.onResync?.();
          continue; // not a failure: reconnect at once from the resync cursor
        }
        throw new Error('stream ended');
      } catch (e) {
        if (this.stopped) break;
        if (e instanceof AuthStop) {
          this.log(`feed stopped: ${e.message}`);
          this.setStatus('signed-out');
          this.stopped = true;
          break;
        }
        this.failures += 1;
        if (this.failures === 1) delay = this.o.backoffMs ?? 1_000;
        const wait = Math.round(delay * (0.8 + 0.4 * rnd()));
        this.log(`feed drop ${(e as Error)?.message ?? 'error'}; retry in ${(wait / 1000).toFixed(1)}s`);
        this.setStatus('reconnecting');
        // polling needs a cursor: before the first `: ready` there is none, and `since=0` would replay
        // the board's whole history, so a cold start keeps retrying the stream instead
        if (this.failures >= 2 && this.since >= 0) {
          try { await this.pollFor(this.o.pollForMs ?? 30_000); } catch (pe) {
            if (pe instanceof AuthStop) { this.setStatus('signed-out'); this.stopped = true; break; }
          }
          continue; // then try the stream again
        }
        await this.sleep(wait);
        delay = Math.min(delay * 2, max);
      }
    }
  }
}
