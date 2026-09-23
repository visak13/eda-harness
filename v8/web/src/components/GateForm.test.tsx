import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { GateRow } from "../api/types";
import { GateForm, useRetainedGates } from "./GateForm";

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

  // S22 (consult #3): the gate leaves the open list (answered in another tab) while a ruling is unsent.
  it("a gate answered elsewhere keeps the form, its unsent text and an 'answered elsewhere' notice", () => {
    function List({ gates }: { gates: GateRow[] }) {
      const rows = useRetainedGates(gates);
      return <>{rows.map(({ gate: g, closed, onDismiss }) => <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} closed={closed} onDismiss={onDismiss} />)}</>;
    }
    const other: GateRow = { ...gate, ticket_id: "epic-2" };
    const qc = new QueryClient();
    const ui = (gates: GateRow[]) => <QueryClientProvider client={qc}><MemoryRouter><List gates={gates} /></MemoryRouter></QueryClientProvider>;
    const { rerender } = render(ui([gate, other]));
    fireEvent.change(screen.getAllByTestId("gate-answer")[0], { target: { value: "my unsent ruling" } });
    rerender(ui([])); // live refetch: both gates answered elsewhere
    expect(screen.getAllByTestId("gate-form")).toHaveLength(1); // only the one holding text is kept
    expect(screen.getByTestId("gate-answer")).toHaveValue("my unsent ruling");
    expect(screen.getByTestId("gate-answered-elsewhere")).toBeInTheDocument();
    expect(screen.queryByTestId("gate-submit")).toBeNull();
    fireEvent.click(screen.getByTestId("gate-dismiss"));
    expect(screen.queryByTestId("gate-form")).toBeNull();
  });
});
