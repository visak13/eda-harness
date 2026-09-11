import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { NewEpicDialog } from "./NewEpicDialog";

// Human #22: the dialog posts the words verbatim as an epic, spawns the architect when asked, and
// navigates to the new epic's page. Both POST bodies are asserted.
function mount(caps = { resume_parked: true, resume_closed: false, park: true, spawn: true }) {
  server.use(http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: caps })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/me"]}>
        <Routes>
          <Route path="/me" element={<NewEpicDialog open onClose={() => {}} />} />
          <Route path="/epic/:id" element={<div data-testid="landed">epic page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewEpicDialog (human #22)", () => {
  it("creates the epic with the words verbatim, spawns the architect, and lands on the epic page", async () => {
    let ticketBody: Record<string, unknown> | null = null;
    let spawnBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/tickets", async ({ request }) => {
        ticketBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: { id: "epic-new1", kind: "epic", title: "Make the board" }, hint: "epic created" });
      }),
      http.post("/v1/sessions/spawn", async ({ request }) => {
        spawnBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: {}, hint: "architect.epic-new1 spawned" });
      }),
    );
    mount();
    const dialog = await screen.findByRole("dialog", { name: "New epic" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("new-epic-create")).toBeDisabled();
    fireEvent.change(screen.getByTestId("new-epic-words"), {
      target: { value: "Make the board readable for a first-time human. No jargon." },
    });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent(/verbatim.*spawns role=architect.*wakes/);
    fireEvent.click(screen.getByTestId("new-epic-create"));
    await waitFor(() => expect(spawnBody).not.toBeNull());
    expect(ticketBody).toEqual({
      kind: "epic",
      work_type: "feature",
      title: "Make the board readable for a first-time human. No jargon.",
      words: "Make the board readable for a first-time human. No jargon.",
    });
    expect(spawnBody).toEqual({ role: "architect", participant_id: "architect.epic-new1", ticket_id: "epic-new1" });
    expect(await screen.findByTestId("landed")).toBeInTheDocument();
  });

  it("without spawning: one POST, the preview says no seat is woken; a refused create shows the hint", async () => {
    let spawns = 0;
    server.use(
      http.post("/v1/tickets", () => HttpResponse.json({ ok: false, hint: "owner may not create a epic here" }, { status: 403 })),
      http.post("/v1/sessions/spawn", () => {
        spawns += 1;
        return HttpResponse.json({ ok: true, value: {} });
      }),
    );
    mount();
    await screen.findByRole("dialog", { name: "New epic" });
    fireEvent.change(screen.getByTestId("new-epic-words"), { target: { value: "words" } });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("new-epic-spawn"));
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent("No seat is woken");
    fireEvent.click(screen.getByTestId("new-epic-create"));
    expect(await screen.findByTestId("new-epic-error")).toHaveTextContent("owner may not create a epic here");
    expect(spawns).toBe(0);
  });

  it("when the pool cannot spawn, the checkbox is disabled and says why", async () => {
    mount({ resume_parked: false, resume_closed: false, park: false, spawn: false, reason: "pool offline" } as never);
    await screen.findByRole("dialog", { name: "New epic" });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).toBeDisabled());
    expect(screen.getByText(/pool offline/)).toBeInTheDocument();
  });
});
