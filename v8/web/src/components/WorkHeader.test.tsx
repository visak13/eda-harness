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

// S17 c-7a3c3ec439 + item 8 (owner m-8a242679d9): the epic title is not repeated in the header, and
// the title bar collapses Word-style with the state remembered per viewer.
describe("WorkHeader title bar (S17)", () => {
  it("treats a purpose line that only repeats the title as a duplicate", async () => {
    const { sameLine } = await import("./WorkHeader");
    expect(sameLine("Board UI improvements:", "Board UI improvements")).toBe(true);
    expect(sameLine("Board UI improvements", "Board UI improvements - phase 2")).toBe(false);
    expect(sameLine("", "")).toBe(false);
  });

  it("S-UI c-cb386d6be1: a purpose that opens with the title keeps only what follows it", async () => {
    const { withoutTitle } = await import("./WorkHeader");
    expect(withoutTitle("Use the bridge. Goal is Astra", "Use the bridge")).toBe("Goal is Astra");
    expect(withoutTitle("Use the bridge.", "Use the bridge")).toBeNull();
    expect(withoutTitle("Something else", "Use the bridge")).toBe("Something else");
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ gates: [] }))));
    renderRoute("/epic/epic-req", "/epic/:id", <WorkHeader ticketId="epic-req" kind="epic" title="Use the codex bridge"
      purpose="Use the codex bridge. Goal is to use GPT 6 Astra" status="designed" assignee={null} actions={null} work={<div />} />);
    expect(await screen.findByTestId("work-purpose")).toHaveTextContent(/^Goal is to use GPT 6 Astra$/);
  });

  it("shows the epic title only for assistive tech and drops a duplicate purpose", async () => {
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ gates: [] }))));
    renderRoute("/epic/epic-req", "/epic/:id", <WorkHeader ticketId="epic-req" kind="epic" title="Board UI improvements"
      purpose={"Board UI improvements:\n- more"} status="designed" assignee={null} actions={null} work={<div />} />);
    const h1 = await screen.findByRole("heading", { level: 1, name: "Board UI improvements" });
    expect(h1.className).toMatch(/srOnly/);
    expect(screen.queryByTestId("work-purpose")).toBeNull();
  });

  it("collapses to the topline and remembers it for the viewer", async () => {
    localStorage.clear();
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ gates: [] }))));
    const { fireEvent, cleanup } = await import("@testing-library/react");
    renderRoute("/epic/epic-req", "/epic/:id", header());
    const toggle = await screen.findByRole("button", { name: "Collapse title bar" });
    expect(screen.getByTestId("work-header-body")).toBeVisible();
    fireEvent.click(toggle);
    expect(screen.getByTestId("work-header-body")).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Expand title bar" })).toHaveAttribute("aria-expanded", "false");
    expect(Object.keys(localStorage).some((k) => k.endsWith(".epic-header-collapsed") && localStorage.getItem(k) === "1")).toBe(true);
    cleanup();
    renderRoute("/epic/epic-req", "/epic/:id", header());
    expect(await screen.findByRole("button", { name: "Expand title bar" })).toBeInTheDocument();
    expect(screen.getByTestId("work-header-body")).not.toBeVisible();
  });
});
