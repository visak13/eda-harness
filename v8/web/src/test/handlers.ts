import { http, HttpResponse } from "msw";

// Mock handlers return the SAME `{ok, value, hint}` envelope the board does, so a test
// passing against the mock passes against the server (strategy_ll §5). Handlers here are
// the shared defaults; a test narrows them with `server.use(...)`.
export const handlers = [
  http.get("/v1/docs/:id/sources", () => HttpResponse.json({ ok: true, value: [{ id: "epic-1", title: "Source work" }] })),
  http.get("/v1/artifacts/:id", ({ params }) => HttpResponse.json({ ok: true, value: { id: params.id, form: "repo_ref", uri: "git:example", note: "Reference", created_by: "owner", created_at: "2026-09-18" } })),
  http.get("/v1/tickets/:id/contextual", ({ params, request }) => HttpResponse.json({ ok: true, value: {
    ticket_id: params.id, title: "Source work", kind: String(params.id).startsWith("epic-") ? "epic" : "story", status: "in_progress",
    owner: "owner", requester: "owner", assignee: null, design_ref: null, gates: [], records: [], events: [],
    category: new URL(request.url).searchParams.get("category") ?? "all", scope: "Direct source only", truncated: false,
  } })),
  http.get("/v1/docs/:id/context", ({ params, request }) => { const p = new URL(request.url).searchParams; return HttpResponse.json({ ok: true, value: {
    ticket_id: p.get("source"), source_title: "Source work", source_kind: "epic", design_ref: params.id,
    reviewed_version: Number(p.get("version")), current_version: 2, gate_event_id: null, can_approve: false, can_review: true,
  } }); }),
  http.get("/v1/avatars/:id", ({ request }) => {
    if (!request.headers.get("X-Participant")) return new HttpResponse(null, { status: 401 });
    return new HttpResponse('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" />', { headers: { "content-type": "image/svg+xml" } });
  }),
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
