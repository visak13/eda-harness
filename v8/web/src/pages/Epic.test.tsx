import { describe, it, expect } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { EpicPage } from "./Epic";
import type { EpicPage as EpicPageData, EpicTreeNode, MessageView } from "../api/types";

function node(over: Partial<EpicTreeNode> = {}): EpicTreeNode {
  return {
    id: "s-1",
    kind: "story",
    work_type: "feature",
    title: "First story",
    status: "in_progress",
    assignee: "engineer.s-99",
    criteria: "2/4",
    gates: [],
    blocked_by: [],
    children: [],
    ...over,
  };
}

function page(over: Partial<EpicPageData> = {}, thread: MessageView[] = []): EpicPageData {
  const epic: EpicTreeNode = {
    id: "epic-1",
    kind: "epic",
    work_type: "feature",
    title: "Upgrade the board UI",
    status: "in_progress",
    assignee: null,
    criteria: "0/0",
    gates: [],
    blocked_by: [],
    children: [node()],
  };
  return {
    board: { epic, counts: { in_progress: 1 }, ready: [], in_review: [], open_gates: [], words: epic.title },
    words: "Upgrade the board UI so that a first-time human can read it without a shell",
    title: epic.title,
    counts: { in_progress: 1 },
    thread,
    docs: [],
    open_gates: [],
    answerable_gates: [],
    criteria: [],
    ...over,
  };
}

function mount(data: EpicPageData, summary: Record<string, unknown>[] = []) {
  server.use(http.get("/v1/epics/epic-1/page", () => okJson(data)));
  // summary is queried for the assigned-seat rail (fired inside render's act — install rows here)
  server.use(http.get("/v1/epics/summary", () => okJson(summary)));
  // the epic's status control reads its legal moves (epics are tickets → same route)
  server.use(
    http.get("/v1/tickets/epic-1/transitions", () =>
      okJson({ status: data.board.epic.status, transitions: [{ to: "done", allowed: true, reason: null }] }),
    ),
  );
  // the assign/spawn control on the epic rail reads pool capabilities
  server.use(http.get("/v1/pool/capabilities", () => okJson({ resume_parked: true, resume_closed: false, park: true, spawn: true })));
  renderRoute("/epic/epic-1", "/epic/:id", <EpicPage />);
}

describe("EpicPage", () => {
  it("shows the id + status word chip and the owner's words verbatim", async () => {
    mount(page());
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    expect(screen.getByTestId("status-chip")).toHaveTextContent("In progress");
    expect(screen.getByText(/Owner.s words/i)).toBeInTheDocument();
    // the words quote carries the request verbatim, once, under the short title (human #32)
    expect(screen.getByTestId("owner-words")).toHaveTextContent("without a shell");
  });

  it("renders the directive callout only when the thread carries an owner steer", async () => {
    // no steer → no callout
    mount(page({}, [{ id: "m1", by: "owner", to: null, kind: "note", text: "hi", at: "2026-09-01T10:00:00Z", reply_to: null }]));
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    expect(screen.queryByTestId("directive")).not.toBeInTheDocument();
  });

  it("shows the directive callout with the steer text when a steer is present", async () => {
    mount(
      page({}, [
        { id: "m2", by: "owner", to: null, kind: "steer", text: "concepts first, then build", at: "2026-09-02T10:00:00Z", reply_to: null },
      ]),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    expect(screen.getByTestId("directive")).toHaveTextContent("concepts first, then build");
  });

  it("Work tab shows a filter bar (status/work-type/assignee/q) mirroring the legacy epic filters", async () => {
    mount(page());
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    const bar = await screen.findByTestId("work-filters");
    expect(bar).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByLabelText("Work type")).toBeInTheDocument();
    expect(screen.getByLabelText("Assignee contains")).toBeInTheDocument();
    expect(screen.getByLabelText("Search words")).toBeInTheDocument();
    // kanban present when there are stories
    expect(screen.getByTestId("kanban")).toBeInTheDocument();
  });

  it("an epic with zero stories renders one sentence and no kanban columns", async () => {
    const data = page();
    data.board.epic.children = [];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    expect(await screen.findByText("This epic has no stories yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("kanban")).not.toBeInTheDocument();
  });

  it("At a glance renders the criteria tally as 'N of M passed'", async () => {
    mount(page());
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    expect(screen.getByText("2 of 4 passed")).toBeInTheDocument();
  });

  it("lists the epic's OWN acceptance criteria with a verdict pane, not just a count (§16)", async () => {
    mount(
      page({
        criteria: [
          { id: "c-e1", text: "the epic is accepted", check: "look", checked_by: "owner", verdict: "pending", evidence_ref: "report-1", evidence_version: 2 },
        ],
      }),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Overview/ }));
    expect(await screen.findByText("the epic is accepted")).toBeInTheDocument();
    // pending + evidence → the one-click ruling pane is on the epic page itself
    expect(screen.getByTestId("approve")).toBeInTheDocument();
    // and the add-criterion affordance is present
    expect(screen.getByText("Add an acceptance criterion")).toBeInTheDocument();
  });

  it("Documents tab lists linked docs; empty epic shows the no-docs sentence", async () => {
    mount(page({ docs: [{ id: "design-1", doc_type: "design_note", title: "The design", version: 1, scope: "epic-1", summary: "", full: "" }] }));
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Documents/ }));
    expect(await screen.findByText("The design")).toBeInTheDocument();
    expect(screen.getByText("design note")).toBeInTheDocument();
  });

  it("Documents tab shows an empty sentence when no docs are linked", async () => {
    mount(page({ docs: [] }));
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Documents/ }));
    expect(await screen.findByText("No documents are linked to this epic yet.")).toBeInTheDocument();
  });

  it("Overview shows a design link and the multi-story pulse sentence", async () => {
    const data = page({ docs: [{ id: "design-1", doc_type: "design", title: "The design", version: 1, scope: "epic-1", summary: "", full: "" }] });
    data.board.epic.children = [node({ id: "s-1" }), node({ id: "s-2", title: "Second story" })];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Overview/ }));
    // pulse sentence pluralises stories and shows the criteria + open gate tally
    expect(screen.getByText(/2 stories ·/)).toBeInTheDocument();
    expect(screen.getByText(/passed ·/)).toBeInTheDocument();
    // design link inside the overview
    expect(screen.getByRole("button", { name: "The design" })).toBeInTheDocument();
  });

  it("Overview pulse reads 'No stories yet' when the epic has none", async () => {
    const data = page();
    data.board.epic.children = [];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Overview/ }));
    expect(screen.getByText(/No stories yet — this epic is still being shaped/)).toBeInTheDocument();
  });

  it("Thread tab renders messages, toggles order, and shows the empty state", async () => {
    mount(
      page({}, [
        { id: "m1", by: "engineer.s-99", to: null, kind: "note", text: "first message", at: "2026-09-01T10:00:00Z", reply_to: null },
        { id: "m2", by: "owner", to: null, kind: "note", text: "second message", at: "2026-09-02T10:00:00Z", reply_to: null },
      ]),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Thread/ }));
    const toggle = await screen.findByTestId("order-toggle");
    expect(toggle).toHaveTextContent("Newest first");
    fireEvent.click(toggle);
    expect(toggle).toHaveTextContent("Oldest first");
    expect(screen.getByTestId("thread")).toHaveTextContent("first message");
  });

  it("Thread tab shows the empty state when there are no messages", async () => {
    mount(page({}, []));
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Thread/ }));
    expect(await screen.findByText("No messages on this epic yet.")).toBeInTheDocument();
  });

  it("Steer this epic jumps to the Thread tab with the steer composer", async () => {
    mount(page({}, []));
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByText("Actions", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Steer this epic" }));
    expect(await screen.findByTestId("order-toggle")).toBeInTheDocument();
  });

  it("Work tab filters by status, work type and assignee", async () => {
    const data = page();
    data.board.epic.children = [
      node({ id: "s-1", title: "Alpha", status: "in_progress", work_type: "feature", assignee: "engineer.s-1" }),
      node({ id: "s-2", title: "Bravo", status: "done", work_type: "bug", assignee: "reviewer.s-2" }),
    ];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    await screen.findByTestId("work-filters");
    // titles appear in both the tree and the kanban → use queryAll
    expect(screen.queryAllByText("Alpha").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Bravo").length).toBeGreaterThan(0);
    // status filter narrows to the in_progress story
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "done" } });
    expect(screen.queryAllByText("Alpha")).toHaveLength(0);
    expect(screen.queryAllByText("Bravo").length).toBeGreaterThan(0);
    // work type filter
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Work type"), { target: { value: "feature" } });
    expect(screen.queryAllByText("Alpha").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Bravo")).toHaveLength(0);
    // assignee contains
    fireEvent.change(screen.getByLabelText("Work type"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Assignee contains"), { target: { value: "reviewer" } });
    expect(screen.queryAllByText("Alpha")).toHaveLength(0);
    expect(screen.queryAllByText("Bravo").length).toBeGreaterThan(0);
  });

  it("Work tab with a no-match filter shows the empty sentence", async () => {
    const data = page();
    data.board.epic.children = [node({ id: "s-1", title: "Alpha", status: "in_progress" })];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    await screen.findByTestId("work-filters");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "done" } });
    expect(await screen.findByText("No tickets match these filters.")).toBeInTheDocument();
  });

  it("Work tab search resolves matching ids via the tickets table", async () => {
    server.use(
      http.get("/v1/tickets/table", () =>
        okJson({ rows: [{ id: "s-1", epic_id: "epic-1", title: "Alpha", kind: "story", work_type: "feature", status: "in_progress", assignee: null, tags: [], criteria: { passed: 0, failed: 0, pending: 0, total: 0 }, blocked_by: [] }], count: 1 }),
      ),
    );
    const data = page();
    data.board.epic.children = [
      node({ id: "s-1", title: "Alpha", status: "in_progress" }),
      node({ id: "s-2", title: "Bravo", status: "in_progress" }),
    ];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    await screen.findByTestId("work-filters");
    fireEvent.change(screen.getByLabelText("Search words"), { target: { value: "Alpha" } });
    const { waitFor } = await import("@testing-library/react");
    // once the search resolves, only the searched-for id (s-1 / Alpha) survives the qHits filter
    await waitFor(() => expect(screen.queryAllByText("Alpha").length).toBeGreaterThan(0));
    expect(screen.queryAllByText("Bravo")).toHaveLength(0);
  });

  it("renders the assigned-seat rail when the summary row carries seats", async () => {
    server.use(
      http.get("/v1/epics/summary", () =>
        okJson([
          {
            id: "epic-1",
            assigned_seats: ["engineer.s-99"],
            waiting_reason: { presence: "alive" },
            latest_status: "on it",
          },
        ]),
      ),
    );
    server.use(http.get("/v1/epics/epic-1/page", () => okJson(page())));
    server.use(
      http.get("/v1/tickets/epic-1/transitions", () =>
        okJson({ status: "in_progress", transitions: [{ to: "done", allowed: true, reason: null }] }),
      ),
    );
    server.use(http.get("/v1/pool/capabilities", () => okJson({ resume_parked: true, resume_closed: false, park: true, spawn: true })));
    renderRoute("/epic/epic-1", "/epic/:id", <EpicPage />);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(screen.getByText("on it")).toBeInTheDocument());
    expect(screen.getAllByText("engineer.s-99").length).toBeGreaterThan(0);
  });

  it("shows the loading state before the page resolves", async () => {
    mount(page());
    expect(screen.getByText("Loading epic…")).toBeInTheDocument();
  });

  it("shows an error banner when the epic page fails to load", async () => {
    const { HttpResponse } = await import("msw");
    server.use(http.get("/v1/epics/epic-1/page", () => new HttpResponse(null, { status: 500 })));
    server.use(http.get("/v1/epics/summary", () => okJson([])));
    renderRoute("/epic/epic-1", "/epic/:id", <EpicPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load epic-1/);
  });

  it("answers the epic's own open gate from the page (§16 Epic 'Answer gate')", async () => {
    let answered: Record<string, unknown> | null = null;
    mount(
      page({
        answerable_gates: [
          { ticket_id: "epic-1", gate: "acceptance", by: "owner", note: "accept the epic?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" },
        ],
      }),
    );
    server.use(
      http.post("/v1/gates/epic-1/acceptance/answer", async ({ request }) => {
        answered = (await request.json()) as Record<string, unknown>;
        return okJson({ ok: true });
      }),
    );
    const form = await screen.findByTestId("gate-form");
    const { within, waitFor } = await import("@testing-library/react");
    fireEvent.change(within(form).getByTestId("gate-answer"), { target: { value: "accepted" } });
    fireEvent.click(within(form).getByTestId("gate-submit"));
    await waitFor(() => expect(answered).not.toBeNull());
    expect(answered!).toMatchObject({ answer: "accepted" });
  });

  it("Ask a role posts a question addressed to the chosen role on the epic thread (promise #17)", async () => {
    let body: Record<string, unknown> | null = null;
    mount(page());
    server.use(
      http.post("/v1/messages", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "m-9", unresolved_mentions: [] }, "delivered to reviewer.epic-1 (the epic's reviewer)");
      }),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByTestId("ask-role-toggle"));
    // the gloss names who is woken: the epic's seat of that role
    expect(screen.getByTestId("ask-role-wake")).toHaveTextContent("architect.epic-1");
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "reviewer" } });
    expect(screen.getByTestId("ask-role-wake")).toHaveTextContent("reviewer.epic-1");
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "is the verdict in?" } });
    fireEvent.click(screen.getByTestId("ask-role-send"));
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!).toEqual({ ticket_id: "epic-1", kind: "question", to: "reviewer", text: "is the verdict in?" });
    // the board's resolution note is the confirmation, verbatim
    expect(await screen.findByTestId("ask-role-sent")).toHaveTextContent("delivered to reviewer.epic-1");
  });

  it("the assign/spawn card says which model + effort the epic's seats run on (owner m-2d7ef9243d)", async () => {
    mount(page({ seat_choice: { model: "astra", effort: "high", note: null } }));
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    expect(await screen.findByTestId("seat-choice")).toHaveTextContent("GPT-6 Astra, effort high");
  });

  it("Spawn the architect POSTs the pool spawn with role=architect for the epic and shows the hint (promise #18)", async () => {
    let body: Record<string, unknown> | null = null;
    mount(page());
    server.use(
      http.post("/v1/sessions/spawn", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ ok: true, session: "sid-7" }, "architect.epic-1 booted on the fleet host");
      }),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(await screen.findByTestId("spawn-architect-btn"));
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!).toEqual({ role: "architect", participant_id: "architect.epic-1", ticket_id: "epic-1" });
    expect(await screen.findByTestId("spawn-architect-hint")).toHaveTextContent("architect.epic-1 booted on the fleet host");
  });

  it("Spawn the architect is hidden when the pool cannot spawn, and shows the board's error hint verbatim", async () => {
    const data = page();
    server.use(http.get("/v1/epics/epic-1/page", () => okJson(data)));
    server.use(http.get("/v1/epics/summary", () => okJson([])));
    server.use(
      http.get("/v1/tickets/epic-1/transitions", () =>
        okJson({ status: "in_progress", transitions: [{ to: "done", allowed: true, reason: null }] }),
      ),
    );
    server.use(http.get("/v1/pool/capabilities", () => okJson({ resume_parked: false, resume_closed: false, park: false, spawn: false, reason: "pool unreachable" })));
    renderRoute("/epic/epic-1", "/epic/:id", <EpicPage />);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    await screen.findByTestId("spawn-unavailable");
    expect(screen.queryByTestId("spawn-architect")).not.toBeInTheDocument();
  });

  it("Spawn the architect reports the board's refusal hint (promise #18)", async () => {
    const { HttpResponse } = await import("msw");
    mount(page());
    server.use(
      http.post("/v1/sessions/spawn", () =>
        HttpResponse.json({ ok: false, value: null, hint: "architect.epic-1 is already alive; message it instead" }, { status: 409 }),
      ),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(await screen.findByTestId("spawn-architect-btn"));
    expect(await screen.findByTestId("spawn-architect-error")).toHaveTextContent("architect.epic-1 is already alive; message it instead");
  });

  it("every control carries a visible gloss saying what it does and who is woken (human #23)", async () => {
    mount(
      page({
        answerable_gates: [
          { ticket_id: "epic-1", gate: "acceptance", by: "owner", note: "accept the epic?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" },
        ],
      }),
    );
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByText("Actions", { exact: true }));
    fireEvent.click(screen.getByText("Actions & work details"));
    // the spawn-architect gloss renders with its button once capabilities resolve
    await screen.findByTestId("spawn-architect-btn");
    for (const k of ["steer", "change-status", "answer-decision", "raise-decision", "assign-spawn", "spawn-architect", "ask-role", "assigned-seats"]) {
      const gloss = screen.getByTestId(`gloss-${k}`);
      expect(gloss, k).toBeVisible();
      expect(gloss.textContent, k).toMatch(/wakes/i);
    }
    // the specifics the human asked for
    expect(screen.getByTestId("gloss-steer")).toHaveTextContent("POST /v1/messages/resolve");
    expect(screen.getByTestId("gloss-change-status")).toHaveTextContent(/owner and the architect/);
    expect(screen.getByTestId("gloss-answer-decision")).toHaveTextContent(/opener/);
    expect(screen.getByTestId("gloss-assign-spawn")).toHaveTextContent(/assignee/);
    expect(screen.getByTestId("gloss-spawn-architect")).toHaveTextContent(/new architect/);
  });

  it("Assigned seats link to the Seats row with inline Message and Resume (human #24)", async () => {
    let resumed: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/sessions/resume", async ({ request }) => {
        resumed = (await request.json()) as Record<string, unknown>;
        return okJson({ ok: true }, "engineer.s-99 resumed from its parked session");
      }),
    );
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99", "architect.epic-1"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    const links = await screen.findAllByTestId("assigned-seat-link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/seats#engineer.s-99", "/seats#architect.epic-1"]);
    expect(links[0]).toHaveTextContent("engineer.s-99");
    // Message → the seat's row with its composer open
    const msgs = screen.getAllByTestId("assigned-seat-message");
    expect(msgs[0]).toHaveAttribute("href", "/seats?message=engineer.s-99#engineer.s-99");
    expect(msgs[0].getAttribute("title")).toMatch(/wakes that seat/);
    // Resume → the same POST Seats.tsx sends, with the seat's own ticket; the hint shows verbatim
    const resumes = await screen.findAllByTestId("assigned-seat-resume");
    fireEvent.click(resumes[0]);
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(resumed).not.toBeNull());
    expect(resumed!).toEqual({ participant_id: "engineer.s-99", ticket_id: "s-99" });
    expect(await screen.findByTestId("assigned-seat-hint")).toHaveTextContent("engineer.s-99 resumed from its parked session");
  });

  // ── Astra visual ruling #36 (1)(3)(4) ─────────────────────────────────────────────────────────

  it("#36 (1): the meta line carries ONE status badge beside the id, wearing the status word", async () => {
    mount(page());
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    const badge = screen.getByTestId("epic-status-badge");
    expect(badge).toHaveTextContent("In progress");
    // exactly one status chip in the header (the rail shows the change button, not a second chip)
    expect(screen.getAllByTestId("status-chip")).toHaveLength(1);
  });

  it("#36 (1): the owner's words sit in a callout with a two-line preview and a Show all / Show less disclosure", async () => {
    // jsdom lays nothing out; make the clamped block report overflow so the disclosure appears
    const sh = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    const ch = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 96 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 64 });
    try {
      mount(page());
      await screen.findByText("Upgrade the board UI", { selector: "h1" });
      const { within } = await import("@testing-library/react");
      const callout = screen.getByTestId("owner-words");
      expect(callout).toHaveTextContent(/Owner.s words · original request/i);
      expect(within(callout).getByTestId("owner-words-text")).toHaveTextContent("without a shell");
      const toggle = within(callout).getByRole("button", { name: "Show all" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      fireEvent.click(toggle);
      expect(within(callout).getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    } finally {
      if (sh) Object.defineProperty(HTMLElement.prototype, "scrollHeight", sh);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
      if (ch) Object.defineProperty(HTMLElement.prototype, "clientHeight", ch);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
    }
  });

  it("#36 (3): the Work search narrows rows by title / id text at once; Filters is a disclosure over the status controls", async () => {
    server.use(http.get("/v1/tickets/table", () => okJson({ rows: [], count: 0 })));
    const data = page();
    data.board.epic.children = [
      node({ id: "s-1", title: "Alpha", status: "in_progress" }),
      node({ id: "s-2", title: "Bravo", status: "in_progress" }),
    ];
    mount(data);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    expect(await screen.findAllByTestId("work-row")).toHaveLength(2);
    const fold = screen.getByTestId("work-filters-fold");
    expect(fold.tagName).toBe("DETAILS");
    expect(fold).toHaveTextContent("Filters");
    expect(fold).not.toHaveAttribute("open");
    // by id
    fireEvent.change(screen.getByTestId("work-search"), { target: { value: "s-2" } });
    let rows = screen.getAllByTestId("work-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Bravo");
    // by title, case-insensitively; the id sits under the title in the same row
    fireEvent.change(screen.getByTestId("work-search"), { target: { value: "alph" } });
    rows = screen.getAllByTestId("work-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Alpha");
    expect(rows[0]).toHaveTextContent("s-1");
    // no hit → the empty sentence
    fireEvent.change(screen.getByTestId("work-search"), { target: { value: "zzz" } });
    expect(screen.getByText("No tickets match these filters.")).toBeInTheDocument();
  });

  it("#36 (4): the rail's Change status button reveals the status control on the #epic-status card", async () => {
    mount(page());
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    const card = document.getElementById("epic-status");
    expect(card).not.toBeNull();
    const toggle = screen.getByTestId("change-status-toggle");
    expect(toggle).toHaveTextContent("Change status");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("epic-status-control")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const control = await screen.findByTestId("epic-status-control");
    expect(card!.contains(control)).toBe(true);
    // the existing StatusControl reads its legal moves once revealed
    expect(await screen.findByTestId("status-control")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByTestId("epic-status-control")).not.toBeInTheDocument();
  });

  it("#36 (4): the lifecycle text lives in a Status history fold and the strip's Next: sentence is gone", async () => {
    mount(page());
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    const history = screen.getByTestId("status-history");
    expect(history.tagName).toBe("DETAILS");
    expect(history).not.toHaveAttribute("open");
    expect(history).toHaveTextContent("Status history");
    expect(history).toHaveTextContent("Next: Do the work and attach evidence");
    // the step chips stay; the duplicate sentence under them does not
    expect(screen.getByTestId("process-strip")).toBeInTheDocument();
    expect(screen.getByTestId("stage-current")).toHaveTextContent("In progress");
    expect(screen.queryByTestId("next-action")).not.toBeInTheDocument();
  });

  it("Message on an assigned seat navigates to the Seats row", async () => {
    mount(page(), [{ id: "epic-1", assigned_seats: ["engineer.s-99"], waiting_reason: { presence: "alive" }, latest_status: "on it" }]);
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    fireEvent.click(await screen.findByTestId("assigned-seat-message"));
    // renderRoute's catch-all route receives the navigation to /seats
    expect(await screen.findByTestId("elsewhere")).toBeInTheDocument();
  });
});
