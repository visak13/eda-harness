import { authHeaders } from "../auth/identity";

// SEAM (live feed). EventSource can't send X-Participant/X-Token, so the SSE stream is
// read with fetch + a ReadableStream reader. Frames are split on the blank line; each
// `data:` payload is JSON. The board also emits `: ready` / `: ping` comment frames
// (no `data:` line) which are skipped. On any drop we reconnect from the last seq seen.
export interface FeedEvent {
  seq: number;
  id?: string;
  kind?: string;
  subject_id?: string;
  created_at?: string;
  [k: string]: unknown;
}

export interface FeedOptions {
  since?: number;
  onError?: (e: unknown) => void;
  backoffMs?: number;
}

/** Subscribe to /v1/feed. Returns a stop function; call it to end the stream. */
export function subscribeFeed(onEvent: (e: FeedEvent) => void, opts: FeedOptions = {}): () => void {
  let stopped = false;
  let since = opts.since ?? -1;
  let ctrl: AbortController | null = null;
  const backoff = opts.backoffMs ?? 1000;
  let failures = 0; // consecutive stream failures; two in a row → poll /v1/events (finding #14)

  // Polling fallback (adversary finding #14, 2026-09-10): a proxy that buffers SSE, or a board
  // without the stream, must not leave the page silent. After two consecutive stream failures we
  // poll the replay endpoint every 5s for ~30s, deliver what it returns, then try the stream again.
  async function pollFor(ms: number): Promise<void> {
    const until = Date.now() + ms;
    while (!stopped && Date.now() < until) {
      try {
        const res = await fetch(`/v1/events?since=${Math.max(since, 0)}&limit=200`, { headers: authHeaders() });
        if (res.ok) {
          const body = (await res.json()) as { value?: FeedEvent[] };
          for (const ev of body.value ?? []) {
            if (typeof ev.seq === "number" && ev.seq > since) {
              since = ev.seq;
              onEvent(ev);
            }
          }
        }
      } catch (e) {
        opts.onError?.(e);
      }
      await new Promise((r) => setTimeout(r, 5000));
    }
  }

  async function run(): Promise<void> {
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const res = await fetch(`/v1/feed?since=${since}`, {
          headers: authHeaders(),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`feed ${res.status}`);
        failures = 0;
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buf = "";
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break; // server closed — fall through to reconnect
          buf += value;
          let idx: number;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const data = frame
              .split("\n")
              .filter((l) => l.startsWith("data:"))
              .map((l) => l.slice(5).replace(/^ /, ""))
              .join("\n");
            if (!data) continue; // comment frame (: ready / : ping)
            try {
              const ev = JSON.parse(data) as FeedEvent;
              if (typeof ev.seq === "number") since = ev.seq;
              onEvent(ev);
            } catch (e) {
              opts.onError?.(e);
            }
          }
        }
      } catch (e) {
        if (stopped) break;
        failures += 1;
        opts.onError?.(e);
      }
      if (stopped) break;
      if (failures >= 2) {
        await pollFor(30_000);
        continue; // then try the stream again
      }
      await new Promise((r) => setTimeout(r, backoff)); // reconnect from last seq
    }
  }

  void run();
  return () => {
    stopped = true;
    ctrl?.abort();
  };
}
