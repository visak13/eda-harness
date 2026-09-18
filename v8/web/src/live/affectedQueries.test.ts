import { it, expect } from "vitest";
import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { affectedBy } from "./affectedQueries";
import type { FeedEvent } from "./feed";
function rig() {
  const qc = new QueryClient();
  qc.setQueryData(["epic", "epic-a"], { board: { epic: { id: "epic-a", children: [{ id: "story-a", children: [] }] } }, docs: [] });
  qc.setQueryData(["library", "docs", "epic-a"], { docs: [] });
  qc.setQueryData(["tickets", "table", "epic-a"], { rows: [{ id: "story-a", epic_id: "epic-a" }] });
  const affected = (event: FeedEvent, key: QueryKey) => affectedBy(event, qc.getQueryCache().find({ queryKey: key, exact: true })!, qc.getQueryCache().getAll());
  return affected;
}
it("new grandchild refreshes its cached ancestor and scoped ticket table", () => {
  const affected = rig();
  const event = { seq: 1, kind: "ticket_created", subject_id: "new-task", data: { parent_id: "story-a" } };
  expect(affected(event, ["epic", "epic-a"])).toBe(true);
  expect(affected(event, ["tickets", "table", "epic-a"])).toBe(true);
});
it("new doc scope refreshes the matching epic and archive, not a different epic", () => {
  const affected = rig();
  for (const scope of ["epic-a", "epic-b"]) {
    const event = { seq: 1, kind: "doc_updated", subject_id: "new-doc", data: { scope } };
    expect(affected(event, ["epic", "epic-a"])).toBe(scope === "epic-a");
    expect(affected(event, ["library", "docs", "epic-a"])).toBe(scope === "epic-a");
  }
});
it("unrelated messages do not refetch scoped docs or ticket tables", () => {
  const affected = rig();
  const event = { seq: 1, kind: "message_sent", subject_id: "epic-b" };
  expect(affected(event, ["library", "docs", "epic-a"])).toBe(false);
  expect(affected(event, ["tickets", "table", "epic-a"])).toBe(false);
});
