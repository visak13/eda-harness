import { it, expect } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { ContextualWork } from "./ContextualWork";
it("files-to-doc is one modal transition and preserves source context", async () => {
  server.use(
    http.get("/v1/tickets/epic-ctx/contextual", () => okJson({ ticket_id: "epic-ctx", title: "Context source", kind: "epic", status: "designed", owner: "owner", requester: "owner", assignee: null, design_ref: "design-ctx", scope: "Direct source", gates: [], events: [], records: [{ type: "doc", group: "Design", relation: "design_ref", record: { id: "design-ctx", title: "Readable design", version: 1 } }] })),
    http.get("/v1/docs/design-ctx/html", () => okJson({ id: "design-ctx", title: "Readable design", version: 1, versions: [1], scope: "epic-ctx", doc_type: "design", owner_role: "architect", html: "<p>Content</p>", body_md: "Content" })),
  );
  renderRoute("/epic/epic-ctx?view=files", "/epic/:id", <ContextualWork ticketId="epic-ctx" />);
  fireEvent.click(await screen.findByRole("button", { name: "Readable design v1" }));
  await screen.findByText("Content");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.queryByRole("dialog", { name: "Files & evidence" })).toBeNull();
  expect(screen.getByRole("link", { name: "Open in tab" })).toHaveAttribute("href", expect.stringContaining("source=epic-ctx"));
});
