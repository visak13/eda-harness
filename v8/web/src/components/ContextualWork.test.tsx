import { it, expect } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { renderRoute } from "../pages/testUtils";
import { ContextualWork, attentionLine } from "./ContextualWork";

const okJson = (value: unknown) => HttpResponse.json({ ok: true, value });
const ctx = (over: Record<string, unknown> = {}) => ({
  ticket_id: "epic-ctx", title: "Context source", kind: "epic", status: "designed", owner: "owner", requester: "owner",
  assignee: null, design_ref: "design-ctx", scope: "Direct source", gates: [], events: [], blockers: [], unresolved_asks: [],
  records: [{ type: "doc", group: "Design", relation: "design_ref", record: { id: "design-ctx", title: "Readable design", version: 1 } }],
  ...over,
});

// The dedicated /records page ("Open in tab" from the header drawer) — design-a2e5369133 §Files.
it("files-to-doc is one modal transition and keeps the way back to the source", async () => {
  server.use(
    http.get("/v1/tickets/epic-ctx/contextual", () => okJson(ctx())),
    http.get("/v1/docs/design-ctx/html", () => okJson({ id: "design-ctx", title: "Readable design", version: 1, versions: [1], scope: "epic-ctx", doc_type: "design", owner_role: "architect", html: "<p>Content</p>", body_md: "Content" })),
  );
  renderRoute("/records/epic-ctx?view=files", "/records/:id", <ContextualWork ticketId="epic-ctx" dedicated />);
  expect(await screen.findByRole("link", { name: "Back to source: Context source" })).toHaveAttribute("href", expect.stringContaining("/epic/epic-ctx"));
  fireEvent.click(await screen.findByRole("button", { name: "Readable design · v1" }));
  await screen.findByText("Content");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
});

it("shows the designed empty state when nothing is attached", async () => {
  server.use(http.get("/v1/tickets/epic-ctx/contextual", () => okJson(ctx({ records: [] }))));
  renderRoute("/records/epic-ctx", "/records/:id", <ContextualWork ticketId="epic-ctx" />);
  expect(await screen.findByTestId("files-empty")).toHaveTextContent("Nothing attached yet");
});

it("degrades to the board's reason (never a blank pane) when the contextual route 404s", async () => {
  server.use(http.get("/v1/tickets/old/contextual", () => HttpResponse.json({ ok: false, error: "no route", hint: "not found" }, { status: 404 })));
  renderRoute("/records/old", "/records/:id", <ContextualWork ticketId="old" />);
  expect(await screen.findByTestId("files-unavailable")).toHaveTextContent(/cannot list files yet/);
});

it("attention line names unanswered requests, gates and blockers rather than a gate-only all-clear", () => {
  expect(attentionLine({ status: "in_progress", gates: [], blockers: [], unresolved_asks: [{ id: "m-question", kind: "question", to: "owner" }] })).toBe("1 unanswered request");
  expect(attentionLine({ status: "in_progress", gates: [], blockers: [], unresolved_asks: [] })).toBe("");
});
