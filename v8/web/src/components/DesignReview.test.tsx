import { describe, it, expect } from "vitest";
import { screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { renderRoute } from "../pages/testUtils";
import { DesignReview } from "./DesignReview";
function mount() {
  server.use(http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
    http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { to: "architect", plan: [], note: "Saved for next session" } })));
  server.use(http.get("/v1/docs/design-test/context", () => HttpResponse.json({ ok: true, value: {
    ticket_id: "epic-review", source_title: "Review source", source_kind: "epic", design_ref: "design-test", reviewed_version: 2,
    current_version: 2, gate_event_id: "ev-review", can_review: true, can_approve: true,
  } })));
  renderRoute("/doc/design-test", "/doc/:id", <DesignReview docId="design-test" version={2} source="epic-review" request="ev-review" />);
}
describe("source-bound design review", () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(body).toMatchObject({ ticket_id: "epic-review", design_ref: "design-test", reviewed_version: 2, gate_event_id: "ev-review", decision: "request_changes", feedback: "Please clarify the retry" }));
    expect(await screen.findByText(/Design remains unapproved/)).toBeInTheDocument();
  });
  it("preserves failed feedback and reuses its idempotency key", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(http.post("/v1/docs/comments", async ({ request }) => { bodies.push(await request.json() as Record<string, unknown>); return HttpResponse.json({ ok: false, hint: "Please retry", error: "offline" }, { status: 503 }); }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Comment without requesting changes" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Keep this comment" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText(/offline/);
    expect(screen.getByRole("textbox")).toHaveValue("Keep this comment");
    cleanup(); mount();
    expect(await screen.findByRole("textbox")).toHaveValue("Keep this comment");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
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
