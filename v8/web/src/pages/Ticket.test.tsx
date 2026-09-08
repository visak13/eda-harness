import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
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
    ...over,
  };
}

function mount(data: TicketPageData) {
  server.use(http.get("/v1/tickets/s-1/page", () => okJson(data)));
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
});
