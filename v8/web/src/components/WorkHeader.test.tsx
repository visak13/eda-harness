import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { renderRoute } from "../pages/testUtils";
import { WorkHeader } from "./WorkHeader";

// Finding 1 (m-93facfac8a) — the route request deep link must open the source-bound review, never
// answer the gate. 9734d1d dropped the ?request= handling from ContextualWork; it now lives in
// WorkHeader. /epic/<id>?request=<gate-id> (GateForm "Review design at source", an S5 notification)
// matches the design_signoff gate and opens ?doc=<design_ref> so DocDrawer renders the review.
const okJson = (value: unknown) => HttpResponse.json({ ok: true, value });
const contextual = (over: Record<string, unknown> = {}) => ({
  ticket_id: "epic-req", title: "Review source", kind: "epic", status: "designed", owner: "owner", requester: "owner",
  assignee: null, design_ref: "design-req", scope: "Direct source", events: [], blockers: [], unresolved_asks: [], records: [],
  gates: [{ id: "ev-gate", data: { gate: "design_signoff" } }],
  ...over,
});
function reviewMocks() {
  server.use(
    http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual())),
    http.get("/v1/docs/design-req/html", () => okJson({ id: "design-req", title: "The design", version: 3, versions: [3], scope: "epic-req", doc_type: "design", owner_role: "architect", html: "<p>Design body</p>", body_md: "Design body" })),
    http.get("/v1/docs/design-req/context", () => okJson({ ticket_id: "epic-req", source_title: "Review source", source_kind: "epic", design_ref: "design-req", reviewed_version: 3, current_version: 3, gate_event_id: "ev-gate", can_review: true, can_approve: true })),
    http.get("/v1/me/people", () => okJson([])),
  );
}
const header = () => <WorkHeader ticketId="epic-req" kind="epic" title="Review source" status="designed" assignee={null} actions={null} work={<div />} />;

describe("WorkHeader request deep link (finding 1)", () => {
  it("opens the source-bound review when ?request= matches a design_signoff gate", async () => {
    reviewMocks();
    renderRoute("/epic/epic-req?request=ev-gate", "/epic/:id", header());
    // The doc drawer opens (dialog) and DocView renders the review surface, not a bare epic page.
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByText(/Review requested/)).toBeInTheDocument();
  });

  it("never opens a review when ?request= matches no design_signoff gate", async () => {
    reviewMocks();
    renderRoute("/epic/epic-req?request=ev-other", "/epic/:id", header());
    await screen.findByTestId("work-header");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  // consult finding 2: the legacy ?tab= migration (finding 9) must not overwrite the ?doc the request
  // effect sets — a design review reached with a stale ?tab=work still opens the review, not the Work viewer.
  it("keeps the request review open despite a legacy ?tab=work (migration must not steal ?doc)", async () => {
    reviewMocks();
    renderRoute("/epic/epic-req?request=ev-gate&tab=work", "/epic/:id", header());
    expect(await screen.findByText(/Review requested/)).toBeInTheDocument();
    expect(screen.queryByTestId("work-search")).toBeNull();
  });
});
