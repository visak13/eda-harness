import { describe, it, expect } from "vitest";
import { screen, fireEvent, within, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { MODEL_CATALOG } from "../test/handlers";
import { http, okJson, renderRoute } from "./testUtils";
import { EpicPage } from "./Epic";
import { ATTENTION, attentionHandler, without } from "../test/attentionFixture";
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

function mount(data: EpicPageData, summary: Record<string, unknown>[] = [], caps: Record<string, unknown> = { resume_parked: true, resume_closed: false, park: true, spawn: true }, path = "/epic/epic-1") {
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
  renderRoute(path, "/epic/:id", <EpicPage />);
}

const seatRow = (id: string, state: string | null) => ({ id, handle: id, role: id.split(".")[0], state, ticket_id: id.split(".")[1], ticket_title: "t", last_output_at: new Date().toISOString(), presence_stale_since: null, reason: state === "dead" ? "closed by self: done" : "", latest_status: null });
const seatsAre = (...rows: ReturnType<typeof seatRow>[]) => server.use(http.get("/v1/seats", () => okJson({ seats: rows, people: [], retired: [] })));

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
  it("m12: a guest's epic page never asks for the owner-only pool capabilities, and logs no 403", async () => {
    const forbidden: string[] = [];
    const seen: string[] = [];
    const onResponse = ({ response, request }: { response: Response; request: Request }) => {
      if (response.status === 403) forbidden.push(new URL(request.url).pathname);
    };
    const onRequest = ({ request }: { request: Request }) => { seen.push(new URL(request.url).pathname); };
    server.events.on("response:mocked", onResponse);
    server.events.on("request:start", onRequest);
    try {
      server.use(http.get("/v1/whoami", () => okJson({ participant: { id: "gina", handle: "gina", role: "guest", type: "human" }, tickets: [], admin: false })));
      // the board's real answer to a guest (403): a page that asked would log it
      mount(page({ board: { ...page().board, epic: { ...page().board.epic, assignee: "architect.epic-1" } } }), [],
        { ok: false, error: { code: "forbidden", message: "owner only" } });
      server.use(http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: false, error: { code: "forbidden", message: "owner only" } }, { status: 403 })));
      await title();
      fireEvent.click(screen.getByTestId("actions-open"));
      await new Promise((r) => setTimeout(r, 300));
      expect(seen).toContain("/v1/epics/epic-1/page");
      expect(seen).not.toContain("/v1/pool/capabilities");
      expect(forbidden).toEqual([]);
    } finally {
      server.events.removeListener("response:mocked", onResponse);
      server.events.removeListener("request:start", onRequest);
    }
  });

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
    // Page indicator states what is shown and how many older remain.
    expect(screen.getByTestId("thread-page-indicator")).toHaveTextContent("Showing 100 of 235 · 135 older");
    const draft = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(draft, { target: { value: "Keep my unsent draft" } });
    const list = screen.getByTestId("thread"); list.scrollTop = 42;
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    await screen.findByText("History row 36");
    // Prepending a page reduces the older count.
    expect(screen.getByTestId("thread-page-indicator")).toHaveTextContent("Showing 200 of 235 · 35 older");
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
    // All loaded: the indicator confirms the full count, the "older" suffix is gone.
    expect(screen.getByTestId("thread-page-indicator")).toHaveTextContent("Showing 235 of 235");
    expect(screen.getByTestId("thread-page-indicator")).not.toHaveTextContent("older");
  }, 30_000);  // 235 rows over 3 pages: 5.5-6.7 s on CI runners (run 36324602815), past vitest's 5 s default

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
    // S12-ui2 (qa m-da89ef8294 item 7): one empty-state line, not two
    expect(within(work).queryByText("This epic has no stories yet.")).toBeNull();
    expect(within(work).getAllByText(/No stories yet/)).toHaveLength(1);
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
      node({ id: "s-2", title: "Bravo", status: "done", work_type: "bug", assignee: "sme.s-2" }),
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
    fireEvent.change(within(work).getByLabelText("Assignee contains"), { target: { value: "qa" } });
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
    server.use(http.post("/v1/messages", async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return okJson({ id: "m-9", unresolved_mentions: [] }, "delivered to qa.epic-1 (the epic's qa)"); }));
    await title();
    const drawer = await openAction("ask-role");
    fireEvent.click(within(drawer).getByTestId("ask-role-toggle"));
    expect(within(drawer).getByTestId("ask-role-wake")).toHaveTextContent("architect.epic-1");
    fireEvent.change(within(drawer).getByLabelText("Role"), { target: { value: "qa" } });
    expect(within(drawer).getByTestId("ask-role-wake")).toHaveTextContent("qa.epic-1");
    fireEvent.change(within(drawer).getByLabelText("Question"), { target: { value: "is the verdict in?" } });
    fireEvent.click(within(drawer).getByTestId("ask-role-send"));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!).toEqual({ ticket_id: "epic-1", kind: "question", to: "qa", text: "is the verdict in?" });
    expect(await within(drawer).findByTestId("ask-role-sent")).toHaveTextContent("delivered to qa.epic-1");
  });

  it("Assign or spawn says which model + effort the epic's seats run on (owner m-2d7ef9243d)", async () => {
    mount(page({ seat_choice: { model: "astra", effort: "high", note: null } }));
    await title();
    const drawer = await openAction("assign-spawn");
    expect(await within(drawer).findByTestId("seat-choice")).toHaveTextContent("GPT-6 Astra, effort high");
    expect(screen.getByRole("dialog", { name: "Assign or spawn a seat" })).toBeInTheDocument(); // the pool can spawn
  });

  it("S-UI: no MODELS strip in the header; Actions → Models… shows and switches each role's model and effort", async () => {
    mount(page({ role_models: { architect: "gpt-6-astra", engineer: "claude-opus-5-5", qa: "claude-fable-5-1", adversary: "gpt-6-astra", sme: "gpt-6-sol" } }));
    const tags = ["area:ui", "model:architect=gpt-6-astra", "model:sme=gpt-6-sol", "seat-effort:adversary=high", "seat-effort:medium"];
    let patched: Record<string, unknown> | null = null;
    server.use(
      http.get("/v1/models", () => okJson(MODEL_CATALOG)),
      http.get("/v1/tickets/epic-1", () => okJson({ id: "epic-1", kind: "epic", tags })),
      http.patch("/v1/tickets/epic-1", async ({ request }) => { patched = (await request.json()) as Record<string, unknown>; return okJson({ id: "epic-1", tags: patched.tags }, "updated"); }),
    );
    await title();
    expect(screen.queryByTestId("work-role-models")).not.toBeInTheDocument();
    expect(screen.queryByText("Models", { selector: "dt" })).not.toBeInTheDocument();
    const drawer = await openAction("models");
    const sel = (k: string, r: string) => within(drawer).getByTestId(`models-${k}-${r}`) as HTMLSelectElement;
    await waitFor(() => expect(sel("model", "architect").value).toBe("gpt-6-astra"));
    expect(within(drawer).getByTestId("models-dialog")).toBeInTheDocument();
    expect(["architect", "engineer", "qa", "adversary", "sme"].map((r) => sel("model", r).value))
      .toEqual(["gpt-6-astra", "claude-opus-5-5", "claude-fable-5-1", "gpt-6-astra", "gpt-6-sol"]);
    expect(["architect", "adversary", "qa"].map((r) => sel("effort", r).value)).toEqual(["medium", "high", "medium"]);
    expect(within(drawer).getByTestId("models-row-architect").querySelector("[data-provider-icon='gpt']")).not.toBeNull();
    expect(within(drawer).getByTestId("models-save")).toBeDisabled(); // nothing changed yet
    fireEvent.change(sel("model", "engineer"), { target: { value: "gpt-6-sol" } });
    fireEvent.change(sel("effort", "engineer"), { target: { value: "high" } });
    fireEvent.click(within(drawer).getByTestId("models-save"));
    await waitFor(() => expect(patched).not.toBeNull());
    // S7: a role with a tag list keeps its list (default first, effort named); the others keep the legacy pair
    expect(patched!.tags).toEqual(["area:ui",
      "model:architect=gpt-6-astra@medium", "model:engineer=gpt-6-sol@high", "model:sme=gpt-6-sol@medium",
      "model:qa=claude-fable-5-1", "model:adversary=gpt-6-astra",
      "seat-effort:qa=medium", "seat-effort:adversary=high"]);
    expect(await within(drawer).findByTestId("models-saved")).toBeInTheDocument();
  });

  it("the header names the live resident architect and its seat state (t-cf353a4051)", async () => {
    mount(page({ architect: { id: "architect.epic-9", state: "alive" } }));
    await title();
    expect(await screen.findByTestId("work-architect")).toHaveTextContent("Architect · running");
  });

  it("an owner-closed architect reads Closed, as on the Seats page, and not 'dead' (qa fail 9)", async () => {
    mount(page({ architect: { id: "architect.epic-9", state: "dead" } }));
    await title();
    const row = await screen.findByTestId("work-architect");
    await waitFor(() => expect(row).toHaveTextContent("Architect · closed"));
    expect(row).not.toHaveTextContent("dead");
  });

  it("an older board without the architect field renders no Architect row", async () => {
    mount(page());
    await title();
    expect(screen.queryByTestId("work-architect")).toBeNull();
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
    // S12-ui2: the title says what the dialog can do (no "spawn" it then says is unavailable)
    expect(screen.getByRole("dialog", { name: "Assign a seat" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /spawn/i })).toBeNull();
  });

  it("Spawn the architect reports the board's refusal hint (promise #18)", async () => {
    mount(page());
    server.use(http.post("/v1/sessions/spawn", () => HttpResponse.json({ ok: false, value: null, hint: "architect.epic-1 is already alive; message it instead" }, { status: 409 })));
    await title();
    const drawer = await openAction("assign-spawn");
    fireEvent.click(await within(drawer).findByTestId("spawn-architect-btn"));
    expect(await within(drawer).findByTestId("spawn-architect-error")).toHaveTextContent("architect.epic-1 is already alive; message it instead");
  });

  // S12-ui2 (qa m-da89ef8294) replaces human #23's "does / wakes" menu line: each item says what it does in one
  // plain sentence (who is woken stays in its tooltip).
  it("every Actions item carries a plain one-sentence description, also the dialog's subtitle", async () => {
    mount(page({ answerable_gates: [{ ticket_id: "epic-1", gate: "acceptance", by: "owner", note: "accept the epic?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" }] }));
    await title();
    fireEvent.click(screen.getByTestId("actions-open"));
    const menu = await screen.findByTestId("actions-menu");
    const items = within(menu).getAllByRole("menuitem");
    expect(items.length).toBeGreaterThan(8);
    for (const item of items) {
      const gloss = item.lastElementChild!.textContent!;
      expect(gloss, item.dataset.testid).toMatch(/^[A-Z][^]*\.$/);
      expect(gloss, item.dataset.testid).not.toMatch(/_|raw status|design link|\w\/\w/);
    }
    expect(within(menu).getByTestId("action-change-status")).toHaveTextContent("Move this epic to its next step.");
    expect(within(menu).getByTestId("action-record")).toHaveTextContent("The ids to quote in a message or a terminal.");
    fireEvent.click(within(menu).getByTestId("action-change-status"));
    expect(await screen.findByTestId("action-drawer-gloss")).toHaveTextContent("Move this epic to its next step.");
  });

  it("S12-ui2: the composer's placeholder is a plain sentence about Steer", async () => {
    mount(page());
    await title();
    expect(await screen.findByPlaceholderText("Write a message. Choose Steer to change the plan.")).toBeInTheDocument();
  });

  it("Assigned seats (under Assign or spawn) link to the Seats row with inline Message and Resume (human #24)", async () => {
    let resumed: Record<string, unknown> | null = null;
    server.use(http.post("/v1/sessions/resume", async ({ request }) => { resumed = (await request.json()) as Record<string, unknown>; return okJson({ ok: true }, "engineer.s-99 resumed from its parked session"); }));
    seatsAre(seatRow("engineer.s-99", "parked"), seatRow("architect.epic-1", "alive"));
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99", "architect.epic-1"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await title();
    const drawer = await openAction("assign-spawn");
    const links = await within(drawer).findAllByTestId("assigned-seat-link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/seats#engineer.s-99", "/seats#architect.epic-1"]);
    const msgs = within(drawer).getAllByTestId("assigned-seat-message");
    expect(msgs[0]).toHaveAttribute("href", "/seats?message=engineer.s-99#engineer.s-99");
    expect(msgs[0].getAttribute("title")).toMatch(/wakes that seat/i);
    fireEvent.click((await within(drawer).findAllByTestId("assigned-seat-resume"))[0]);
    await waitFor(() => expect(resumed).not.toBeNull());
    expect(resumed!).toEqual({ participant_id: "engineer.s-99", ticket_id: "s-99" });
    expect(await within(drawer).findByTestId("assigned-seat-hint")).toHaveTextContent("engineer.s-99 resumed from its parked session");
  });

  it("a live assigned seat has a Close that calls sessions/close (design-63db8a7d42 G)", async () => {
    let closed: Record<string, unknown> | null = null;
    server.use(http.post("/v1/sessions/close", async ({ request }) => { closed = (await request.json()) as Record<string, unknown>; return okJson({ closed: true }, "engineer.s-99 closed"); }));
    seatsAre(seatRow("engineer.s-99", "alive"));
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await title();
    const drawer = await openAction("assign-spawn");
    const close = await within(drawer).findByTestId("assigned-seat-close");
    fireEvent.click(close);
    await waitFor(() => expect(closed).not.toBeNull());
    expect(closed!).toEqual({ participant_id: "engineer.s-99", ticket_id: "s-99" });
    expect(await within(drawer).findByTestId("assigned-seat-hint")).toHaveTextContent("engineer.s-99 closed");
  });

  // qa c-4c274905e3: Resume / Close follow the Seats page's presence rule, one state per seat
  const ALL_CAPS = { resume_parked: true, resume_closed: true, park: true, spawn: true };
  for (const [state, resume, close, word] of [["alive", false, true, "Working"], ["stalled", true, true, "Stalled"], ["dead", true, false, "Closed"], ["parked", true, true, "Parked"], [null, false, false, "Not visible here"]] as const) {
    it(`an assigned seat that is ${state ?? "unknown"} says ${word ?? "nothing"} and offers ${resume ? "Resume" : "no Resume"} and ${close ? "Close" : "no Close"}`, async () => {
      seatsAre(seatRow("engineer.s-99", state));
      mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99"], waiting_reason: { presence: "alive" }, latest_status: "on it" }], ALL_CAPS);
      await title();
      const drawer = await openAction("assign-spawn");
      await waitFor(() => expect(within(drawer).getByTestId("assigned-seat")).toHaveAttribute("data-presence"));
      expect(within(drawer).queryByTestId("assigned-seat-resume") !== null).toBe(resume);
      expect(within(drawer).queryByTestId("assigned-seat-close") !== null).toBe(close);
      if (word) expect(within(drawer).getByTestId("assigned-seat-state")).toHaveTextContent(word); // the chip the Seats page shows
      else expect(within(drawer).queryByTestId("assigned-seat-state")).toBeNull();
    });
  }

  it("the Assign dialog and the header both read epic.assignee only: Unassigned when it is null, though a seat works a story", async () => {
    seatsAre(seatRow("engineer.s-99", "alive"));
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await title();
    await waitFor(() => expect(screen.getByTestId("work-assigned")).toHaveTextContent("Unassigned"));
    const drawer = await openAction("assign-spawn");
    expect(within(drawer).getByTestId("assign-current")).toHaveTextContent("Unassigned");
    expect(within(drawer).getByTestId("assigned-seat-link")).toHaveTextContent("engineer.s-99"); // still listed under Assigned seats
  });

  it("the dialog names a real epic assignee", async () => {
    mount(page({ board: { ...page().board, epic: { ...page().board.epic, assignee: "architect.epic-1" } } }));
    await title();
    const drawer = await openAction("assign-spawn");
    expect(within(drawer).getByTestId("assign-current")).toHaveTextContent("architect.epic-1");
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

describe("S-UI: the unanswered-request badge is a control (c-7e59da92c3)", () => {
  const msg = (id: string, text: string, at: string): MessageView =>
    ({ id, by: "architect.epic-1", to: "owner", kind: "question", text, at, reply_to: null }) as MessageView;
  const asks = [
    { id: "m-old", kind: "question", to: "owner", by: "architect.epic-1", at: "2026-09-20T10:00:00Z", text: "Which icon set?" },
    { id: "m-new", kind: "steer", to: "owner", by: "architect.epic-1", at: "2026-09-21T10:00:00Z", text: "Pick a filter" },
  ];
  function withAsks(n: number) {
    const thread = [msg("m-old", "Which icon set?", asks[0].at), msg("m-new", "Pick a filter", asks[1].at)];
    mount(page({}, thread));
    server.use(http.get("/v1/tickets/epic-1/contextual", () => okJson({
      ticket_id: "epic-1", title: "Upgrade the board UI", kind: "epic", status: "in_progress", owner: "owner", requester: "owner",
      assignee: null, design_ref: null, gates: [], scope: "epic-1", events: [], blockers: [], records: [],
      unresolved_asks: asks.slice(0, n) })));
  }

  it("one ask: clicking the badge scrolls to and highlights that message", async () => {
    withAsks(1);
    await title();
    const badge = await screen.findByTestId("attention-asks");
    expect(badge.tagName).toBe("BUTTON");
    expect(badge).toHaveTextContent("1 unanswered request");
    await screen.findByText("Which icon set?");
    fireEvent.click(badge);
    expect(document.getElementById("m-old")).toHaveAttribute("data-highlight", "true");
    expect(document.querySelectorAll("[data-highlight]")).toHaveLength(1);
  });

  it("several asks: clicking opens the list oldest first; a row jumps to and highlights its message", async () => {
    withAsks(2);
    await title();
    const badge = await screen.findByTestId("attention-asks");
    expect(badge).toHaveTextContent("2 unanswered requests");
    await screen.findByText("Pick a filter");
    fireEvent.click(badge);
    const rows = within(await screen.findByTestId("attention-asks-list")).getAllByTestId("attention-ask");
    expect(rows.map((r) => r.getAttribute("data-ask"))).toEqual(["m-old", "m-new"]);
    expect(rows[1]).toHaveTextContent("Pick a filter");
    fireEvent.click(rows[1]);
    expect(document.getElementById("m-new")).toHaveAttribute("data-highlight", "true");
    expect(document.getElementById("m-old")).not.toHaveAttribute("data-highlight");
    expect(screen.queryByTestId("attention-asks-list")).toBeNull();
  });

  it("e0cec S3: each row says why it is waiting on the owner, and a single ask carries it in the badge title", async () => {
    const why = "Addressed to you; work does not wait on it";
    asks.forEach((a) => Object.assign(a, { why }));
    withAsks(2);
    await title();
    const badge = await screen.findByTestId("attention-asks");
    await screen.findByText("Pick a filter");
    fireEvent.click(badge);
    const whys = within(await screen.findByTestId("attention-asks-list")).getAllByTestId("attention-ask-why");
    expect(whys.map((w) => w.textContent)).toEqual([why, why]);
  });
});

// t-994970028d: the architect's brief renders the board's description_html as markdown inside Clamp.
describe("EpicPage brief markdown", () => {
  it("renders <strong> and <li> and shows no literal **", async () => {
    mount(page({
      description: "**Brief:** concepts first\n\n- design\n- stories",
      description_html: "<p><strong>Brief:</strong> concepts first</p>\n<ul>\n<li>design</li>\n<li>stories</li>\n</ul>",
    }));
    await title();
    expect(screen.getByTestId("work-purpose")).toHaveTextContent(/^Brief: concepts first$/);
    const work = await openWork();
    const brief = within(work).getByTestId("architect-brief");
    expect(brief.querySelector("strong")).toHaveTextContent("Brief:");
    expect(brief.querySelectorAll("li")).toHaveLength(2);
    expect(brief.textContent).not.toContain("**");
  });
});

// S20 attention trail (design-e963c656f5 §4.18): inside the epic, the opener holding an item carries the dot, then
// the section, then the ticket row / the item — each with a non-colour marker and an aria-label.
describe("EpicPage attention trail (S20)", () => {
  const scopeGate = { event_id: "ev-scope", ticket_id: "epic-1", gate: "scope", by: "architect.epic-1", note: "cut the export?", opened_at: "2026-09-27T00:00:00Z", epic: "epic-1" };

  it("Work opener → the ticket row carry the dot; Actions → Answer a decision lists the gate, unmarked", async () => {
    server.use(attentionHandler());
    mount(page({ open_gates: [["epic-1", "scope"]], answerable_gates: [scopeGate] }));
    await title();
    const work = screen.getByTestId("work-work");
    expect(await within(work).findByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    expect(work).toHaveAttribute("data-attention", "true");
    const trigger = screen.getByTestId("actions-open");
    expect(within(trigger).queryByRole("img")).toBeNull();
    await openWork();
    const row = document.getElementById("row-s-1")!;
    expect(row).toHaveAttribute("data-attention", "true");
    expect(within(row).getByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    // steer m-4ed69369cb: the row leads to the ticket's newest waiting item, not the bare ticket page
    expect(within(row).getByRole("link")).toHaveAttribute("href", "/ticket/s-1#m-storyq");
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(trigger);
    const item = await screen.findByTestId("action-answer-decision");
    expect(item).not.toHaveAttribute("data-attention");
    fireEvent.click(item);
    await screen.findByTestId("action-drawer-answer-decision");
    expect(document.getElementById("ev-scope")).not.toHaveAttribute("data-attention");
  });

  it("a Work row with nothing waiting links to the ticket page", async () => {
    server.use(attentionHandler(without("c-1", "m-storyq")));
    mount(page());
    await title();
    await openWork();
    expect(within(document.getElementById("row-s-1")!).getByRole("link")).toHaveAttribute("href", "/ticket/s-1");
  });

  it("a ?request=<gate> deep link opens the decision drawer on the gate", async () => {
    server.use(attentionHandler());
    mount(page({ open_gates: [["epic-1", "scope"]], answerable_gates: [scopeGate] }), [], undefined, "/epic/epic-1?request=ev-scope");
    await title();
    await screen.findByTestId("action-drawer-answer-decision");
    expect(document.getElementById("ev-scope")).toBeInTheDocument();
  });

  it("clears: with nothing waiting no opener or row carries a dot", async () => {
    server.use(attentionHandler(without(...ATTENTION.items.map((i) => i.id))));
    mount(page());
    await title();
    await openWork();
    await waitFor(() => expect(document.querySelector("[data-attention-dot]")).toBeNull());
    expect(document.getElementById("row-s-1")).not.toHaveAttribute("data-attention");
  });

  // s-aa76c83998: the requirements list and the board's reason the epic cannot finish sit behind Work
  it("Work shows the marked requirements, open first, and why the epic is held", async () => {
    const reason = "1 open requirement (req-u)";
    server.use(attentionHandler(without(...ATTENTION.items.map((i) => i.id))));
    server.use(http.get("/v1/epics/epic-1/requirements", () => okJson({ digests: [], blocked_reason: reason, requirements: [
      { id: "req-c", state: "linked", epic: "epic-1", ticket: "s-1", source: "m-2", char_start: 0, char_end: 22, by: "owner",
        at: "2026-10-01T11:00:00+00:00", text: "quote works in the app", criterion: "c-9" },
      { id: "req-u", state: "open", epic: "epic-1", ticket: "epic-1", source: "m-1", char_start: 0, char_end: 26, by: "owner",
        at: "2026-10-01T10:00:00+00:00", text: "make the board trustworthy" },
    ] })));
    mount(page());
    await title();
    const work = await openWork();
    const rows = await within(work).findAllByTestId("req-row");
    expect(rows.map((r) => r.dataset.state)).toEqual(["open", "linked"]);
    expect(within(rows[1]).getByTestId("req-link")).toHaveTextContent("Covered by c-9");
    expect(within(work).getByTestId("gate-blocked-reason").textContent).toBe("1 open requirement"); // the board names the id for agents; the page does not
  });

  it("Work says no requirements are marked for an empty list", async () => {
    server.use(attentionHandler(without(...ATTENTION.items.map((i) => i.id))));
    mount(page());
    await title();
    const work = await openWork();
    expect(await within(work).findByTestId("requirements-empty")).toHaveTextContent("No requirements marked");
    expect(within(work).queryByTestId("gate-held")).toBeNull();
  });
});

// S12-ui3 (architect m-3264e7edf9 item 4): a menu label that opens a dialog ends in the "…" glyph, never three dots.
describe("Epic Actions labels (S12-ui3)", () => {
  it("uses the ellipsis glyph", async () => {
    mount(page());
    await title();
    fireEvent.click(screen.getByTestId("actions-open"));
    const models = await screen.findByTestId("action-models");
    expect(models).toHaveTextContent("Models…");
    expect(screen.getByTestId("actions-open").closest("body")!.textContent).not.toContain("...");
  });
});
