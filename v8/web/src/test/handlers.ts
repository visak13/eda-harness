import { http, HttpResponse } from "msw";

// Mock handlers return the SAME `{ok, value, hint}` envelope the board does, so a test
// passing against the mock passes against the server (strategy_ll §5). Handlers here are
// the shared defaults; a test narrows them with `server.use(...)`.
export const MODEL_CATALOG = {
  roles: {
    architect: ["claude-fable-5-1", "gpt-6-astra"], engineer: ["claude-opus-5-5", "gpt-6-sol"],
    qa: ["claude-fable-5-1", "gpt-6-astra"], adversary: ["gpt-6-astra"], sme: ["claude-opus-5-5", "gpt-6-sol"],
  },
  defaults: { architect: "claude-fable-5-1", engineer: "claude-opus-5-5", qa: "claude-fable-5-1", adversary: "gpt-6-astra", sme: "claude-opus-5-5" },
};

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
  // S-ROLES: the per-role model catalog (models.json role_models)
  http.get("/v1/models", () => HttpResponse.json({ ok: true, value: MODEL_CATALOG, hint: "" })),
  // The live feed: an open stream that never emits (tests that need events override this).
  http.get("/v1/feed", () =>
    new HttpResponse(new ReadableStream(), { headers: { "content-type": "text/event-stream" } }),
  ),
];

// S-LIBRARY: a knowledge view with one active linked strategy, one proposal for it, and a lesson
// (GET /v1/knowledge shape — library.knowledge_view).
export const KNOWLEDGE_VIEW = {
  docs: [
    {
      id: "strategyhl-2", doc_type: "strategy_hl", title: "py craft v2", version: 1, scope: "global", tags: ["python"],
      status: "proposed", proposes: "strategyhl-1", summary: "- rule one", full: "doc_read(id)", created_by: "engineer.s-1",
      created_at: "2026-09-23T10:00:00Z", source: { participant: "engineer.s-1", ticket: "s-1" }, source_url: null,
      resolution: null, linked: [],
    },
    {
      id: "strategyhl-1", doc_type: "strategy_hl", title: "py craft", version: 3, scope: "global", tags: ["python", "testing"],
      status: "active", summary: "- rule one", full: "doc_read(id)", created_by: "owner", created_at: "2026-09-20T10:00:00Z",
      source: null, source_url: null, resolution: null,
      linked: [{ link_id: "lk-1", ticket_id: "epic-1", kind: "epic", title: "The epic", relation: "uses_strategy" }],
    },
    {
      id: "domain-1", doc_type: "domain", title: "board domain", version: 1, scope: "global", tags: ["board"],
      status: "retired", summary: "", full: "doc_read(id)", created_by: "owner", created_at: "2026-09-19T10:00:00Z",
      source: null, source_url: null, resolution: "rejected", linked: [],
    },
  ],
  lessons: [{ id: "les-1", domain: "operations", topic: "restart", text: "restart the board by pid", status: "live",
    created_by: "owner", created_at: "2026-09-18T10:00:00Z" }],
  tags: ["board", "python", "testing"],
  epics: [{ id: "epic-1", title: "The epic", status: "in_progress" }, { id: "epic-2", title: "Other epic", status: "ready" }],
};
export const KNOWLEDGE_DIFF = {
  id: "strategyhl-2", status: "proposed", base_id: "strategyhl-1", base_version: 3, title_changed: true,
  base_title: "py craft", title: "py craft v2",
  diff: "--- strategyhl-1 v3 (active)\n+++ strategyhl-2 v1 (proposed)\n@@ -1 +1,2 @@\n- rule one\n+- rule two\n",
};
