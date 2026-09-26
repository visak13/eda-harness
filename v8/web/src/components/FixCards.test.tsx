import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { FixCards } from "./FixCards";
import type { FixProposal } from "../api/endpoints";

// S19 c-190f5c6276: a proposed fix is an admin approval card showing the exact action; Approve and Reject
// each call their admin route once; nothing is called before a press; a non-admin sees no card.

const FIX: FixProposal = {
  id: "fix-1", topic_id: "topic-h", created_by: "doctor.topic-h", created_at: "2026-09-27T10:00:00Z",
  action: { kind: "service.restart", service: "pool", keep_seats: true },
  effect: "Restart the pool process; running seats are re-adopted.",
  request: { method: "POST", path: "/v1/admin/services/pool/restart", body: { force: false, keep_seats: true } },
  status: "proposed", decided_by: null, decided_at: null, result: null, card: "[fix proposed] fix-1",
};

function renderCards(topicId?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><FixCards topicId={topicId} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

function trackCalls() {
  const calls: string[] = [];
  let decided = false;
  server.use(
    http.get("/v1/fixes", ({ request }) => {
      calls.push(`GET ${new URL(request.url).search}`);
      return HttpResponse.json({ ok: true, value: decided ? [] : [FIX] });
    }),
    http.post("/v1/admin/fixes/:id/approve", ({ params }) => {
      calls.push(`approve ${params.id}`);
      decided = true;
      return HttpResponse.json({ ok: true, value: { fix: { ...FIX, status: "applied", decided_by: "owner", result: { http_status: 200 } }, response: {} } });
    }),
    http.post("/v1/admin/fixes/:id/reject", ({ params }) => {
      calls.push(`reject ${params.id}`);
      decided = true;
      return HttpResponse.json({ ok: true, value: { ...FIX, status: "rejected", decided_by: "owner" } });
    }),
  );
  return calls;
}

describe("FixCards", () => {
  it("shows the exact action and calls nothing before a press; Approve calls the approve route once", async () => {
    const calls = trackCalls();
    renderCards();
    const card = await screen.findByTestId("fix-card");
    expect(card).toHaveTextContent(FIX.effect);
    expect(screen.getByTestId("fix-request")).toHaveTextContent(
      'POST /v1/admin/services/pool/restart {"force":false,"keep_seats":true}');
    expect(screen.getByRole("link", { name: "help thread" })).toHaveAttribute("href", "/library/topics/topic-h");
    expect(calls.filter((c) => !c.startsWith("GET"))).toEqual([]);
    expect(calls[0]).toContain("status=proposed");

    fireEvent.click(screen.getByTestId("fix-approve"));
    expect(await screen.findByTestId("fix-done")).toHaveTextContent("Applied: HTTP 200");
    expect(calls.filter((c) => !c.startsWith("GET"))).toEqual(["approve fix-1"]);
  });

  it("Reject calls only the reject route", async () => {
    const calls = trackCalls();
    renderCards("topic-h");
    await screen.findByTestId("fix-card");
    expect(calls[0]).toContain("topic_id=topic-h");
    expect(screen.queryByRole("link", { name: "help thread" })).toBeNull();   // already on the thread
    fireEvent.click(screen.getByTestId("fix-reject"));
    expect(await screen.findByTestId("fix-done")).toHaveTextContent("Rejected: nothing ran.");
    expect(calls.filter((c) => !c.startsWith("GET"))).toEqual(["reject fix-1"]);
  });

  it("shows the board's refusal of a decided fix", async () => {
    server.use(
      http.get("/v1/fixes", () => HttpResponse.json({ ok: true, value: [FIX] })),
      http.post("/v1/admin/fixes/:id/approve", () =>
        HttpResponse.json({ ok: false, error: { code: "http", message: "fix-1 was already applied by bob" }, hint: "" }, { status: 409 })),
    );
    renderCards();
    fireEvent.click(await screen.findByTestId("fix-approve"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already applied/);
  });

  it("renders nothing for a non-admin (403) or with no proposals", async () => {
    server.use(http.get("/v1/fixes", () => HttpResponse.json({ ok: false, error: { code: "http", message: "admins only" }, hint: "" }, { status: 403 })));
    const { container } = renderCards();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    server.use(http.get("/v1/fixes", () => HttpResponse.json({ ok: true, value: [] })));
    const r2 = renderCards();
    await waitFor(() => expect(r2.container).toBeEmptyDOMElement());
  });
});
