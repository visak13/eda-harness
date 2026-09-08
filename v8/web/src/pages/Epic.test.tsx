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
    words: epic.title,
    counts: { in_progress: 1 },
    thread,
    docs: [],
    open_gates: [],
    answerable_gates: [],
    criteria: [],
    ...over,
  };
}

function mount(data: EpicPageData) {
  server.use(http.get("/v1/epics/epic-1/page", () => okJson(data)));
  // summary is queried for the assigned-seat rail; default handler returns [], override to be safe
  server.use(http.get("/v1/epics/summary", () => okJson([])));
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
    // words quote carries the request verbatim
    expect(screen.getAllByText("Upgrade the board UI").length).toBeGreaterThanOrEqual(2);
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
});
