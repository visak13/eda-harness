import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { subscribeFeed, type FeedEvent } from "./feed";

function sseResponse(chunks: string[]) {
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
  return new HttpResponse(stream, { headers: { "content-type": "text/event-stream" } });
}

async function until(pred: () => boolean, ms = 1000): Promise<void> {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (pred()) return;
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error("condition not met in time");
}

describe("subscribeFeed (SSE fetch-stream parser)", () => {
  it("parses data frames, skips comment frames, and tracks the last seq", async () => {
    server.use(
      http.get("/v1/feed", ({ request }) => {
        // First connect starts at since=-1; assert we asked from the start.
        expect(new URL(request.url).searchParams.get("since")).toBe("-1");
        return sseResponse([
          ": ready\n\n", // comment frame — skipped
          'data: {"seq":1,"kind":"status_changed"}\n\n',
          'data: {"seq":2,"kind":"message_sent","subject_id":"s-1"}\n\n',
        ]);
      }),
    );

    const events: FeedEvent[] = [];
    const stop = subscribeFeed((e) => events.push(e), { backoffMs: 10_000 });
    await until(() => events.length >= 2);
    stop();

    expect(events.map((e) => e.kind)).toEqual(["status_changed", "message_sent"]);
    expect(events[1].seq).toBe(2);
  });

  it("reports malformed JSON via onError without dropping the stream", async () => {
    server.use(
      http.get("/v1/feed", () => sseResponse(["data: not-json\n\n", 'data: {"seq":7}\n\n'])),
    );
    const onError = vi.fn();
    const events: FeedEvent[] = [];
    const stop = subscribeFeed((e) => events.push(e), { onError, backoffMs: 10_000 });
    await until(() => events.length >= 1);
    stop();

    expect(onError).toHaveBeenCalled();
    expect(events[0].seq).toBe(7);
  });

  it("stop() ends the subscription", async () => {
    server.use(http.get("/v1/feed", () => sseResponse(['data: {"seq":1}\n\n'])));
    const events: FeedEvent[] = [];
    const stop = subscribeFeed((e) => events.push(e), { backoffMs: 10_000 });
    await until(() => events.length >= 1);
    stop();
    const count = events.length;
    await new Promise((r) => setTimeout(r, 50));
    expect(events.length).toBe(count); // no further events after stop
  });
});

// Adversary round 2 #9 (2026-09-10): a 200 that closes before any frame, or one that never yields
// a byte, must count as a failure so the /v1/events poll fallback (finding #14) actually engages.
describe("subscribeFeed watchdog (round 2 #9)", () => {
  it("two premature EOFs reach the poll fallback", async () => {
    let polls = 0;
    server.use(
      http.get("/v1/feed", () => sseResponse([])), // 200, EOF before any frame
      http.get("/v1/events", () => {
        polls += 1;
        return HttpResponse.json({ ok: true, value: [{ seq: 41, kind: "polled" }] });
      }),
    );
    const events: FeedEvent[] = [];
    const stop = subscribeFeed((e) => events.push(e), { backoffMs: 5 });
    await until(() => polls >= 1);
    stop();
    expect(events.map((e) => e.kind)).toContain("polled");
  });

  it("a silent open stream is cut by the read watchdog and then polled", async () => {
    let polls = 0;
    server.use(
      http.get("/v1/feed", () => new HttpResponse(new ReadableStream({ start() {} }), { headers: { "content-type": "text/event-stream" } })),
      http.get("/v1/events", () => {
        polls += 1;
        return HttpResponse.json({ ok: true, value: [] });
      }),
    );
    const stop = subscribeFeed(() => {}, { backoffMs: 5, readTimeoutMs: 30 });
    await until(() => polls >= 1, 3000);
    stop();
    expect(polls).toBeGreaterThanOrEqual(1);
  });
});
