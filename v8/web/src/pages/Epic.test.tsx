import { describe, it, expect } from "vitest";
import { screen, fireEvent, within, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { EpicPage } from "./Epic";
import type { EpicPage as EpicPageData, EpicTreeNode, MessageView } from "../api/types";

// The epic page per design-a2e5369133 / revision3-clean-epic.png: WorkHeader (breadcrumb + Actions ▾,
// title, purpose, STATUS/OWNER/ASSIGNED/NEEDS ATTENTION, links row) over the conversation. Every
// control lives under Actions ▾ (a drawer per item); stories/kanban/criteria/process live behind Work.

function node(over: Partial<EpicTreeNode> = {}): EpicTreeNode {
  return { id: "s-1", kind: "story", work_type: "feature", title: "First story", status: "in_progress", assignee: "engineer.s-99", criteria: "2/4", gates: [], blocked_by: [], children: [], ...over };
}

function page(over: Partial<EpicPageData> = {}, thread: MessageView[] = []): EpicPageData {
  const epic: EpicTreeNode = { id: "epic-1", kind: "epic", work_type: "feature", title: "Upgrade the board UI", status: "in_progress", assignee: null, criteria: "0/0", gates: [], blocked_by: [], children: [node()] };
  return {
    board: { epic, counts: { in_progress: 1 }, ready: [], in_review: [], open_gates: [], words: epic.title },
    words: "Upgrade the board UI so that a first-time human can read it without a shell",
    title: epic.title, counts: { in_progress: 1 }, thread, docs: [], open_gates: [], answerable_gates: [], criteria: [], ...over,
  };
}

function mount(data: EpicPageData, summary: Record<string, unknown>[] = [], caps: Record<string, unknown> = { resume_parked: true, resume_closed: false, park: true, spawn: true }) {
  server.use(http.get("/v1/epics/epic-1/page", () => okJson(data)));
  server.use(http.get("/v1/tickets/epic-1/contextual", () => okJson({
    ticket_id: "epic-1", title: data.title, kind: "epic", status: data.board.epic.status, owner: "owner", requester: "owner", assignee: null,
    design_ref: null, gates: [], scope: "epic-1", events: [], blockers: [], unresolved_asks: [],
    records: data.docs.map((record) => ({ type: "doc", group: "Other", relation: record.doc_type.replaceAll("_", " "), record })),
  })));
  server.use(http.get("/v1/epics/summary", () => okJson(summary)));
  server.use(http.get("/v1/tickets/epic-1/transitions", () => okJson({ status: data.board.epic.status, transitions: [{ to: "done", allowed: true, reason: null }] })));
  server.use(http.get("/v1/pool/capabilities", () => okJson(caps)));
  server.use(http.get("/v1/me/people", () => okJson([])), http.post("/v1/messages/resolve", () => okJson({ to: null, wakes: [], plan: [], note: "" })));
  renderRoute("/epic/epic-1", "/epic/:id", <EpicPage />);
}

const title = () => screen.findByText("Upgrade the board UI", { selector: "h1" });
async function openAction(key: string) {
  fireEvent.click(screen.getByTestId("actions-open"));
  fireEvent.click(await screen.findByTestId(`action-${key}`));
  return screen.findByTestId(`action-drawer-${key}`);
}
async function openWork() {
  fireEvent.click(screen.getByTestId("work-work"));
  return screen.findByTestId("epic-work");
}

describe("EpicPage", () => {
  it("shows the full >100 total and loads every older page without replacing the draft", async () => {
    const messages: MessageView[] = Array.from({ length: 235 }, (_, i) => ({ id: `m-${i + 1}`, seq: i + 1, by: "owner", to: null, kind: "note", text: `History row ${i + 1}`, at: "2026-09-01T10:00:00Z", reply_to: null }));
    const cursors: number[] = [];
    server.use(http.get("/v1/tickets/epic-1/thread", ({ request }) => {
      expect(request.headers.get("X-Participant")).toBeTruthy();
      const before = Number(new URL(request.url).searchParams.get("before")); cursors.push(before);
      const older = messages.filter((m) => m.seq! < before);
      const rows = older.slice(-100);
      return okJson({ thread: rows, thread_total: 235, thread_before: older.length > 100 ? rows[0].seq : null });
    }));
    mount(page({ thread_total: 235, thread_before: 136 }, messages.slice(-100)));
    expect(await screen.findByTestId("conversation-total")).toHaveTextContent("235 messages");
    const draft = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(draft, { target: { value: "Keep my unsent draft" } });
    const list = screen.getByTestId("thread"); list.scrollTop = 42;
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    await screen.findByText("History row 36");
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    await screen.findByText("History row 1");
    expect(cursors).toEqual([136, 36]);
    expect(list.children).toHaveLength(235);
    expect(list.firstElementChild).toHaveAttribute("id", "m-235");
    expect(list.scrollTop).toBe(42);
    fireEvent.click(screen.getByTestId("order-toggle"));
    expect(list.firstElementChild).toHaveAttribute("id", "m-1");
    expect(screen.getByRole("textbox", { name: "Message" })).toBe(draft);
    expect(draft).toHaveValue("Keep my unsent draft");
    expect(screen.queryByRole("button", { name: "Load older messages" })).toBeNull();
  });

  it("header: title, purpose from the owner's words, ONE status badge, owner and assigned from the board", async () => {
    mount(page());
    await title();
    expect(screen.getByTestId("work-purpose")).toHaveTextContent("without a shell");
    const status = screen.getByTestId("work-status");
    expect(status).toHaveTextContent("In progress");
    expect(screen.getByTestId("work-metadata").querySelectorAll('[data-testid="status-chip"]')).toHaveLength(1);
    expect(await within(screen.getByTestId("work-owner")).findByText("owner")).toBeInTheDocument();
    expect(screen.getByTestId("work-attention")).toHaveTextContent("Nothing open");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    // no design linked → no Design link; Files / History / Work always present
    expect(screen.queryByTestId("work-design")).toBeNull();
    expect(screen.getByTestId("work-files")).toBeInTheDocument();
  });

  it("the owner's words sit verbatim under Actions → Original request", async () => {
    mount(page());
    await title();
    const drawer = await openAction("original-request");
    expect(within(drawer).getByTestId("owner-words")).toHaveTextContent(/Owner.s words · original request/i);
    expect(within(drawer).getByTestId("owner-words-text")).toHaveTextContent("without a shell");
  });

  it("Work shows the latest steer only when the thread carries one", async () => {
    mount(page({}, [{ id: "m1", by: "owner", to: null, kind: "note", text: "hi", at: "2026-09-01T10:00:00Z", reply_to: null }]));
    await title();
    await openWork();
    expect(screen.queryByTestId("directive")).not.toBeInTheDocument();
  });

  it("Work shows the latest steer text when a steer is present", async () => {
    mount(page({}, [{ id: "m2", by: "owner", to: null, kind: "steer", text: "concepts first, then build", at: "2026-09-02T10:00:00Z", reply_to: null }]));
    await title();
    const work = await openWork();
    expect(within(work).getByTestId("directive")).toHaveTextContent("concepts first, then build");
  });

  it("Work carries the filter fold (status/work-type/assignee), the search and the kanban", async () => {
    mount(page());
    await title();
    const work = await openWork();
    expect(within(work).getByTestId("work-search")).toBeInTheDocument();
    expect(within(work).getByTestId("work-filters")).toBeInTheDocument();
    expect(within(work).getByLabelText("Status")).toBeInTheDocument();
    expect(within(work).getByLabelText("Work type")).toBeInTheDocument();
    expect(within(work).getByLabelText("Assignee contains")).toBeInTheDocument();
    expect(within(work).getByTestId("kanban")).toBeInTheDocument();
    expect(within(work).getByText("2 of 4 criteria passed", { exact: false })).toBeInTheDocument();
    expect(within(work).getByTestId("process-strip")).toBeInTheDocument();
    expect(within(work).getByTestId("stage-current")).toHaveTextContent("In progress");
  });

  it("an epic with zero stories renders one sentence and no kanban columns", async () => {
    const data = page(); data.board.epic.children = [];
    mount(data);
    await title();
    const work = await openWork();
    expect(within(work).getByText("This epic has no stories yet.")).toBeInTheDocument();
    expect(within(work).getByText(/No stories yet — this epic is still being shaped/)).toBeInTheDocument();
    expect(within(work).queryByTestId("kanban")).not.toBeInTheDocument();
  });

  it("lists the epic's OWN acceptance criteria with a verdict pane, not just a count (§16)", async () => {
    mount(page({ criteria: [{ id: "c-e1", text: "the epic is accepted", check: "look", checked_by: "owner", verdict: "pending", evidence_ref: "report-1", evidence_version: 2 }] }));
    await title();
    const work = await openWork();
    expect(within(work).getByText("the epic is accepted")).toBeInTheDocument();
    expect(within(work).getByTestId("approve")).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("drawer-panel")).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByTestId("epic-work")).toBeNull());
    expect(await openAction("add-criterion")).toBeInTheDocument();
  });

  it("Files & evidence lists linked docs from the board's records; empty epic shows the designed empty state", async () => {
    mount(page({ docs: [{ id: "design-1", doc_type: "design_note", title: "The design", version: 1, scope: "epic-1", summary: "", full: "" }] }));
    await title();
    fireEvent.click(screen.getByTestId("work-files"));
    expect(await screen.findByRole("button", { name: "The design · v1" })).toBeInTheDocument();
    expect(screen.getByText(/design note/)).toBeInTheDocument();
  });

  it("Files & evidence shows the empty state when nothing is linked", async () => {
    mount(page({ docs: [] }));
    await title();
    fireEvent.click(screen.getByTestId("work-files"));
    expect(await screen.findByTestId("files-empty")).toHaveTextContent("Nothing attached yet");
  });

  it("Design link opens the design in the reader and the pulse counts stories", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => okJson({ id: "design-1", title: "The design", version: 1, versions: [1], scope: "epic-1", doc_type: "design", owner_role: "architect", html: "<p>Design body</p>", body_md: "Design body" })));
    const data = page({ docs: [{ id: "design-1", doc_type: "design", title: "The design", version: 1, scope: "epic-1", summary: "", full: "" }] });
    data.board.epic.children = [node({ id: "s-1" }), node({ id: "s-2", title: "Second story" })];
    mount(data);
    await title();
    const work = await openWork();
    expect(within(work).getByText(/2 stories ·/)).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("drawer-panel")).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByTestId("epic-work")).toBeNull());
    fireEvent.click(screen.getByTestId("work-design"));
    await screen.findByText("Design body");
  });

  it("conversation renders messages, toggles order, and shows the empty state", async () => {
    mount(page({}, [
      { id: "m1", by: "engineer.s-99", to: null, kind: "note", text: "first message", at: "2026-09-01T10:00:00Z", reply_to: null },
      { id: "m2", by: "owner", to: null, kind: "note", text: "second message", at: "2026-09-02T10:00:00Z", reply_to: null },
    ]));
    await title();
    const toggle = await screen.findByTestId("order-toggle");
    expect(toggle).toHaveTextContent("Newest first");
    fireEvent.click(toggle);
    expect(toggle).toHaveTextContent("Oldest first");
    expect(screen.getByTestId("thread")).toHaveTextContent("first message");
  });

  it("conversation shows the empty state when there are no messages", async () => {
    mount(page({}, []));
    await title();
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument();
  });

  it("steering is a Type in the composer, not a button (owner: 'steer just focuses the message box')", async () => {
    mount(page({}, []));
    await title();
    expect(screen.queryByRole("button", { name: "Steer this epic" })).toBeNull();
    const kinds = screen.getByTestId("kind-picker") as HTMLSelectElement;
    expect([...kinds.options].map((o) => o.value)).toContain("steer");
    fireEvent.change(kinds, { target: { value: "steer" } });
    expect(kinds.value).toBe("steer");
  });

  it("Work filters by status, work type and assignee; a no-match filter shows the empty sentence", async () => {
    const data = page();
    data.board.epic.children = [
      node({ id: "s-1", title: "Alpha", status: "in_progress", work_type: "feature", assignee: "engineer.s-1" }),
      node({ id: "s-2", title: "Bravo", status: "done", work_type: "bug", assignee: "reviewer.s-2" }),
    ];
    mount(data);
    await title();
    const work = await openWork();
    expect(within(work).queryAllByText("Alpha").length).toBeGreaterThan(0);
    fireEvent.change(within(work).getByLabelText("Status"), { target: { value: "done" } });
    expect(within(work).queryAllByText("Alpha")).toHaveLength(0);
    expect(within(work).queryAllByText("Bravo").length).toBeGreaterThan(0);
    fireEvent.change(within(work).getByLabelText("Status"), { target: { value: "" } });
    fireEvent.change(within(work).getByLabelText("Work type"), { target: { value: "feature" } });
    expect(within(work).queryAllByText("Bravo")).toHaveLength(0);
    fireEvent.change(within(work).getByLabelText("Work type"), { target: { value: "" } });
    fireEvent.change(within(work).getByLabelText("Assignee contains"), { target: { value: "reviewer" } });
    expect(within(work).queryAllByText("Alpha")).toHaveLength(0);
    fireEvent.change(within(work).getByLabelText("Assignee contains"), { target: { value: "nobody" } });
    expect(within(work).getByText("No tickets match these filters.")).toBeInTheDocument();
  });

  it("Work search narrows rows by title / id at once and resolves ids via the tickets table", async () => {
    server.use(http.get("/v1/tickets/table", () => okJson({ rows: [{ id: "s-1", epic_id: "epic-1", title: "Alpha", kind: "story", work_type: "feature", status: "in_progress", assignee: null, tags: [], criteria: { passed: 0, failed: 0, pending: 0, total: 0 }, blocked_by: [] }], count: 1 })));
    const data = page();
    data.board.epic.children = [node({ id: "s-1", title: "Alpha" }), node({ id: "s-2", title: "Bravo" })];
    mount(data);
    await title();
    const work = await openWork();
    expect(within(work).getAllByTestId("work-row")).toHaveLength(2);
    const fold = within(work).getByTestId("work-filters-fold");
    expect(fold.tagName).toBe("DETAILS");
    expect(fold).not.toHaveAttribute("open");
    fireEvent.change(within(work).getByTestId("work-search"), { target: { value: "s-2" } });
    expect(within(work).getAllByTestId("work-row")[0]).toHaveTextContent("Bravo");
    fireEvent.change(within(work).getByTestId("work-search"), { target: { value: "alph" } });
    await waitFor(() => expect(within(work).getAllByTestId("work-row")).toHaveLength(1));
    expect(within(work).getAllByTestId("work-row")[0]).toHaveTextContent("s-1");
    fireEvent.change(within(work).getByTestId("work-search"), { target: { value: "zzz" } });
    expect(within(work).getByText("No tickets match these filters.")).toBeInTheDocument();
  });

  it("shows the loading state, then an error banner when the page fails", async () => {
    server.use(http.get("/v1/epics/epic-1/page", () => new HttpResponse(null, { status: 500 })));
    server.use(http.get("/v1/epics/summary", () => okJson([])));
    renderRoute("/epic/epic-1", "/epic/:id", <EpicPage />);
    expect(screen.getByText("Loading epic…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load epic-1/);
  });

  it("answers the epic's own open gate from Actions → Answer a decision (§16)", async () => {
    let answered: Record<string, unknown> | null = null;
    mount(page({ answerable_gates: [{ ticket_id: "epic-1", gate: "acceptance", by: "owner", note: "accept the epic?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" }] }));
    server.use(http.post("/v1/gates/epic-1/acceptance/answer", async ({ request }) => { answered = (await request.json()) as Record<string, unknown>; return okJson({ ok: true }); }));
    await title();
    const drawer = await openAction("answer-decision");
    const form = within(drawer).getByTestId("gate-form");
    fireEvent.change(within(form).getByTestId("gate-answer"), { target: { value: "accepted" } });
    fireEvent.click(within(form).getByTestId("gate-submit"));
    await waitFor(() => expect(answered).not.toBeNull());
    expect(answered!).toMatchObject({ answer: "accepted" });
  });

  it("Ask a role posts a question addressed to the chosen role on the epic thread (promise #17)", async () => {
    let body: Record<string, unknown> | null = null;
    mount(page());
    server.use(http.post("/v1/messages", async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return okJson({ id: "m-9", unresolved_mentions: [] }, "delivered to reviewer.epic-1 (the epic's reviewer)"); }));
    await title();
    const drawer = await openAction("ask-role");
    fireEvent.click(within(drawer).getByTestId("ask-role-toggle"));
    expect(within(drawer).getByTestId("ask-role-wake")).toHaveTextContent("architect.epic-1");
    fireEvent.change(within(drawer).getByLabelText("Role"), { target: { value: "reviewer" } });
    expect(within(drawer).getByTestId("ask-role-wake")).toHaveTextContent("reviewer.epic-1");
    fireEvent.change(within(drawer).getByLabelText("Question"), { target: { value: "is the verdict in?" } });
    fireEvent.click(within(drawer).getByTestId("ask-role-send"));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!).toEqual({ ticket_id: "epic-1", kind: "question", to: "reviewer", text: "is the verdict in?" });
    expect(await within(drawer).findByTestId("ask-role-sent")).toHaveTextContent("delivered to reviewer.epic-1");
  });

  it("Assign or spawn says which model + effort the epic's seats run on (owner m-2d7ef9243d)", async () => {
    mount(page({ seat_choice: { model: "astra", effort: "high", note: null } }));
    await title();
    const drawer = await openAction("assign-spawn");
    expect(await within(drawer).findByTestId("seat-choice")).toHaveTextContent("GPT-6 Astra, effort high");
  });

  it("Spawn the architect POSTs the pool spawn with role=architect and shows the hint (promise #18)", async () => {
    let body: Record<string, unknown> | null = null;
    mount(page());
    server.use(http.post("/v1/sessions/spawn", async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return okJson({ ok: true, session: "sid-7" }, "architect.epic-1 booted on the fleet host"); }));
    await title();
    const drawer = await openAction("assign-spawn");
    fireEvent.click(await within(drawer).findByTestId("spawn-architect-btn"));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!).toEqual({ role: "architect", participant_id: "architect.epic-1", ticket_id: "epic-1" });
    expect(await within(drawer).findByTestId("spawn-architect-hint")).toHaveTextContent("architect.epic-1 booted on the fleet host");
  });

  it("Spawn is hidden when the pool cannot spawn, and the board's reason shows verbatim", async () => {
    mount(page(), [], { resume_parked: false, resume_closed: false, park: false, spawn: false, reason: "pool unreachable" });
    await title();
    const drawer = await openAction("assign-spawn");
    expect(await within(drawer).findByTestId("spawn-unavailable")).toHaveTextContent("pool unreachable");
    expect(within(drawer).queryByTestId("spawn-architect")).not.toBeInTheDocument();
  });

  it("Spawn the architect reports the board's refusal hint (promise #18)", async () => {
    mount(page());
    server.use(http.post("/v1/sessions/spawn", () => HttpResponse.json({ ok: false, value: null, hint: "architect.epic-1 is already alive; message it instead" }, { status: 409 })));
    await title();
    const drawer = await openAction("assign-spawn");
    fireEvent.click(await within(drawer).findByTestId("spawn-architect-btn"));
    expect(await within(drawer).findByTestId("spawn-architect-error")).toHaveTextContent("architect.epic-1 is already alive; message it instead");
  });

  it("every Actions item carries a gloss saying what it does and who is woken (human #23)", async () => {
    mount(page({ answerable_gates: [{ ticket_id: "epic-1", gate: "acceptance", by: "owner", note: "accept the epic?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" }] }));
    await title();
    fireEvent.click(screen.getByTestId("actions-open"));
    const menu = await screen.findByTestId("actions-menu");
    for (const k of ["change-status", "answer-decision", "raise-decision", "assign-spawn", "ask-role"]) {
      expect(within(menu).getByTestId(`action-${k}`).textContent, k).toMatch(/wakes/i);
    }
    expect(within(menu).getByTestId("action-change-status")).toHaveTextContent(/owner and the architect/);
    expect(within(menu).getByTestId("action-answer-decision")).toHaveTextContent(/opener/);
    expect(within(menu).getByTestId("action-assign-spawn")).toHaveTextContent(/assignee/);
    for (const k of ["add-criterion", "original-request", "record"]) expect(within(menu).getByTestId(`action-${k}`).textContent!.length, k).toBeGreaterThan(30);
  });

  it("Assigned seats (under Assign or spawn) link to the Seats row with inline Message and Resume (human #24)", async () => {
    let resumed: Record<string, unknown> | null = null;
    server.use(http.post("/v1/sessions/resume", async ({ request }) => { resumed = (await request.json()) as Record<string, unknown>; return okJson({ ok: true }, "engineer.s-99 resumed from its parked session"); }));
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99", "architect.epic-1"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await title();
    await waitFor(() => expect(screen.getByTestId("work-assigned")).toHaveTextContent("engineer"));
    const drawer = await openAction("assign-spawn");
    const links = await within(drawer).findAllByTestId("assigned-seat-link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/seats#engineer.s-99", "/seats#architect.epic-1"]);
    const msgs = within(drawer).getAllByTestId("assigned-seat-message");
    expect(msgs[0]).toHaveAttribute("href", "/seats?message=engineer.s-99#engineer.s-99");
    expect(msgs[0].getAttribute("title")).toMatch(/wakes that seat/);
    fireEvent.click((await within(drawer).findAllByTestId("assigned-seat-resume"))[0]);
    await waitFor(() => expect(resumed).not.toBeNull());
    expect(resumed!).toEqual({ participant_id: "engineer.s-99", ticket_id: "s-99" });
    expect(await within(drawer).findByTestId("assigned-seat-hint")).toHaveTextContent("engineer.s-99 resumed from its parked session");
  });

  it("Change status opens the existing StatusControl in the drawer", async () => {
    mount(page());
    await title();
    const drawer = await openAction("change-status");
    expect(await within(drawer).findByTestId("status-control")).toBeInTheDocument();
  });

  it("Message on an assigned seat navigates to the Seats row", async () => {
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await title();
    const drawer = await openAction("assign-spawn");
    fireEvent.click(await within(drawer).findByTestId("assigned-seat-message"));
    expect(await screen.findByTestId("elsewhere")).toBeInTheDocument();
  });
});
