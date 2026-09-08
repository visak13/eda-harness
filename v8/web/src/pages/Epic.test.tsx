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
    ...over,
  };
}

function mount(data: EpicPageData) {
  server.use(http.get("/v1/epics/epic-1/page", () => okJson(data)));
  // summary is queried for the assigned-seat rail; default handler returns [], override to be safe
  server.use(http.get("/v1/epics/summary", () => okJson([])));
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
});
