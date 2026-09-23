import { describe, it, expect, vi } from "vitest";
import { uploadArtifact } from "../api/endpoints";
import { screen, within, waitFor, fireEvent } from "@testing-library/react";
import { HttpResponse } from "msw";
import { useLocation } from "react-router";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { TicketPage } from "./Ticket";
import type { TicketPage as TicketPageData } from "../api/types";

// The upload's multipart body cannot be read back in an msw handler under jsdom (request.text() /
// formData() never resolve), so the ticket the drop uploads against is asserted on the endpoint
// call itself: a pass-through spy on uploadArtifact.
vi.mock("../api/endpoints", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/endpoints")>();
  return { ...orig, uploadArtifact: vi.fn(orig.uploadArtifact) };
});

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
  return renderRoute("/ticket/s-1?as=owner", "/ticket/:id", <TicketPage />);
}

const title = () => screen.findByText("Build the epic page", { selector: "h1" });
// design-a2e5369133: controls live under Actions ▾ (one drawer per item); the description, seat,
// process ladder, criteria and linked documents live behind the header's Work link.
async function openAction(key: string) {
  fireEvent.click(screen.getByTestId("actions-open"));
  fireEvent.click(await screen.findByTestId(`action-${key}`));
  return screen.findByTestId(`action-drawer-${key}`);
}
async function openWork() {
  fireEvent.click(screen.getByTestId("work-work"));
  return screen.findByTestId("ticket-work");
}

describe("TicketPage", () => {
  it("reports total beyond100 and keeps draft/rows on older-page failure and retry", async () => {
    const rows = Array.from({ length: 101 }, (_, i) => ({ id: `m-${i + 1}`, seq: i + 1, by: "owner", to: null, kind: "note", text: `Older row ${i + 1}`, at: "2026-09-02T10:00:00Z", reply_to: null }));
    let fail = true;
    server.use(http.get("/v1/tickets/s-1/thread", () => fail
      ? HttpResponse.json({ ok: false, error: "offline", hint: "try again" }, { status: 503 })
      : okJson({ thread: rows.slice(0, 1), thread_total: 101, thread_before: null })));
    mount(ticketPage({ thread: rows.slice(1), thread_total: 101, thread_before: 2 }));
    expect(await screen.findByTestId("conversation-total")).toHaveTextContent("101 messages");
    const draft = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(draft, { target: { value: "Do not lose me" } });
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    await screen.findByRole("alert");
    expect(screen.getByTestId("thread").children).toHaveLength(100);
    expect(draft).toHaveValue("Do not lose me");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    await screen.findByText("Older row 1");
    expect(screen.getByTestId("thread").children).toHaveLength(101);
    expect(screen.getByRole("textbox", { name: "Message" })).toBe(draft);
    expect(screen.queryByRole("button", { name: "Load older messages" })).toBeNull();
  });
  it("shows the status word, assignee, criteria with verdicts, docs and thread", async () => {
    mount(ticketPage());
    await title();
    expect(screen.getByTestId("work-status")).toHaveTextContent("In review");
    expect(screen.getByTestId("work-assigned")).toHaveTextContent("engineer");
    expect(screen.getByTestId("work-purpose")).toHaveTextContent("Render the epic destination.");
    // thread message on the conversation canvas
    expect(screen.getByTestId("thread")).toHaveTextContent("working on it");
    const work = await openWork();
    expect(within(work).getByTestId("assignee")).toHaveTextContent("engineer.s-99");
    // criteria with verdict words (pass → "Passed"), rendered by the shared CriterionCard
    expect(within(work).getByText("RTL is green")).toBeInTheDocument();
    expect(within(work).getByText("e2e is green")).toBeInTheDocument();
    expect(within(work).getByText("Passed")).toBeInTheDocument();
    // linked doc with its relation label
    expect(within(work).getByText(/designed by/i)).toBeInTheDocument();
  });

  it("crumb links back to the epic", async () => {
    mount(ticketPage());
    await title();
    const crumb = within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "epic-1" });
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
    await title();
    const work = await openWork();
    expect(within(work).getByText("the report proves it")).toBeInTheDocument();
    // ruling mode → the Approve / Needs work buttons are present on the ticket page itself
    expect(within(work).getByTestId("approve")).toBeInTheDocument();
    expect(within(work).getByTestId("needs-work")).toBeInTheDocument();
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
    await title();
    const form = within(await openAction("answer-decision")).getByTestId("gate-form");
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
    expect(screen.queryByTestId("work-purpose")).toBeNull();
    expect(screen.queryByTestId("work-design")).toBeNull(); // design not linked → no Design link
    expect(screen.getByTestId("work-assigned")).toHaveTextContent("Unassigned");
    expect(screen.getByText(/No messages yet/)).toBeInTheDocument();
    const work = await openWork();
    expect(within(work).queryByTestId("description")).toBeNull();
    expect(within(work).getByText(/No acceptance criteria have been added/)).toBeInTheDocument();
    expect(within(work).getByText("No documents linked.")).toBeInTheDocument();
    expect(within(work).getByText("no live shell")).toBeInTheDocument();
    expect(within(work).getByTestId("assignee")).toHaveTextContent("unassigned");
  });

  it.each([
    ["in_review", /Review the evidence, record the checks, then mark it Done/],
    ["in_progress", /Do the work and attach evidence, then move it to In review/],
    ["ready", /Assign or spawn a seat, then start the work/],
    ["done", /Complete — nothing more is needed/],
    ["blocked", /Clear what blocks it, then return it to In progress/],
  ] as const)("process strip next action for status %s (under Work)", async (status, text) => {
    mount(ticketPage({ ticket: { ...ticketPage().ticket, status } }));
    await title();
    const work = await openWork();
    const next = within(work).getByTestId("next-action");
    expect(next).toHaveTextContent(text);
    expect(next).toHaveTextContent("Actions → Change status");
  });

  it("S-UI: Actions → Models… on a story reads and writes its EPIC's per-role tags", async () => {
    mount(ticketPage());
    let patchedEpic = "";
    server.use(
      http.get("/v1/models", () => okJson({ roles: { engineer: ["claude-opus-5-5", "gpt-6-sol"] }, defaults: { engineer: "claude-opus-5-5" } })),
      http.get("/v1/tickets/epic-1", () => okJson({ id: "epic-1", kind: "epic", tags: ["model:engineer=gpt-6-sol"] })),
      http.patch("/v1/tickets/:id", ({ params }) => { patchedEpic = String(params.id); return okJson({ id: params.id, tags: [] }); }),
    );
    await title();
    const drawer = await openAction("models");
    const sel = within(drawer).getByTestId("models-dialog");
    await waitFor(() => expect((within(sel).getByTestId("models-model-engineer") as HTMLSelectElement).value).toBe("gpt-6-sol"));
    fireEvent.change(within(sel).getByTestId("models-effort-engineer"), { target: { value: "low" } });
    fireEvent.click(within(sel).getByTestId("models-save"));
    await waitFor(() => expect(patchedEpic).toBe("epic-1"));
  });

  it("Change status opens the existing StatusControl under Actions", async () => {
    mount(ticketPage());
    await title();
    expect(await within(await openAction("change-status")).findByTestId("status-control")).toBeInTheDocument();
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
    await title();
    const form = within(await openAction("link-doc")).getByTestId("link-doc");
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
    await title();
    const form = within(await openAction("ask-role")).getByTestId("ask-role");
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

// Promise #19: the "Linked documents" card is a drop target that uses the composer's upload path.
describe("TicketPage linked-documents drop target (promise #19)", () => {
  it("shows a drag-over state, uploads the dropped file, FINALISES it onto the ticket, and lists it (finding 11)", async () => {
    vi.mocked(uploadArtifact).mockClear();
    // Finding 11: the drop must not leave the upload staged. The upload returns a staged artifact;
    // the page must then POST /v1/artifacts/finalize with that id + the ticket so it unstages and
    // links `produced`. We record that call and prove the finalised id and ticket are correct.
    let finalized: { path: string; body: Record<string, unknown> } | null = null;
    server.use(
      http.get("/v1/me/people", () => okJson([])), // the page's composer
      // the multipart body is never read back here: request.text()/formData() hang under jsdom
      http.post("/v1/artifacts/upload", () => okJson({ id: "art-drop01", form: "image", staged: true })),
      http.post("/v1/artifacts/finalize", async ({ request }) => {
        finalized = { path: "/v1/artifacts/finalize", body: (await request.json()) as Record<string, unknown> };
        return okJson([{ id: "art-drop01", form: "image", staged: false }], "attached to the ticket");
      }),
    );
    const { qc } = mount(ticketPage());
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    await title();
    const card = within(await openWork()).getByTestId("linked-documents");
    fireEvent.dragOver(card);
    expect(within(card).getByTestId("drop-veil")).toBeInTheDocument();
    fireEvent.dragLeave(card);
    expect(within(card).queryByTestId("drop-veil")).not.toBeInTheDocument();

    fireEvent.drop(card, { dataTransfer: { files: [new File(["x"], "shot.png", { type: "image/png" })] } });
    const row = await within(card).findByTestId("attached-artifact");
    expect(row).toHaveTextContent("art-drop01");
    expect(within(row).getByTestId("artifact-link")).toHaveAttribute("data-artifact", "art-drop01");
    expect(vi.mocked(uploadArtifact).mock.calls[0]?.[1]).toBe("s-1");
    // the finalise really happened: the staged id was attached onto this exact ticket
    await waitFor(() => expect(finalized).not.toBeNull());
    expect(finalized!.body).toMatchObject({ artifact_ids: ["art-drop01"], ticket_id: "s-1" });
    // consult claim 6: the open Files & evidence pane is refreshed from the board's truth, not left
    // to the optimistic row alone — the contextual query for this ticket is invalidated.
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contextual", "s-1"] }));
  });

  it("a refused upload shows the board's reason on the card", async () => {
    server.use(http.post("/v1/artifacts/upload", () => HttpResponse.json({ ok: false, hint: "disallowed type" }, { status: 415 })));
    mount(ticketPage());
    await title();
    const card = within(await openWork()).getByTestId("linked-documents");
    fireEvent.drop(card, { dataTransfer: { files: [new File(["x"], "a.exe", { type: "application/x-msdownload" })] } });
    expect(await within(card).findByRole("alert")).toHaveTextContent(/Upload failed/);
    expect(within(card).queryByTestId("attached-artifact")).not.toBeInTheDocument();
  });

  it("a failed finalise keeps the file off the list and surfaces the reason (finding 11)", async () => {
    server.use(
      http.get("/v1/me/people", () => okJson([])),
      http.post("/v1/artifacts/upload", () => okJson({ id: "art-drop02", form: "image", staged: true })),
      http.post("/v1/artifacts/finalize", () => HttpResponse.json({ ok: false, hint: "ticket is frozen" }, { status: 409 })),
    );
    mount(ticketPage());
    await title();
    const card = within(await openWork()).getByTestId("linked-documents");
    fireEvent.drop(card, { dataTransfer: { files: [new File(["x"], "shot.png", { type: "image/png" })] } });
    expect(await within(card).findByRole("alert")).toHaveTextContent(/Upload failed/);
    expect(within(card).queryByTestId("attached-artifact")).not.toBeInTheDocument();
  });
});
