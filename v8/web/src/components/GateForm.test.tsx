import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { GateRow } from "../api/types";
import { GateForm } from "./GateForm";

const gate: GateRow = {
  ticket_id: "epic-1",
  gate: "design_signoff",
  by: "architect.epic-1",
  note: "please rule",
  opened_at: "2026-09-08T00:00:00Z",
  epic: "epic-1",
};

function mount(onAnswered = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <GateForm gate={gate} onAnswered={onAnswered} />
    </QueryClientProvider>,
  );
  return onAnswered;
}

describe("GateForm", () => {
  it("shows the fixed gate kind and the opener, submit disabled until a ruling is typed", () => {
    mount();
    expect(screen.getByTestId("gate-kind")).toHaveTextContent("Design sign-off"); // human label, not the raw enum
    expect(screen.getByText(/architect\.epic-1/)).toBeInTheDocument();
    expect(screen.getByTestId("gate-submit")).toBeDisabled();
    fireEvent.change(screen.getByTestId("gate-answer"), { target: { value: "approved" } });
    expect(screen.getByTestId("gate-submit")).toBeEnabled();
  });

  it("Enter in the textarea does NOT submit; only the button posts the answer", async () => {
    let posted: { path: string; body: unknown } | null = null;
    server.use(
      http.post("/v1/gates/:t/:g/answer", async ({ request, params }) => {
        posted = { path: `${params.t}/${params.g}`, body: await request.json() };
        return HttpResponse.json({ ok: true, value: {} });
      }),
    );
    const onAnswered = mount();
    const ta = screen.getByTestId("gate-answer");
    fireEvent.change(ta, { target: { value: "approved" } });
    fireEvent.keyDown(ta, { key: "Enter" });
    expect(posted).toBeNull(); // Enter never submits a gate
    fireEvent.click(screen.getByTestId("gate-submit"));
    await waitFor(() => expect(onAnswered).toHaveBeenCalled());
    expect(posted).toMatchObject({ path: "epic-1/design_signoff", body: { answer: "approved" } });
  });
});
