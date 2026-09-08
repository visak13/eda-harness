import { describe, it, expect } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { LibraryPage } from "./Library";

const TABLE = {
  rows: [
    {
      id: "s-1",
      epic_id: "epic-1",
      title: "A story",
      kind: "story",
      work_type: "feature",
      status: "in_progress",
      assignee: "engineer.s-9",
      tags: ["web"],
      criteria: { passed: 1, failed: 0, pending: 1, total: 2 },
      blocked_by: [],
    },
  ],
  count: 1,
};

describe("LibraryPage — Tickets", () => {
  it("applies all seven legacy filters from the query string in one request", async () => {
    let seen = "";
    server.use(
      http.get("/v1/tickets/table", ({ request }) => {
        seen = new URL(request.url).search;
        return okJson(TABLE);
      }),
    );
    renderRoute(
      "/library/tickets?epic=epic-1&status=in_progress&kind=story&work_type=feature&assignee=eng&tag=web&q=story",
      "/library/:section",
      <LibraryPage />,
    );
    await screen.findByTestId("tickets-table");
    for (const p of ["epic=epic-1", "status=in_progress", "kind=story", "work_type=feature", "assignee=eng", "tag=web", "q=story"]) {
      expect(seen).toContain(p);
    }
    expect(screen.getByText("A story")).toBeInTheDocument();
  });

  it("changing a filter updates the query and re-requests", async () => {
    const seen: string[] = [];
    server.use(
      http.get("/v1/tickets/table", ({ request }) => {
        seen.push(new URL(request.url).search);
        return okJson(TABLE);
      }),
    );
    renderRoute("/library/tickets", "/library/:section", <LibraryPage />);
    await screen.findByTestId("tickets-table");
    fireEvent.change(screen.getByLabelText("status"), { target: { value: "done" } });
    await waitFor(() => expect(seen.some((s) => s.includes("status=done"))).toBe(true));
  });
});

describe("LibraryPage — History", () => {
  it("renders day-grouped activity lines", async () => {
    server.use(
      http.get("/v1/activity", () =>
        okJson([
          { day: "Monday 01 Sep", events: [{ line: "moved ready → in_progress", subject_id: "s-1", kind: "status_changed", at: "2026-09-01T09:30:00Z" }] },
        ]),
      ),
    );
    renderRoute("/library/history", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("Monday 01 Sep")).toBeInTheDocument();
    expect(screen.getByText(/moved ready/)).toBeInTheDocument();
  });

  it("the sub-nav lists all five sections", async () => {
    server.use(http.get("/v1/tickets/table", () => okJson(TABLE)));
    renderRoute("/library/tickets", "/library/:section", <LibraryPage />);
    for (const s of ["Documents", "Artifacts", "Links", "Tickets", "History"]) {
      expect(screen.getByRole("link", { name: s })).toBeInTheDocument();
    }
  });
});
