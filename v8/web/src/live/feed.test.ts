import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { subscribeFeed, type FeedEvent } from "./feed";

function sseResponse(chunks: string[]): HttpResponse {
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
