import { describe, it, expect } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { renderRoute } from "../pages/testUtils";
import { WorkHeader } from "./WorkHeader";
import { attentionHandler } from "../test/attentionFixture";

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

describe("WorkHeader open requirements (qa report-138db92cad)", () => {
  it("says them in the Needs attention field, with the list link, instead of 'Nothing open'", async () => {
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ gates: [] }))), http.get("/v1/me/people", () => okJson([])));
    renderRoute("/epic/epic-req", "/epic/:id", <WorkHeader ticketId="epic-req" kind="epic" title="Review source" status="designed" assignee={null} actions={null} work={<div />} openRequirements={1} />);
    const field = await screen.findByTestId("work-attention");
    await waitFor(() => expect(field).toHaveTextContent("1 open requirement"));
    expect(field).not.toHaveTextContent("Nothing open");
    expect(within(field).getByTestId("requirements-chip-open")).toHaveTextContent("Open the list");
    expect(within(field).getByTestId("requirements-chip")).toHaveAttribute("title", expect.stringContaining("cannot finish until the architect links each one"));
  });
});

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

// S13 (s-461403ebd1, ruling m-6cd695046c): the epic's workflow pin is shown from the board's pin table.
describe("WorkHeader workflow pin (S13)", () => {
  it("shows the pinned workflow version when the page passes one", async () => {
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ gates: [] }))));
    renderRoute("/epic/epic-req", "/epic/:id", <WorkHeader ticketId="epic-req" kind="epic" title="Pinned"
      status="designed" assignee={null} workflow="lean@1" actions={null} work={<div />} />);
    expect(await screen.findByTestId("work-workflow")).toHaveTextContent("lean@1");
  });

  it("shows no workflow row on an older board", async () => {
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ gates: [] }))));
    renderRoute("/epic/epic-req", "/epic/:id", header());
    await screen.findByTestId("work-header");
    expect(screen.queryByTestId("work-workflow")).toBeNull();
  });
});

describe("stripMarkdown (t-994970028d)", () => {
  it("drops markdown markers from the plain-text purpose line", async () => {
    const { stripMarkdown } = await import("./WorkHeader");
    expect(stripMarkdown("**Cause:** `Ticket.tsx` renders _raw_ text")).toBe("Cause: Ticket.tsx renders raw text");
    expect(stripMarkdown("- a [link](https://x.y) item")).toBe("a link item");
    expect(stripMarkdown("## Heading")).toBe("Heading");
    expect(stripMarkdown("snake_case_name stays")).toBe("snake_case_name stays");
    expect(stripMarkdown("2 * 3 * 4")).toBe("2 * 3 * 4");
  });
});

// S20 attention trail: each opener holding an item carries its dot (Design, Work), and whatever hides the openers
// (the collapsed title bar) carries their sum, so the trail never breaks at a closed control.
describe("WorkHeader attention openers (S20)", () => {
  it("dots Work, not Design or Files; the collapsed bar keeps the sum", async () => {
    localStorage.clear();
    server.use(attentionHandler(), http.get("/v1/tickets/epic-1/contextual", () => okJson({ ...contextual({ gates: [] }), ticket_id: "epic-1" })));
    const { fireEvent, within } = await import("@testing-library/react");
    renderRoute("/epic/epic-1", "/epic/:id", <WorkHeader ticketId="epic-1" kind="epic" title="Galaxy site" status="designed" assignee={null}
      designRef="design-req" actions={null} work={<div />} />);
    expect(await within(screen.getByTestId("work-work")).findByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    expect(within(screen.getByTestId("work-design")).queryByRole("img")).toBeNull();
    expect(within(screen.getByTestId("work-files")).queryByRole("img")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Collapse title bar" }));
    expect(screen.getByRole("img", { name: "needs your attention: 1" })).toBeVisible();
  });
});

// S12-ui2 (qa m-da89ef8294 item 7): at 390 px the context summary and the Needs attention row both said
// "3 unanswered requests"; open, the summary names the section instead.
describe("WorkHeader attention said once (S12-ui2)", () => {
  it("drops the attention words from the summary while the details are open", async () => {
    reviewMocks();
    const asks = [1, 2, 3].map((i) => ({ id: `m-${i}`, by: "architect.e", text: `ask ${i}`, created_at: "2026-10-01T00:00:00Z", to: "owner" }));
    server.use(http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ unresolved_asks: asks, gates: [] }))));
    renderRoute("/epic/epic-req", "/epic/:id", header());
    const summary = await screen.findByTestId("work-context-summary");
    const details = summary.closest("details") as HTMLDetailsElement;
    if (!details.open) fireEvent.click(screen.getByTestId("work-context-toggle"));
    details.open = true; fireEvent(details, new Event("toggle"));
    expect(await screen.findByTestId("work-attention")).toHaveTextContent("3 unanswered requests");
    expect(screen.getByTestId("work-context-summary")).not.toHaveTextContent("unanswered");
    details.open = false; fireEvent(details, new Event("toggle"));
    expect(await screen.findByText("3 unanswered requests", { selector: "[data-testid=work-context-summary]" })).toBeInTheDocument();
  });
});

describe("WorkHeader owner while loading (qa m-aa62e7bd8e, 390 px)", () => {
  it("shows a skeleton, never \"Unknown\", until the contextual route answers", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    server.use(
      http.get("/v1/tickets/epic-req/contextual", async () => { await gate; return okJson(contextual({ owner: "owner" })); }),
      http.get("/v1/me/people", () => okJson([])),
    );
    renderRoute("/epic/epic-req", "/epic/:id", header());
    const owner = await screen.findByTestId("work-owner");
    expect(within(owner).getByTestId("work-owner-skeleton")).toBeInTheDocument();
    expect(owner).not.toHaveTextContent("Unknown");
    release();
    await waitFor(() => expect(owner).toHaveTextContent("owner"));
    expect(within(owner).queryByTestId("work-owner-skeleton")).toBeNull();
  });

  it("says Unknown only when the answer came back without an owner", async () => {
    server.use(
      http.get("/v1/tickets/epic-req/contextual", () => okJson(contextual({ owner: null }))),
      http.get("/v1/me/people", () => okJson([])),
    );
    renderRoute("/epic/epic-req", "/epic/:id", header());
    await waitFor(() => expect(screen.getByTestId("work-owner")).toHaveTextContent("Unknown"));
  });
});
