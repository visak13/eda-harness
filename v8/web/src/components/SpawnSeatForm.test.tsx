import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { SpawnSeatForm } from "./SpawnSeatForm";
import { SeatsPage } from "../pages/Seats";

// S-ROLES c-455bd9042c: "Spawn seat" offers every catalog role, the model list is THAT role's catalog,
// and an engineer spawned on a story becomes its assignee (assign:true rides the spawn body).
function mount(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}
const opts = (id: string) => Array.from((screen.getByTestId(id) as HTMLSelectElement).options).map((o) => o.value);

describe("SpawnSeatForm (S-ROLES)", () => {
  it("offers every catalog role, each with its own models, and spawns an engineer as the story's assignee", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(http.post("/v1/sessions/spawn", async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ ok: true, value: { assignee: "engineer.s-1" }, hint: "engineer.s-1 spawned" });
    }));
    mount(<SpawnSeatForm />);
    await waitFor(() => expect(opts("spawn-seat-role")).toEqual(["architect", "engineer", "qa", "adversary", "sme"]));
    expect((screen.getByTestId("spawn-seat-role") as HTMLSelectElement).value).toBe("engineer");
    expect(opts("spawn-seat-model")).toEqual(["claude-opus-5-5", "gpt-6-sol"]);
    expect(screen.getByTestId("spawn-seat-assign")).toBeChecked();
    expect(screen.getByTestId("spawn-seat-submit")).toBeDisabled();
    fireEvent.change(screen.getByTestId("spawn-seat-ticket"), { target: { value: " s-1 " } });
    fireEvent.change(screen.getByTestId("spawn-seat-model"), { target: { value: "gpt-6-sol" } });
    expect(screen.getByTestId("spawn-seat-preview")).toHaveTextContent("Starts engineer.s-1 on GPT-6 Sol and assigns s-1 to it.");
    fireEvent.click(screen.getByTestId("spawn-seat-submit"));
    expect(await screen.findByTestId("spawn-seat-done")).toHaveTextContent("engineer.s-1 spawned");
    expect(body).toEqual({ role: "engineer", participant_id: "engineer.s-1", ticket_id: "s-1", model: "gpt-6-sol", assign: true });
  });

  it("a checker role is never made the assignee by default, and switching role resets the model to its default", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(http.post("/v1/sessions/spawn", async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ ok: true, value: {}, hint: "" });
    }));
    mount(<SpawnSeatForm />);
    await waitFor(() => expect(opts("spawn-seat-role")).toContain("adversary"));
    fireEvent.change(screen.getByTestId("spawn-seat-model"), { target: { value: "gpt-6-sol" } });
    fireEvent.change(screen.getByTestId("spawn-seat-role"), { target: { value: "adversary" } });
    expect(opts("spawn-seat-model")).toEqual(["gpt-6-astra"]);
    expect((screen.getByTestId("spawn-seat-model") as HTMLSelectElement).value).toBe("gpt-6-astra");
    expect(screen.getByTestId("spawn-seat-assign")).not.toBeChecked();
    fireEvent.change(screen.getByTestId("spawn-seat-ticket"), { target: { value: "epic-9" } });
    fireEvent.click(screen.getByTestId("spawn-seat-submit"));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toEqual({ role: "adversary", participant_id: "adversary.epic-9", ticket_id: "epic-9", model: "gpt-6-astra" });
  });

  it("shows the board's refusal verbatim", async () => {
    server.use(http.post("/v1/sessions/spawn", () =>
      HttpResponse.json({ ok: false, hint: "pool is down (no response since 10:00)" }, { status: 503 })));
    mount(<SpawnSeatForm />);
    await waitFor(() => expect(opts("spawn-seat-role")).toContain("engineer"));
    fireEvent.change(screen.getByTestId("spawn-seat-ticket"), { target: { value: "s-2" } });
    fireEvent.click(screen.getByTestId("spawn-seat-submit"));
    expect(await screen.findByTestId("spawn-seat-error")).toHaveTextContent("pool is down (no response since 10:00)");
  });

  it("a failed catalog read says Spawn seat is unavailable", async () => {
    server.use(http.get("/v1/models", () => HttpResponse.json({ ok: false, hint: "x" }, { status: 500 })));
    mount(<SpawnSeatForm />);
    expect(await screen.findByTestId("spawn-seat-unavailable")).toBeInTheDocument();
  });

  it("the Seats page shows it only when the pool can spawn", async () => {
    const seats = { seats: [], people: [] };
    server.use(
      http.get("/v1/seats", () => HttpResponse.json({ ok: true, value: seats })),
      http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: { resume_parked: false, resume_closed: false, park: false, spawn: true } })),
    );
    mount(<SeatsPage />);
    expect(await screen.findByTestId("spawn-seat-form")).toBeInTheDocument();
  });

  it("the Seats page hides it when the pool cannot spawn", async () => {
    server.use(
      http.get("/v1/seats", () => HttpResponse.json({ ok: true, value: { seats: [], people: [] } })),
      http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: { resume_parked: false, resume_closed: false, park: false, spawn: false, reason: "pool down" } })),
    );
    mount(<SeatsPage />);
    await screen.findByText("No seats in this group.");
    expect(screen.queryByTestId("spawn-seat-form")).not.toBeInTheDocument();
  });
});
