import { describe, it, expect } from "vitest";
import { screen, within, waitFor, fireEvent } from "@testing-library/react";
import { HttpResponse } from "msw";
import { useLocation } from "react-router";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { TicketPage } from "./Ticket";
import type { TicketPage as TicketPageData } from "../api/types";

function ticketPage(over: Partial<TicketPageData> = {}): TicketPageData {
  return {
    ticket: {
      id: "s-1",
      kind: "story",
      work_type: "feature",
      title: "Build the epic page",
      description: "Render the epic destination.",
      status: "in_review",
      assignee: "engineer.s-99",
      tags: ["web", "epics"],
      design_ref: "design-1",
      epic_id: "epic-1",
    },
    epic_id: "epic-1",
    criteria: [
      { id: "c-1", text: "RTL is green", check: "command", checked_by: "qa", verdict: "pass", evidence_ref: "design-1", evidence_version: 2 },
      { id: "c-2", text: "e2e is green", check: "command", checked_by: "qa", verdict: "pending", evidence_ref: null, evidence_version: null },
    ],
    docs: [{ id: "design-1", doc_type: "design", title: "The design", version: 2, scope: "epic-1", summary: "", full: "", relation: "designed_by" }],
    thread: [{ id: "m1", by: "engineer.s-99", to: null, kind: "note", text: "working on it", at: "2026-09-02T10:00:00Z", reply_to: null }],
    assignee: { id: "engineer.s-99", handle: "engineer.s-99", role: "engineer" },
    waiting_reason: { reason: "awaiting qa", presence: "alive", latest_status: "on it" },
    open_gates: [],
    ...over,
  };
}

function mount(data: TicketPageData) {
  server.use(http.get("/v1/tickets/s-1/page", () => okJson(data)));
  server.use(
    http.get("/v1/tickets/s-1/transitions", () =>
      okJson({ status: data.ticket.status, transitions: [{ to: "done", allowed: true, reason: null }] }),
    ),
  );
  server.use(
    http.get("/v1/pool/capabilities", () =>
      okJson({ resume_parked: true, resume_closed: false, park: true, spawn: false, reason: "no pool in tests" }),
    ),
  );
  server.use(http.post("/v1/messages/resolve", () => okJson({ to: null, wakes: [], plan: [], note: "" })));
  renderRoute("/ticket/s-1?as=owner", "/ticket/:id", <TicketPage />);
}

describe("TicketPage", () => {
  it("shows the status word, assignee, criteria with verdicts, docs and thread", async () => {
    mount(ticketPage());
    await screen.findByText("Build the epic page", { selector: "h1" });
    expect(screen.getByTestId("status-chip")).toHaveTextContent("In review");
    expect(screen.getByTestId("assignee")).toHaveTextContent("engineer.s-99");

    // criteria with verdict words (pass → "Passed"), rendered by the shared CriterionCard
    expect(screen.getByText("RTL is green")).toBeInTheDocument();
    expect(screen.getByText("e2e is green")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();

    // linked doc with its relation label
    expect(screen.getByText(/designed by/i)).toBeInTheDocument();
    // thread message
    expect(screen.getByTestId("thread")).toHaveTextContent("working on it");
  });

  it("crumb links back to the epic", async () => {
    mount(ticketPage());
    const crumb = await screen.findByRole("link", { name: /Epic epic-1/ });
    expect(crumb).toHaveAttribute("href", "/epic/epic-1");
  });

  it("offers the one-click verdict pane on a pending criterion that already has evidence (§16)", async () => {
    mount(
      ticketPage({
        criteria: [
          { id: "c-9", text: "the report proves it", check: "look", checked_by: "owner", verdict: "pending", evidence_ref: "report-1", evidence_version: 3 },
        ],
      }),
    );
    await screen.findByText("the report proves it");
    // ruling mode → the Approve / Needs work buttons are present on the ticket page itself
    expect(screen.getByTestId("approve")).toBeInTheDocument();
    expect(screen.getByTestId("needs-work")).toBeInTheDocument();
  });

  it("closes the OTHER half of the gate loop: an open gate on the ticket can be answered from the page", async () => {
    let answered: { path: string; body: Record<string, unknown> } | null = null;
    mount(
      ticketPage({
        open_gates: [
          { ticket_id: "s-1", gate: "demo", by: "architect.epic-1", note: "does it work?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" },
        ],
      }),
    );
    server.use(
      http.post("/v1/gates/s-1/demo/answer", async ({ request }) => {
        answered = { path: "/v1/gates/s-1/demo/answer", body: (await request.json()) as Record<string, unknown> };
        return okJson({ ok: true });
      }),
    );
    const form = await screen.findByTestId("gate-form");
    fireEvent.change(within(form).getByTestId("gate-answer"), { target: { value: "looks good, shipping" } });
    fireEvent.click(within(form).getByTestId("gate-submit"));
    await waitFor(() => expect(answered).not.toBeNull());
    expect(answered!.body).toMatchObject({ answer: "looks good, shipping" });
  });

  it("renders the empty-state variants: no description, no tags, no criteria, no docs, no thread", async () => {
    mount(
      ticketPage({
        ticket: {
          id: "s-1",
          kind: "story",
          work_type: "feature",
          title: "Bare ticket",
          description: "",
          status: "ready",
          assignee: null,
          tags: [],
          design_ref: null,
          epic_id: "epic-1",
        },
        criteria: [],
        docs: [],
        thread: [],
        assignee: { id: null, handle: null, role: null },
        waiting_reason: { reason: "", presence: null, latest_status: null },
      }),
    );
    await screen.findByText("Bare ticket", { selector: "h1" });
    expect(screen.getByText("No acceptance criteria have been added.")).toBeInTheDocument();
    expect(screen.getByText("No documents linked.")).toBeInTheDocument();
    expect(screen.getByText("No messages on this ticket yet.")).toBeInTheDocument();
    // no live shell state, unassigned seat label, design not linked, waiting "—"
    expect(screen.getByText("no live shell")).toBeInTheDocument();
    expect(screen.getByTestId("assignee")).toHaveTextContent("unassigned");
    expect(screen.getByText("Not linked")).toBeInTheDocument();
  });

  it.each([
    ["in_review", "Review the evidence, then change the status →"],
    ["in_progress", "Attach evidence, then move it to In review →"],
    ["ready", "Assign or spawn a seat, then start it →"],
    ["done", "Complete — see the status below."],
    ["blocked", "Change the status →"],
  ] as const)("process strip next action for status %s", async (status, text) => {
    mount(ticketPage({ ticket: { ...ticketPage().ticket, status } }));
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("toggles the conversation order", async () => {
    mount(ticketPage());
    await screen.findByText("Build the epic page", { selector: "h1" });
    const toggle = screen.getByTestId("order-toggle");
    expect(toggle).toHaveTextContent("Newest first");
    fireEvent.click(toggle);
    expect(toggle).toHaveTextContent("Oldest first");
  });

  it("links a document to the ticket via the Link & ask control", async () => {
    let linked: Record<string, unknown> | null = null;
    mount(ticketPage());
    server.use(
      http.post("/v1/links", async ({ request }) => {
        linked = (await request.json()) as Record<string, unknown>;
        return okJson({ ok: true });
      }),
    );
    await screen.findByText("Build the epic page", { selector: "h1" });
    const form = screen.getByTestId("link-doc");
    fireEvent.change(within(form).getByPlaceholderText("document id"), { target: { value: "design-9" } });
    fireEvent.change(within(form).getByLabelText("Relation"), { target: { value: "supersedes" } });
    fireEvent.submit(form);
    await waitFor(() => expect(linked).not.toBeNull());
    expect(linked!).toMatchObject({ from_id: "s-1", to_id: "design-9", relation: "supersedes" });
    expect(await screen.findByTestId("link-doc-ok")).toBeInTheDocument();
  });

  it("asks a role a question via the Link & ask control", async () => {
    let asked: Record<string, unknown> | null = null;
    mount(ticketPage());
    server.use(
      http.post("/v1/messages", async ({ request }) => {
        asked = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "m9", unresolved_mentions: [] }, "asked");
      }),
    );
    await screen.findByText("Build the epic page", { selector: "h1" });
    const form = screen.getByTestId("ask-role");
    fireEvent.change(within(form).getByLabelText("Question"), { target: { value: "what is the scope?" } });
    fireEvent.submit(form);
    await waitFor(() => expect(asked).not.toBeNull());
    expect(asked!).toMatchObject({ ticket_id: "s-1", kind: "question", text: "what is the scope?" });
    expect(await screen.findByTestId("ask-role-ok")).toBeInTheDocument();
  });

  it("shows the loading state, then an error banner when the page fails", async () => {
    server.use(http.get("/v1/tickets/s-1/page", () => new HttpResponse(null, { status: 500 })));
    renderRoute("/ticket/s-1?as=owner", "/ticket/:id", <TicketPage />);
    expect(screen.getByText("Loading ticket…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load s-1/);
  });
});

// Promise #15 (design §4.2 "Expand"): the same composer opens in the right Drawer; the draft
// moves with it and back; `?compose=1` carries the state and reopens the expanded composer.
function LocationProbe(): React.JSX.Element {
  const { search } = useLocation();
  return <span data-testid="location-search">{search}</span>;
}

function mountWithProbe(path: string, data: TicketPageData) {
  server.use(http.get("/v1/tickets/s-1/page", () => okJson(data)));
  server.use(
    http.get("/v1/tickets/s-1/transitions", () =>
      okJson({ status: data.ticket.status, transitions: [{ to: "done", allowed: true, reason: null }] }),
    ),
  );
  server.use(
    http.get("/v1/pool/capabilities", () =>
      okJson({ resume_parked: true, resume_closed: false, park: true, spawn: false, reason: "no pool in tests" }),
    ),
  );
  server.use(http.post("/v1/messages/resolve", () => okJson({ to: null, wakes: [], plan: [], note: "" })));
  renderRoute(
    path,
    "/ticket/:id",
    <>
      <TicketPage />
      <LocationProbe />
    </>,
  );
}

describe("TicketPage composer Expand (§4.2, promise #15)", () => {
  it("Expand moves the draft into the drawer and sets ?compose=1; Collapse brings it back", async () => {
    mountWithProbe("/ticket/s-1?as=owner", ticketPage());
    await screen.findByText("Build the epic page", { selector: "h1" });
    const inline = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    fireEvent.change(inline, { target: { value: "half-written thought" } });
    fireEvent.click(screen.getByTestId("composer-expand"));

    const drawer = await screen.findByTestId("drawer-panel");
    expect(within(drawer).getByTestId("composer-text")).toHaveValue("half-written thought");
    expect(screen.getByTestId("location-search").textContent).toContain("compose=1");
    // the inline slot no longer holds a composer — only the note pointing at the drawer
    expect(screen.getByTestId("composer-expanded-note")).toBeInTheDocument();
    expect(screen.getAllByTestId("composer-text")).toHaveLength(1);

    // keep typing in the drawer, then collapse: the draft comes back inline
    fireEvent.change(within(drawer).getByTestId("composer-text"), { target: { value: "half-written thought, finished" } });
    fireEvent.click(within(drawer).getByTestId("composer-expand")); // reads "Collapse"
    await waitFor(() => expect(screen.queryByTestId("drawer-panel")).not.toBeInTheDocument());
    expect(screen.getByTestId("composer-text")).toHaveValue("half-written thought, finished");
    expect(screen.getByTestId("location-search").textContent).not.toContain("compose=1");
  });

  it("closing the drawer (Esc / ✕) also returns the draft to the page", async () => {
    mountWithProbe("/ticket/s-1?as=owner", ticketPage());
    await screen.findByText("Build the epic page", { selector: "h1" });
    fireEvent.change(screen.getByTestId("composer-text"), { target: { value: "draft" } });
    fireEvent.click(screen.getByTestId("composer-expand"));
    const drawer = await screen.findByTestId("drawer-panel");
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByTestId("drawer-panel")).not.toBeInTheDocument());
    expect(screen.getByTestId("composer-text")).toHaveValue("draft");
  });

  it("loading the page with ?compose=1 reopens the expanded composer", async () => {
    mountWithProbe("/ticket/s-1?as=owner&compose=1", ticketPage());
    await screen.findByText("Build the epic page", { selector: "h1" });
    const drawer = await screen.findByTestId("drawer-panel");
    expect(within(drawer).getByTestId("composer-text")).toBeInTheDocument();
    expect(within(drawer).getByTestId("composer-expand")).toHaveTextContent("Collapse");
    expect(screen.getByTestId("composer-expanded-note")).toBeInTheDocument();
  });
});
