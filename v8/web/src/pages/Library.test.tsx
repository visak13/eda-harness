import { describe, it, expect } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { LibraryPage } from "./Library";

const LIB = {
  docs: [{ id: "design-1", doc_type: "design_note", title: "The design", version: 2, scope: "epic-1", summary: "", full: "" }],
  artifacts: [
    { id: "art-1", form: "image", uri: "http://x/one.png", note: "a shot", created_by: "engineer.s-1", created_at: "2026-09-01T10:00:00Z" },
    { id: "art-2", form: "file", uri: "http://x/two.txt", note: "", created_by: "engineer.s-1", created_at: "2026-09-01T10:00:00Z" },
  ],
  links: [{ id: "l-1", from_id: "s-1", to_id: "design-1", relation: "designed_by", created_by: "architect.epic-1" }],
};
const EMPTY_LIB = { docs: [], artifacts: [], links: [] };

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

describe("LibraryPage — Documents", () => {
  it("lists documents with the doc type de-underscored and passes ?epic to the read", async () => {
    let seen = "";
    server.use(
      http.get("/v1/library", ({ request }) => {
        seen = new URL(request.url).search;
        return okJson(LIB);
      }),
    );
    renderRoute("/library/documents?epic=epic-1", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("The design")).toBeInTheDocument();
    expect(screen.getByText("design note")).toBeInTheDocument();
    expect(seen).toContain("epic=epic-1");
  });

  it("shows the empty state when there are no documents", async () => {
    server.use(http.get("/v1/library", () => okJson(EMPTY_LIB)));
    renderRoute("/library/documents", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("No documents.")).toBeInTheDocument();
  });

  it("surfaces a load error as an alert banner", async () => {
    server.use(http.get("/v1/library", () => new HttpResponse(null, { status: 500 })));
    renderRoute("/library/documents", "/library/:section", <LibraryPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("LibraryPage — Artifacts", () => {
  it("lists artifacts, rendering the note only when present", async () => {
    server.use(http.get("/v1/library", () => okJson(LIB)));
    renderRoute("/library/artifacts", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("http://x/one.png")).toBeInTheDocument();
    expect(screen.getByText("a shot")).toBeInTheDocument();
    // second artifact has an empty note → no note span text for it
    expect(screen.getByText("http://x/two.txt")).toBeInTheDocument();
  });

  it("shows the empty state when there are no artifacts", async () => {
    server.use(http.get("/v1/library", () => okJson(EMPTY_LIB)));
    renderRoute("/library/artifacts", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("No artifacts.")).toBeInTheDocument();
  });
});

describe("LibraryPage — Links", () => {
  it("renders the link table", async () => {
    server.use(http.get("/v1/library", () => okJson(LIB)));
    renderRoute("/library/links", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("designed_by")).toBeInTheDocument();
    expect(screen.getAllByText("s-1").length).toBeGreaterThan(0);
  });

  it("shows the empty state when there are no links", async () => {
    server.use(http.get("/v1/library", () => okJson(EMPTY_LIB)));
    renderRoute("/library/links", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("No links.")).toBeInTheDocument();
  });
});

describe("LibraryPage — routing + empty states", () => {
  it("falls back to Tickets for an unknown section", async () => {
    server.use(http.get("/v1/tickets/table", () => okJson(TABLE)));
    renderRoute("/library/bogus", "/library/:section", <LibraryPage />);
    expect(await screen.findByTestId("ticket-filters")).toBeInTheDocument();
  });

  it("shows the no-tickets empty state when the table is empty", async () => {
    server.use(http.get("/v1/tickets/table", () => okJson({ rows: [], count: 0 })));
    renderRoute("/library/tickets", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("No tickets match these filters.")).toBeInTheDocument();
  });

  it("surfaces a tickets-table load error", async () => {
    server.use(http.get("/v1/tickets/table", () => new HttpResponse(null, { status: 500 })));
    renderRoute("/library/tickets", "/library/:section", <LibraryPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("shows the no-activity empty state for History", async () => {
    server.use(http.get("/v1/activity", () => okJson([])));
    renderRoute("/library/history", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("No activity yet.")).toBeInTheDocument();
  });

  it("surfaces a history load error", async () => {
    server.use(http.get("/v1/activity", () => new HttpResponse(null, { status: 500 })));
    renderRoute("/library/history", "/library/:section", <LibraryPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
