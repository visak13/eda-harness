import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { server } from "../test/setup";
import { http, HttpResponse, okJson, renderRoute } from "./testUtils";
import { LibraryPage } from "./Library";
import { TopicPage } from "./TopicPage";
import { TicketPage } from "./Ticket";
import { attentionHandler } from "../test/attentionFixture";
import { SIGNOFF, asTicketThread, topicTicketHandlers, topicTicketPage } from "../test/topicTicketFixture";
import type { TopicPage as TopicPageData, TopicRow } from "../api/types";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const topicsCss = readFileSync(resolve(__dirname, "Topics.module.css"), "utf-8");

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
  allowlist: ["skills.sh", "www.skills.sh", "github.com", "raw.githubusercontent.com", "docs.pytest.org"],
  fetches: [{ url: "https://www.skills.sh/wshobson/agents/python-testing-patterns", status: 200, fetched_at: "2026-09-24T10:03:00Z", by: "sme.topic-1" }],
  viewer: { id: "owner", role: "owner" },
};

function mountPage(page: TopicPageData = PAGE) {
  server.use(http.get("/v1/topics/:id", () => okJson(page)), ...topicTicketHandlers("topic-1", page.topic.title, { thread: asTicketThread(page.thread) }));
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
    await waitFor(() => expect(body).toMatchObject({ title: "Rust async", tags: ["rust", "async"], seed_url: "https://tokio.rs/tokio/tutorial" }));
    await waitFor(() => expect(screen.queryByTestId("topic-open-dialog")).toBeNull()); // no experts: straight to the topic
  });

  it("a help thread (S19) names its Help seat and shows the thread's fix cards", async () => {
    const asked: string[] = [];
    server.use(http.get("/v1/fixes", ({ request }) => {
      asked.push(new URL(request.url).search);
      return okJson([{ id: "fix-9", topic_id: "topic-1", created_by: "doctor.topic-1", created_at: "2026-09-27",
        action: { kind: "service.restart", service: "broker" }, effect: "Restart the broker.",
        request: { method: "POST", path: "/v1/admin/services/broker/restart", body: { force: false, keep_seats: false } },
        status: "proposed", decided_by: null, decided_at: null, result: null, card: "" }]);
    }));
    mountPage({ ...PAGE, topic: { ...PAGE.topic, tags: ["help"] },
      seat: { ...PAGE.seat, participant: "doctor.topic-1", state: "dead", phase: "failed", reason: "clean exit: other" } });
    await screen.findByTestId("topic-page");
    // t-67dad8c6aa: the help thread says where the request is, with the failure reason
    expect(screen.getByTestId("topic-seat")).toHaveTextContent("Help seat doctor.topic-1 · Failed: clean exit: other. Send a message to retry.");
    expect(await screen.findByTestId("fix-request")).toHaveTextContent("POST /v1/admin/services/broker/restart");
    expect(asked[0]).toContain("topic_id=topic-1");
  });

  it("m10: the seat line names the catalog model, and the panels grow with their content", async () => {
    mountPage({ ...PAGE, seat: { ...PAGE.seat, model: "claude-opus-5-5", effort: "high" } });
    await screen.findByTestId("topic-page");
    expect(screen.getByTestId("topic-seat")).toHaveTextContent("sme.topic-1 · live · Claude Opus 5.5 at high");
    expect(screen.getByTestId("topic-seat")).not.toHaveTextContent("claude-opus-5-5");
    // a fixed-height scroll box cut the Docs card off (art-5e80d762a2): the page scrolls, not the panel
    const rule = /\.panelsAbove\s*\{([^}]*)\}/.exec(topicsCss)?.[1] ?? "";
    expect(rule).not.toMatch(/max-height|overflow/);
  });

  it("shows docs, thread, experts, seat and who set the tags; the owner edits the tags", async () => {
    let tags: unknown = null;
    server.use(http.patch("/v1/topics/:id/tags", async ({ request }) => { tags = await request.json(); return okJson({}); }));
    mountPage();
    await screen.findByTestId("topic-page");
    expect(screen.getByTestId("topic-seat")).toHaveTextContent("sme.topic-1 · live");
    // S12-ui2 (qa m-da89ef8294 m5): the header's status is the one status; no second "open" chip
    expect(screen.queryByTestId("topic-status")).toBeNull();
    expect(screen.getByTestId("topic-tags-by")).toHaveTextContent("set by sme.topic-1 · 2026-09-24 10:05");
    expect(screen.getByTestId("topic-doc")).toHaveTextContent("pytest patterns");
    expect(screen.getByTestId("topic-doc")).toHaveTextContent("python-testing-patterns");
    await screen.findAllByTestId("thread-message");
    const said = screen.getAllByTestId("thread-message").map((m) => m.textContent).join("|");
    expect(said).toContain("fixtures or factories?");
    expect(said).toContain("fixtures, scoped");
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

  it("posts through the ticket page's own composer and shows the board's refusal verbatim", async () => {
    let posted: unknown = null;
    server.use(http.post("/v1/messages", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ ok: false, error: { code: "invalid", message: "topic-1 is closed" }, hint: "" }, { status: 409 });
    }));
    mountPage();
    await screen.findByTestId("topic-page");
    fireEvent.change(await screen.findByTestId("composer-text"), { target: { value: "what about hypothesis?" } });
    fireEvent.click(screen.getByTestId("composer-send"));
    await waitFor(() => expect(posted).toMatchObject({ ticket_id: "topic-1", text: "what about hypothesis?" }));
    expect(await screen.findByText(/topic-1 is closed/)).toBeInTheDocument();
  });

  // sweep #1 (note-8f0629190d): the owner's topic page is the ticket page's conversation, not a second implementation
  it("gives the owner the ticket page's thread and composer features, and the expert the slim topic thread", async () => {
    mountPage();
    await screen.findByTestId("topic-page");
    expect(await screen.findByTestId("conversation")).toBeInTheDocument();
    expect(screen.getByTestId("order-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("composer-attach")).toBeInTheDocument();
    expect(screen.getByTestId("kind-picker")).toBeInTheDocument();
    expect(screen.queryByTestId("topic-thread")).toBeNull();
    expect(screen.queryByTestId("topic-composer")).toBeNull();
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

// S20 attention trail: Library → Topics → the topic row (dot + reason) → the question in its thread (marked, and
// highlighted when the link names it).
describe("Library topics attention (S20)", () => {
  it("marks the waiting topic row with its reason", async () => {
    server.use(attentionHandler(), http.get("/v1/topics", () => okJson([ROW, { ...ROW, id: "topic-2", title: "Quiet topic" }])));
    renderRoute("/library/topics", "/library/:section", <LibraryPage />);
    await waitFor(() => expect(screen.getAllByTestId("topic-row")).toHaveLength(2));
    // the hop before the row: Library's Topics tab carries the topics count
    expect(within(screen.getByRole("link", { name: /^Topics/ })).getByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    const [waiting, quiet] = screen.getAllByTestId("topic-row");
    expect(waiting).toHaveAttribute("data-attention", "true");
    expect(within(waiting).getByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    expect(within(waiting).getByTestId("attention-reason")).toHaveTextContent("1 question");
    expect(quiet).not.toHaveAttribute("data-attention");
  });

  it("marks the waiting question in the thread and highlights it from its #m- link", async () => {
    server.use(attentionHandler());
    const ask = { id: "m-topicq", created_at: "2026-09-24T10:08:00Z", created_by: "sme.topic-1", to: "owner", kind: "question", text: "which runner?",
      reply_to: null, from: { id: "sme.topic-1", role: "sme", type: "agent" } };
    server.use(http.get("/v1/topics/:id", () => okJson({ ...PAGE, thread: [...PAGE.thread, ask] })), ...topicTicketHandlers("topic-1", PAGE.topic.title, { thread: asTicketThread([...PAGE.thread, ask]) }));
    renderRoute("/library/topics/topic-1#m-topicq", "/library/topics/:id", <TopicPage />);
    await screen.findByText("which runner?");
    const li = document.getElementById("m-topicq")!;
    await waitFor(() => expect(li).toHaveAttribute("data-attention", "true"));
    await waitFor(() => expect(li).toHaveAttribute("data-highlight", "true"));
    expect(document.getElementById("m-1")).not.toHaveAttribute("data-attention");
  });

  // S16 c-320d037cb8: the owner's topic page is the ticket page's surface (header, Work drawer, Actions) plus the topic panels.
  it("renders the topic like a ticket page: criteria and sign-off, gates, files, work drawer, lifecycle, and the topic panel", async () => {
    server.use(attentionHandler(), ...topicTicketHandlers("topic-1", "Python testing", {
      criteria: [SIGNOFF],
      docs: [{ id: "note-t1", doc_type: "report", title: "Fixture notes", version: 1, scope: "topic-1", summary: "", full: "", relation: "evidence" }],
      open_gates: [{ ticket_id: "topic-1", gate: "demo", by: "owner", note: "is the sme on track?", opened_at: "2026-09-24T10:00:00Z", epic: "topic-1" }],
    }));
    server.use(http.get("/v1/topics/:id", () => okJson(PAGE)));
    renderRoute("/library/topics/topic-1", "/library/topics/:id", <TopicPage />);
    const header = await screen.findByTestId("work-header");
    expect(within(header).getByRole("link", { name: "Library" })).toHaveAttribute("href", "/library/topics");
    expect(within(header).queryByRole("link", { name: "Epics" })).toBeNull();
    expect(screen.getByTestId("work-status")).toHaveTextContent(/in progress/i);
    fireEvent.click(screen.getByTestId("work-work"));
    const work = await screen.findByTestId("ticket-work");
    expect(within(work).getByText(/Acceptance criteria \(1\)/)).toBeInTheDocument();
    expect(within(work).getByText("The sme's notes cover test fixtures")).toBeInTheDocument();
    expect(within(work).getByText("Process")).toBeInTheDocument();
    expect(within(work).getByText(/Linked documents \(1\)/)).toBeInTheDocument();
    expect(screen.getByTestId("work-files")).toBeInTheDocument();
    expect(screen.getByTestId("work-history")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("actions-open"));
    expect(await screen.findByTestId("action-answer-decision")).toBeInTheDocument();
    expect(screen.getByTestId("action-add-criterion")).toBeInTheDocument();
    expect(screen.getByTestId("action-change-status")).toBeInTheDocument();
    expect(screen.queryByTestId("action-models")).toBeNull();
    expect(screen.queryByTestId("action-assign-spawn")).toBeNull();
    const source = screen.getByTestId("topic-source");
    expect(within(source).getByTestId("topic-seed")).toHaveAttribute("href", "https://docs.pytest.org/en/stable/");
    expect(within(screen.getByTestId("topic-allowlist")).getAllByText(/\./).map((e) => e.textContent)).toContain("docs.pytest.org");
    expect(screen.getByTestId("topic-experts")).toHaveTextContent("priya");
    expect(screen.getByTestId("conversation")).toBeInTheDocument();
  });

  it("gives an expert the topic panel (seed URL, allowlist) without a single ticket-route call", async () => {
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => { seen.push(new URL(request.url).pathname); });
    server.use(http.get("/v1/topics/:id", () => okJson({ ...PAGE, viewer: { id: "priya", role: "expert" } })));
    renderRoute("/library/topics/topic-1", "/library/topics/:id", <TopicPage />);
    await screen.findByTestId("topic-source");
    expect(screen.getByTestId("topic-seed")).toHaveAttribute("href", "https://docs.pytest.org/en/stable/");
    expect(screen.getByTestId("topic-allowlist")).toHaveTextContent("github.com");
    expect(screen.queryByTestId("work-header")).toBeNull();
    expect(seen.filter((u) => u.startsWith("/v1/tickets/"))).toEqual([]);
    server.events.removeAllListeners();
  });

  it("sends a /ticket/<topic id> link to the topic's Library page", async () => {
    server.use(http.get("/v1/tickets/topic-1/page", () => okJson(topicTicketPage("topic-1", "Python testing"))));
    server.use(http.get("/v1/topics/:id", () => okJson(PAGE)), ...topicTicketHandlers("topic-1", "Python testing"));
    renderRoute("/ticket/topic-1", "/ticket/:id", <TicketPage />);
    await screen.findByTestId("elsewhere"); // no /ticket page rendered: the link was replaced by the Library route
  });
});
