import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { GateRow } from "../api/types";
import { GateForm } from "./GateForm";

const gate: GateRow = {
  ticket_id: "epic-1",
  gate: "acceptance", // design_signoff renders the source-review link instead of a form
  by: "architect.epic-1",
  note: "please rule",
  opened_at: "2026-09-08T00:00:00Z",
  epic: "epic-1",
};

function mount(onAnswered = vi.fn(), row: GateRow = gate) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><GateForm gate={row} onAnswered={onAnswered} /></MemoryRouter>
    </QueryClientProvider>,
  );
  return onAnswered;
}

describe("GateForm", () => {
  it("shows the fixed gate kind and the opener, submit disabled until a ruling is typed", () => {
    mount();
    expect(screen.getByTestId("gate-kind")).toHaveTextContent("Acceptance"); // human label, not the raw enum
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
    expect(posted).toMatchObject({ path: "epic-1/acceptance", body: { answer: "approved" } });
  });

  it("renders a gate with no note (the em-dash quote branch is skipped)", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><GateForm gate={{ ...gate, note: "" }} /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText(/opened by architect\.epic-1/)).toBeInTheDocument();
    expect(screen.queryByText(/please rule/)).not.toBeInTheDocument();
  });

  it("keeps the ruling and shows an error when the answer POST fails", async () => {
    server.use(
      http.post("/v1/gates/:t/:g/answer", () => new HttpResponse(null, { status: 500 })),
    );
    mount();
    fireEvent.change(screen.getByTestId("gate-answer"), { target: { value: "approved" } });
    fireEvent.click(screen.getByTestId("gate-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/your ruling is kept/);
  });
});

describe("GateForm design_signoff", () => {
  it("renders the review-at-source link instead of a ruling form", () => {
    mount(undefined, { ...gate, gate: "design_signoff", event_id: "ev-1" });
    expect(screen.queryByTestId("gate-answer")).toBeNull();
    expect(screen.getByRole("link", { name: "Review design at source" })).toHaveAttribute("href", expect.stringContaining("/epic/epic-1?"));
  });
});
