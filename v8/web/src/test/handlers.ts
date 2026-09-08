import { http, HttpResponse } from "msw";

// Mock handlers return the SAME `{ok, value, hint}` envelope the board does, so a test
// passing against the mock passes against the server (strategy_ll §5). Handlers here are
// the shared defaults; a test narrows them with `server.use(...)`.
export const handlers = [
  http.get("/v1/whoami", () =>
    HttpResponse.json({
      ok: true,
      value: { participant: { id: "owner", handle: "owner", role: "owner" }, tickets: [] },
    }),
  ),
  http.get("/v1/me/summary", () =>
    HttpResponse.json({ ok: true, value: { decisions: 0, epics: 0, seats: 0, library: 0 } }),
  ),
  http.get("/v1/epics/summary", () => HttpResponse.json({ ok: true, value: [] })),
  // The live feed: an open stream that never emits (tests that need events override this).
  http.get("/v1/feed", () =>
    new HttpResponse(new ReadableStream(), { headers: { "content-type": "text/event-stream" } }),
  ),
];
