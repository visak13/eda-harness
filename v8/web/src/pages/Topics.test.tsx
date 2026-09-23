import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { server } from "../test/setup";
import { http, HttpResponse, okJson, renderRoute } from "./testUtils";
import { LibraryPage } from "./Library";
import { TopicPage } from "./TopicPage";
import type { TopicPage as TopicPageData, TopicRow } from "../api/types";

// S-SME-SURFACE (s-698224fca8) c-df07f026e7 / c-bc73017057: Library topics — the list beside Knowledge, the
// Open topic dialog, the topic page (docs, thread, experts, seat, tags with who set them), and the
// expert's view (topic routes only, owner controls hidden).
const ROW: TopicRow = {
  id: "topic-1", title: "Python testing", tags: ["python", "testing"], status: "open", created_at: "2026-09-24T10:00:00Z",
  created_by: "owner", seat: { participant: "sme.topic-1", state: "live" }, docs: 1, experts: 1, messages: 2,
};
const PAGE: TopicPageData = {
  topic: { ...ROW, description: "" },
  seed_url: "https://docs.pytest.org/en/stable/",
  tags_set_by: { by: "sme.topic-1", at: "2026-09-24T10:05:00Z" },
  docs: [{ id: "strategyhl-9", doc_type: "strategy_hl", title: "pytest patterns", version: 1, status: "proposed", tags: [],
    summary: "> Source: …", source_url: "https://www.skills.sh/wshobson/agents/python-testing-patterns",
    created_by: "sme.topic-1", created_at: "2026-09-24T10:04:00Z" }],
  thread: [
    { id: "m-1", created_at: "2026-09-24T10:06:00Z", created_by: "priya", to: null, kind: "question", text: "fixtures or factories?",
      reply_to: null, from: { id: "priya", role: "expert", type: "human" } },
    { id: "m-2", created_at: "2026-09-24T10:07:00Z", created_by: "sme.topic-1", to: "priya", kind: "answer", text: "fixtures, scoped",
      reply_to: "m-1", from: { id: "sme.topic-1", role: "sme", type: "agent" } },
  ],
  experts: [{ id: "priya", handle: "priya", created_at: "2026-09-24T10:02:00Z" }],
  seat: { participant: "sme.topic-1", state: "live" },
  fetches: [{ url: "https://www.skills.sh/wshobson/agents/python-testing-patterns", status: 200, fetched_at: "2026-09-24T10:03:00Z", by: "sme.topic-1" }],
  viewer: { id: "owner", role: "owner" },
};

function mountPage(page: TopicPageData = PAGE) {
  server.use(http.get("/v1/topics/:id", () => okJson(page)));
  return renderRoute("/library/topics/topic-1", "/library/topics/:id", <TopicPage />);
}

describe("Library topics", () => {
  it("lists topics beside Knowledge and opens a topic from the dialog", async () => {
    let body: unknown = null;
    server.use(
      http.get("/v1/topics", () => okJson([ROW])),
      http.post("/v1/topics", async ({ request }) => { body = await request.json(); return okJson({ topic: { id: "topic-2" }, seat: {} }); }),
    );
    renderRoute("/library/topics", "/library/:section", <LibraryPage />);
    expect(await screen.findByRole("link", { name: "Topics" })).toBeInTheDocument();
    const row = await screen.findByTestId("topic-row");
    expect(row).toHaveTextContent("Python testing");
    expect(row).toHaveAttribute("href", "/library/topics/topic-1");
    fireEvent.click(screen.getByTestId("topic-open-button"));
    const dlg = screen.getByTestId("topic-open-dialog");
    fireEvent.change(within(dlg).getByTestId("topic-open-title"), { target: { value: "Rust async" } });
    fireEvent.change(within(dlg).getByTestId("topic-open-tags"), { target: { value: "rust, async" } });
    fireEvent.change(within(dlg).getByTestId("topic-open-seed"), { target: { value: "http://tokio.rs" } });
    expect(within(dlg).getByRole("alert")).toHaveTextContent("must start with https://");
    expect(within(dlg).getByTestId("topic-open-create")).toBeDisabled();
    fireEvent.change(within(dlg).getByTestId("topic-open-seed"), { target: { value: "https://tokio.rs/tokio/tutorial" } });
    fireEvent.click(within(dlg).getByTestId("topic-open-create"));
    await waitFor(() => expect(body).toEqual({ title: "Rust async", tags: ["rust", "async"], seed_url: "https://tokio.rs/tokio/tutorial" }));
  });

  it("shows docs, thread, experts, seat and who set the tags; the owner edits the tags", async () => {
    let tags: unknown = null;
    server.use(http.patch("/v1/topics/:id/tags", async ({ request }) => { tags = await request.json(); return okJson({}); }));
    mountPage();
    await screen.findByTestId("topic-page");
    expect(screen.getByTestId("topic-seat")).toHaveTextContent("sme.topic-1 · live");
    expect(screen.getByTestId("topic-tags-by")).toHaveTextContent("set by sme.topic-1 · 2026-09-24 10:05");
    expect(screen.getByTestId("topic-doc")).toHaveTextContent("pytest patterns");
    expect(screen.getByTestId("topic-doc")).toHaveTextContent("python-testing-patterns");
    expect(screen.getAllByTestId("topic-message").map((m) => m.textContent)).toEqual([
      expect.stringContaining("fixtures or factories?"), expect.stringContaining("fixtures, scoped")]);
    expect(screen.getByTestId("topic-expert")).toHaveTextContent("priya");
    fireEvent.click(screen.getByTestId("topic-tags-edit"));
    fireEvent.change(screen.getByTestId("topic-tags-input"), { target: { value: "python, testing, owner-picked" } });
    fireEvent.click(screen.getByTestId("topic-tags-save"));
    await waitFor(() => expect(tags).toEqual({ tags: ["python", "testing", "owner-picked"] }));
  });

  it("adds an expert and shows the link once, then removes an expert", async () => {
    let removed = "";
    server.use(
      http.post("/v1/topics/:id/experts", () => okJson({ expert: { id: "ravi", handle: "ravi" }, token: "t0k", link: "/ui/library/topics/topic-1?as=ravi&token=t0k" })),
      http.delete("/v1/topics/:id/experts/:eid", ({ params }) => { removed = String(params.eid); return okJson({ removed: params.eid }); }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mountPage();
    await screen.findByTestId("topic-page");
    fireEvent.change(screen.getByTestId("topic-expert-handle"), { target: { value: "ravi" } });
    fireEvent.click(screen.getByTestId("topic-expert-add"));
    const link = await screen.findByTestId("topic-expert-link");
    expect(link).toHaveTextContent("/ui/library/topics/topic-1?as=ravi&token=t0k");
    fireEvent.click(within(link).getByRole("button", { name: "Done" }));
    expect(screen.queryByTestId("topic-expert-link")).toBeNull(); // not shown again
    fireEvent.click(within(screen.getByTestId("topic-expert")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(removed).toBe("priya"));
  });

  it("posts on the thread and shows the board's refusal verbatim", async () => {
    let posted: unknown = null;
    server.use(http.post("/v1/topics/:id/messages", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ ok: false, error: { code: "invalid", message: "topic-1 is closed" }, hint: "" }, { status: 409 });
    }));
    mountPage();
    await screen.findByTestId("topic-page");
    fireEvent.change(screen.getByTestId("topic-composer"), { target: { value: "what about hypothesis?" } });
    fireEvent.click(screen.getByTestId("topic-send"));
    await waitFor(() => expect(posted).toEqual({ text: "what about hypothesis?", kind: "question" }));
    expect(await screen.findByText("topic-1 is closed")).toBeInTheDocument();
  });

  it("gives an expert the topic only: no experts panel, no tag edit, no close, no link to the list", async () => {
    mountPage({ ...PAGE, viewer: { id: "priya", role: "expert" } });
    await screen.findByTestId("topic-page");
    expect(screen.getByTestId("topic-thread")).toBeInTheDocument();
    expect(screen.getByTestId("topic-composer")).toBeInTheDocument();
    expect(screen.queryByTestId("topic-experts")).toBeNull();
    expect(screen.queryByTestId("topic-tags-edit")).toBeNull();
    expect(screen.queryByTestId("topic-close")).toBeNull();
    expect(screen.queryByText("← All topics")).toBeNull();
  });

  it("reads a doc through the topic route", async () => {
    let asked = "";
    server.use(http.get("/v1/topics/:id/docs/:doc", ({ params }) => { asked = `${params.id}/${params.doc}`; return okJson({ body_md: "## Enforced\n- fixtures [required]" }); }));
    mountPage();
    await screen.findByTestId("topic-page");
    fireEvent.click(within(screen.getByTestId("topic-doc")).getByRole("button", { name: "pytest patterns" }));
    expect(await screen.findByText(/fixtures \[required\]/)).toBeInTheDocument();
    expect(asked).toBe("topic-1/strategyhl-9");
  });
});
