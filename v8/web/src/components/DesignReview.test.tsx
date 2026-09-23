import { describe, it, expect } from "vitest";
import { screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { renderRoute } from "../pages/testUtils";
import { DesignReview } from "./DesignReview";
function mount(el = <DesignReview docId="design-test" version={2} source="epic-review" request="ev-review" />) {
  server.use(http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
    http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { to: "architect", plan: [], note: "Saved for next session" } })));
  server.use(http.get("/v1/docs/design-test/context", () => HttpResponse.json({ ok: true, value: {
    ticket_id: "epic-review", source_title: "Review source", source_kind: "epic", design_ref: "design-test", reviewed_version: 2,
    current_version: 2, gate_event_id: "ev-review", can_review: true, can_approve: true,
  } })));
  renderRoute("/doc/design-test", "/doc/:id", el);
}
describe("source-bound design review", () => {
  it("S19: one header per revision3-clean-review.png — the review panel sits beside the document; Cancel clears the feedback", async () => {
    mount();
    expect(await screen.findByTestId("review-state")).toHaveTextContent("Design · Version 2 · Review requested");
    expect(screen.getByRole("link", { name: "Back to source: Review source" })).toBeInTheDocument();
    // t-feb26a46d9: reader mode is the default — no panel, no index until the toggle shows them.
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(screen.getByTestId("review-reader-toggle"));
    // Only the two review actions in the header; commenting is the panel's link.
    expect(screen.queryAllByRole("button", { name: "Comment without requesting changes" })).toHaveLength(1);
    expect(screen.getByRole("complementary", { name: "Your review" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    const panel = screen.getByRole("complementary", { name: "Request changes" });
    expect(panel).toHaveTextContent("Regarding: design-test · v2");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Clarify the retry" } });
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Approve design" })).toBeEnabled();
  });
  it("t-feb26a46d9: opens in reader mode; the toggle shows and hides the comment panel and the index; Request changes shows the panel", async () => {
    mount(<DesignReview docId="design-test" version={2} source="epic-review" request="ev-review"
      outline={[{ level: 1, text: "Intro" }, { level: 2, text: "Detail" }]}><p>the design body</p></DesignReview>);
    await screen.findByTestId("review-state");
    const toggle = screen.getByTestId("review-reader-toggle");
    expect(screen.getByText("the design body")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle).toHaveTextContent("Show panel");
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByTestId("review-outline-side")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveTextContent("Reader mode");
    expect(screen.getByRole("complementary", { name: "Your review" })).toBeInTheDocument();
    expect(screen.getByTestId("review-outline-side")).toHaveTextContent("Detail");
    fireEvent.click(toggle);
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    expect(screen.getByRole("complementary", { name: "Request changes" })).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps an authorized nested document readable when the proposed source is unrelated", async () => {
    server.use(http.get("/v1/docs/design-nested/context", () => HttpResponse.json({ ok: false, error: "not linked", hint: "Choose a linked source" }, { status: 400 })));
    renderRoute("/doc/design-nested", "/doc/:id", <DesignReview docId="design-nested" version={1} source="epic-unrelated"><p>Authorized nested document body</p></DesignReview>);
    await screen.findByRole("alert");
    expect(screen.getByText("Authorized nested document body")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve design" })).toBeNull();
  });
  it("requests changes locally with pinned context; never calls the acceptance endpoint", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(http.post("/v1/gates/decide", async ({ request }) => { body = await request.json() as Record<string, unknown>; return HttpResponse.json({ ok: true, value: { message_id: "m-feedback", decision: "request_changes" } }); }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Request changes" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Please clarify the retry" } });
    expect(screen.getByRole("button", { name: "Approve design" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    await waitFor(() => expect(body).toMatchObject({ ticket_id: "epic-review", design_ref: "design-test", reviewed_version: 2, gate_event_id: "ev-review", decision: "request_changes", feedback: "Please clarify the retry" }));
    expect(await screen.findByText(/Design remains unapproved/)).toBeInTheDocument();
  });
  it("preserves failed feedback and reuses its idempotency key", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(http.post("/v1/docs/comments", async ({ request }) => { bodies.push(await request.json() as Record<string, unknown>); return HttpResponse.json({ ok: false, hint: "Please retry", error: "offline" }, { status: 503 }); }));
    mount();
    fireEvent.click(await screen.findByTestId("review-reader-toggle"));
    fireEvent.click(await screen.findByRole("button", { name: "Comment without requesting changes" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Keep this comment" } });
    fireEvent.click(screen.getByRole("button", { name: "Send comment" }));
    await screen.findByText(/offline/);
    expect(screen.getByRole("textbox")).toHaveValue("Keep this comment");
    cleanup(); mount();
    expect(await screen.findByRole("textbox")).toHaveValue("Keep this comment");
    fireEvent.click(screen.getByRole("button", { name: "Send comment" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[0].idempotency_key).toBe(bodies[1].idempotency_key);
  });

  it("shows the recipient once — the panel chip, never the composer's own To picker (finding 5)", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Request changes" }));
    await screen.findByRole("textbox");
    // the composer must NOT render its own recipient selector (that was the duplication)
    expect(screen.queryByTestId("to-picker")).toBeNull();
    // the recipient appears exactly once, as the panel's "To architect" chip
    expect(screen.getAllByText("architect")).toHaveLength(1);
  });
});
