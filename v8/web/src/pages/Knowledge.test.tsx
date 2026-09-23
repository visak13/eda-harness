import { describe, it, expect } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { server } from "../test/setup";
import { KNOWLEDGE_DIFF, KNOWLEDGE_VIEW } from "../test/handlers";
import { http, HttpResponse, okJson, renderRoute } from "./testUtils";
import { LibraryPage } from "./Library";

// S-LIBRARY c-ed2a341466 / c-14e93ebfc7: the Library's knowledge section — list, filters, proposal
// diff with Approve / Reject, edit as a new version, link/unlink to an epic, import from skills.sh.
function mount(path = "/library/knowledge") {
  server.use(http.get("/v1/knowledge", () => okJson(KNOWLEDGE_VIEW)), http.get("/v1/docs/:id/diff", () => okJson(KNOWLEDGE_DIFF)));
  return renderRoute(path, "/library/:section", <LibraryPage />);
}
const rows = () => screen.getAllByTestId("knowledge-row").map((r) => r.textContent ?? "");

describe("Library knowledge", () => {
  it("lists docs with a status word and lessons, and flags proposals", async () => {
    mount();
    await screen.findByTestId("knowledge-list");
    expect(rows()).toHaveLength(3);
    expect(screen.getAllByTestId("knowledge-status").map((s) => s.textContent)).toEqual(["Proposed", "Active", "Retired"]);
    expect(screen.getByTestId("knowledge-lesson")).toHaveTextContent("restart the board by pid");
    expect(screen.getByTestId("knowledge-proposed-banner")).toHaveTextContent("1 proposed doc waits");
  });

  it("filters by search, kind, tag and status", async () => {
    mount();
    await screen.findByTestId("knowledge-list");
    fireEvent.change(screen.getByTestId("knowledge-tag"), { target: { value: "testing" } });
    expect(rows()).toEqual([expect.stringContaining("py craft")]);
    expect(screen.queryByTestId("knowledge-lesson")).toBeNull(); // lessons carry no tags
    fireEvent.change(screen.getByTestId("knowledge-tag"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("knowledge-kind"), { target: { value: "domain" } });
    expect(rows()).toEqual([expect.stringContaining("board domain")]);
    fireEvent.change(screen.getByTestId("knowledge-kind"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("knowledge-status-filter"), { target: { value: "proposed" } });
    expect(rows()).toEqual([expect.stringContaining("py craft v2")]);
    fireEvent.change(screen.getByTestId("knowledge-status-filter"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("knowledge-search"), { target: { value: "pid" } });
    expect(screen.queryAllByTestId("knowledge-row")).toHaveLength(0);
    expect(screen.getByTestId("knowledge-lesson")).toBeInTheDocument();
  });

  it("shows a proposal's diff with words and approves it", async () => {
    let approved = "";
    server.use(http.post("/v1/docs/:id/approve", ({ params }) => { approved = String(params.id); return okJson({ doc: {}, target: {} }); }));
    mount("/library/knowledge?k=strategyhl-2");
    const detail = await screen.findByTestId("knowledge-detail");
    const diff = await within(detail).findByTestId("knowledge-diff");
    expect(diff).toHaveTextContent("added: +- rule two");
    expect(within(detail).getByTestId("knowledge-title-change")).toHaveTextContent("Title: “py craft” → “py craft v2”");
    expect(within(detail).getByTestId("knowledge-source")).toHaveTextContent("Proposed by engineer.s-1 on s-1 as the next version of strategyhl-1");
    fireEvent.click(within(detail).getByTestId("knowledge-approve"));
    await waitFor(() => expect(approved).toBe("strategyhl-2"));
  });

  it("rejects a proposal and shows the board's refusal verbatim", async () => {
    server.use(http.post("/v1/docs/:id/reject", () =>
      HttpResponse.json({ ok: false, error: { code: "scope", message: "only the owner approves or rejects a proposed doc" }, hint: "" }, { status: 403 })));
    mount("/library/knowledge?k=strategyhl-2");
    fireEvent.click(await screen.findByTestId("knowledge-reject"));
    expect(await screen.findByTestId("knowledge-error")).toHaveTextContent("only the owner approves or rejects a proposed doc");
  });

  it("edits a doc as a new version with tags", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("/v1/docs/:id", () => okJson({ id: "strategyhl-1", doc_type: "strategy_hl", title: "py craft", body_md: "- rule one",
        version: 3, tags: ["python"], status: "active", versions: [1, 2, 3] })),
      http.patch("/v1/docs/:id", async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return okJson({}); }),
    );
    mount("/library/knowledge?k=strategyhl-1");
    fireEvent.click(await screen.findByTestId("knowledge-edit"));
    const text = await screen.findByTestId("knowledge-edit-body");
    expect(text).toHaveValue("- rule one");
    fireEvent.change(text, { target: { value: "- rule one\n- rule two" } });
    fireEvent.change(screen.getByTestId("knowledge-edit-tags"), { target: { value: "Python, web" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect(body).toEqual({ body_md: "- rule one\n- rule two", tags: ["python", "web"] }));
  });

  it("links to an epic and unlinks", async () => {
    const calls: string[] = [];
    server.use(
      http.post("/v1/links", async ({ request }) => { const b = (await request.json()) as Record<string, string>; calls.push(`link ${b.from_id} ${b.relation} ${b.to_id}`); return okJson({}); }),
      http.delete("/v1/links/:id", ({ params }) => { calls.push(`unlink ${String(params.id)}`); return okJson({ deleted: true }); }),
    );
    mount("/library/knowledge?k=strategyhl-1");
    const linked = await screen.findByTestId("knowledge-linked");
    expect(linked).toHaveTextContent("The epic");
    const pick = screen.getByTestId("knowledge-link-epic");
    expect(within(pick).queryByText(/The epic/)).toBeNull(); // already linked: not offered again
    fireEvent.change(pick, { target: { value: "epic-2" } });
    fireEvent.click(screen.getByTestId("knowledge-link"));
    fireEvent.click(screen.getByTestId("knowledge-unlink"));
    await waitFor(() => expect([...calls].sort()).toEqual(["link epic-2 uses_strategy strategyhl-1", "unlink lk-1"]));
  });

  it("imports from skills.sh and reports the board's hint", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(http.post("/v1/library/import", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return okJson({ doc: { id: "strategyhl-9" }, created: true, fetched: "https://raw…" }, "imported as strategyhl-9 v1");
    }));
    mount();
    fireEvent.click(await screen.findByTestId("knowledge-import-open"));
    const dialog = await screen.findByRole("dialog", { name: "Import from skills.sh" });
    const run = within(dialog).getByTestId("knowledge-import-run");
    expect(run).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId("knowledge-import-url"), { target: { value: "https://skills.sh/anthropics/skills/frontend-design" } });
    fireEvent.click(run);
    expect(await within(dialog).findByTestId("knowledge-import-done")).toHaveTextContent("imported as strategyhl-9 v1");
    expect(sent).toEqual({ url: "https://skills.sh/anthropics/skills/frontend-design", tags: [] });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("creates a new knowledge doc", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(http.post("/v1/docs", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return okJson({ id: "domain-9" });
    }));
    mount();
    fireEvent.click(await screen.findByTestId("knowledge-new-open"));
    const dialog = await screen.findByRole("dialog", { name: "New knowledge doc" });
    fireEvent.change(within(dialog).getByLabelText("Kind"), { target: { value: "domain" } });
    fireEvent.change(within(dialog).getByTestId("knowledge-new-title"), { target: { value: "Board domain" } });
    fireEvent.change(within(dialog).getByLabelText(/Tags/), { target: { value: "board ops" } });
    fireEvent.change(within(dialog).getByTestId("knowledge-new-body"), { target: { value: "- a fact" } });
    fireEvent.click(within(dialog).getByTestId("knowledge-new-create"));
    await waitFor(() => expect(sent).toEqual({ scope: "global", doc_type: "domain", title: "Board domain", body_md: "- a fact", tags: ["board", "ops"] }));
  });
});
