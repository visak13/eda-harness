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

  async function run(): Promise<void> {
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const res = await fetch(`/v1/feed?since=${since}`, {
          headers: authHeaders(),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`feed ${res.status}`);
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
        opts.onError?.(e);
      }
      if (stopped) break;
      await new Promise((r) => setTimeout(r, backoff)); // reconnect from last seq
    }
  }

  void run();
  return () => {
    stopped = true;
    ctrl?.abort();
  };
}
