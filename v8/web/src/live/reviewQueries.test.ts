import { it, expect } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { affectedBy } from "./affectedQueries";
it("review and contextual caches refresh only for their source/document", () => {
  const qc = new QueryClient();
  const keys = [["contextual", "epic-a", "all"], ["review-context", "epic-a", "design-a", 1]];
  for (const key of keys) qc.setQueryData(key, { records: [{ record: { id: "design-a" } }] });
  for (const query of qc.getQueryCache().getAll()) {
    expect(affectedBy({ seq: 1, kind: "design_reviewed", subject_id: "epic-b" }, query)).toBe(false);
    expect(affectedBy({ seq: 2, kind: "design_reviewed", subject_id: "epic-a" }, query)).toBe(true);
    expect(affectedBy({ seq: 3, kind: "doc_updated", subject_id: "design-a" }, query)).toBe(true);
    expect(affectedBy({ seq: 4, kind: "doc_updated", subject_id: "design-b" }, query)).toBe(false);
  }
});
