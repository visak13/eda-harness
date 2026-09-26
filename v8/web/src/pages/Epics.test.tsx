import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent, within } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { EpicsPage } from "./Epics";
import { ATTENTION, attentionHandler, without } from "../test/attentionFixture";
import type { EpicSummaryRow } from "../api/types";

function row(over: Partial<EpicSummaryRow>): EpicSummaryRow {
  return {
    id: "epic-1",
    title: "Upgrade the board UI",
    status: "in_progress",
    created_at: "2026-09-01T10:00:00Z",
    criteria: { passed: 2, failed: 0, pending: 2, total: 4 },
    open_gates: 0,
    waiting_reason: { reason: "engineer building", presence: "alive", latest_status: "on it" },
    assigned_seats: ["engineer.s-1"],
    latest_status: "on it",
    ...over,
  };
}

describe("EpicsPage", () => {
  it("renders a row with the status word and 'N of M passed', with the waiting reason", async () => {
    server.use(http.get("/v1/epics/summary", () => okJson([row({})])));
    renderRoute("/epics", "/epics", <EpicsPage />);

    await screen.findByTestId("epic-list");
    expect(screen.getByText("Upgrade the board UI")).toBeInTheDocument();
    expect(screen.getByText("2 of 4 passed")).toBeInTheDocument();
    expect(screen.getByTestId("status-chip")).toHaveTextContent("In progress");
    expect(screen.getByTestId("waiting-reason")).toHaveTextContent("engineer building");
  });

  it("shows 'None defined' and no progress bar for a 0/0 epic", async () => {
    server.use(
      http.get("/v1/epics/summary", () =>
        okJson([row({ id: "epic-2", criteria: { passed: 0, failed: 0, pending: 0, total: 0 } })]),
      ),
    );
    renderRoute("/epics", "/epics", <EpicsPage />);
    await screen.findByTestId("epic-list");
    expect(screen.getByText("None defined")).toBeInTheDocument();
    // No progress bar for 0/0 (design §4.2): the tally reads as words alone.
    expect(screen.queryByText("0 of 0 passed")).not.toBeInTheDocument();
  });

  it("binds status/q to the query string: the URL params reach the request and the select", async () => {
    let seen = "";
    server.use(
      http.get("/v1/epics/summary", ({ request }) => {
        seen = new URL(request.url).search;
        return okJson([row({})]);
      }),
    );
    renderRoute("/epics?status=open&q=board", "/epics", <EpicsPage />);
    await screen.findByTestId("epic-list");
    expect(seen).toContain("status=open");
    expect(seen).toContain("q=board");
    expect((screen.getByLabelText("Filter by status") as HTMLSelectElement).value).toBe("open");
  });

  it("changing a filter re-issues the query with the new param", async () => {
    const seen: string[] = [];
    server.use(
      http.get("/v1/epics/summary", ({ request }) => {
        seen.push(new URL(request.url).search);
        return okJson([row({})]);
      }),
    );
    renderRoute("/epics", "/epics", <EpicsPage />);
    await screen.findByTestId("epic-list");
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "done" } });
    await waitFor(() => expect(seen.some((s) => s.includes("status=done"))).toBe(true));
  });
});

// S20 attention trail: an epic waiting on the viewer sorts first, is marked (inset rule + dot, never colour only) and
// names its one-line reason; it clears when the attention read no longer lists it.
describe("EpicsPage attention (S20)", () => {
  const rows = [row({ id: "epic-2", title: "Quiet epic" }), row({ id: "epic-1", title: "Galaxy site" })];

  it("sorts the waiting epic first, marks it and names the reason", async () => {
    server.use(attentionHandler(), http.get("/v1/epics/summary", () => okJson(rows)));
    renderRoute("/epics", "/epics", <EpicsPage />);
    await waitFor(() => expect(screen.getAllByTestId("epic-row")[0]).toHaveTextContent("Galaxy site"));
    const [first, second] = screen.getAllByTestId("epic-row");
    expect(first).toHaveAttribute("data-attention", "true");
    expect(within(first).getByRole("img", { name: "needs your attention: 5" })).toBeInTheDocument();
    expect(within(first).getByTestId("attention-reason")).toHaveTextContent("Waiting on you: 2 questions, 1 scope decision, 1 design sign-off, 1 sign-off");
    expect(second).not.toHaveAttribute("data-attention");
    expect(within(second).queryByRole("img")).toBeNull();
  });

  it("keeps the board's order and no marks once nothing waits", async () => {
    server.use(attentionHandler(without(...ATTENTION.items.map((i) => i.id))), http.get("/v1/epics/summary", () => okJson(rows)));
    renderRoute("/epics", "/epics", <EpicsPage />);
    await screen.findByTestId("epic-list");
    expect(screen.getAllByTestId("epic-row").map((r) => r.textContent)).toEqual([expect.stringContaining("Quiet epic"), expect.stringContaining("Galaxy site")]);
    expect(screen.queryByTestId("attention-reason")).toBeNull();
  });
});
