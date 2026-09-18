import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { NewEpicDialog } from "./NewEpicDialog";

// Human #22: the dialog posts the words verbatim as an epic, spawns the architect when asked, and
// navigates to the new epic's page. Both POST bodies are asserted. Owner m-2d7ef9243d: the seat
// model + effort chosen here ride the epic as tags and the (opt-in, unticked by default) spawn body.
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
  it("creates the epic with the words verbatim, spawns the architect when TICKED, and lands on the epic page", async () => {
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
    fireEvent.change(screen.getByTestId("new-epic-title"), { target: { value: "  Readable board  " } });
    fireEvent.change(screen.getByTestId("new-epic-words"), {
      target: { value: "Make the board readable for a first-time human. No jargon." },
    });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    // creating an epic never forces a spawn: the box starts UNTICKED (owner m-2d7ef9243d)
    expect(screen.getByTestId("new-epic-spawn")).not.toBeChecked();
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent("No seat is woken now");
    expect(screen.getByTestId("new-epic-create")).toHaveTextContent("Create the epic");
    fireEvent.click(screen.getByTestId("new-epic-spawn"));
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent(/verbatim.*Claude at effort medium.*spawns role=architect.*wakes/);
    expect(screen.getByTestId("new-epic-create")).toHaveTextContent("Create and spawn the architect");
    fireEvent.click(screen.getByTestId("new-epic-create"));
    await waitFor(() => expect(spawnBody).not.toBeNull());
    expect(ticketBody).toEqual({
      kind: "epic",
      work_type: "feature",
      title: "Readable board",
      words: "Make the board readable for a first-time human. No jargon.",
      tags: ["seat-model:claude", "seat-effort:medium"],
    });
    expect(spawnBody).toEqual({
      role: "architect",
      participant_id: "architect.epic-new1",
      ticket_id: "epic-new1",
      model: "claude",
      effort: "medium",
    });
    expect(await screen.findByTestId("landed")).toBeInTheDocument();
  });

  it("GPT-6 Astra at effort high: the choice rides the epic tags and the spawn body; Claude hides high", async () => {
    let ticketBody: Record<string, unknown> | null = null;
    let spawnBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/tickets", async ({ request }) => {
        ticketBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: { id: "epic-astra", kind: "epic", title: "t" }, hint: "epic created" });
      }),
      http.post("/v1/sessions/spawn", async ({ request }) => {
        spawnBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: {}, hint: "spawned" });
      }),
    );
    mount();
    await screen.findByRole("dialog", { name: "New epic" });
    // Claude: only low/medium are offered, with the cap explained
    const effortOptions = () => Array.from((screen.getByTestId("new-epic-effort") as HTMLSelectElement).options).map((o) => o.value);
    expect(effortOptions()).toEqual(["low", "medium"]);
    expect(screen.getByTestId("new-epic-effort-cap")).toHaveTextContent(/capped at effort medium/);
    fireEvent.change(screen.getByTestId("new-epic-model"), { target: { value: "astra" } });
    expect(effortOptions()).toEqual(["low", "medium", "high"]);
    expect(screen.queryByTestId("new-epic-effort-cap")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("new-epic-effort"), { target: { value: "high" } });
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent("GPT-6 Astra at effort high");
    // switching back to Claude drops high to medium (the cap)
    fireEvent.change(screen.getByTestId("new-epic-model"), { target: { value: "claude" } });
    expect((screen.getByTestId("new-epic-effort") as HTMLSelectElement).value).toBe("medium");
    fireEvent.change(screen.getByTestId("new-epic-model"), { target: { value: "astra" } });
    fireEvent.change(screen.getByTestId("new-epic-effort"), { target: { value: "high" } });
    fireEvent.change(screen.getByTestId("new-epic-title"), { target: { value: "Astra" } });
    fireEvent.change(screen.getByTestId("new-epic-words"), { target: { value: "Ship it on Astra." } });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("new-epic-spawn"));
    fireEvent.click(screen.getByTestId("new-epic-create"));
    await waitFor(() => expect(spawnBody).not.toBeNull());
    expect((ticketBody as Record<string, unknown> | null)?.tags).toEqual(["seat-model:astra", "seat-effort:high"]);
    expect(spawnBody).toEqual({
      role: "architect",
      participant_id: "architect.epic-astra",
      ticket_id: "epic-astra",
      model: "astra",
      effort: "high",
    });
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
    fireEvent.change(screen.getByTestId("new-epic-title"), { target: { value: "Title" } });
    fireEvent.change(screen.getByTestId("new-epic-words"), { target: { value: "words" } });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    expect(screen.getByTestId("new-epic-spawn")).not.toBeChecked(); // unticked by default: no spawn
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent("No seat is woken");
    fireEvent.click(screen.getByTestId("new-epic-create"));
    expect(await screen.findByTestId("new-epic-error")).toHaveTextContent("owner may not create a epic here");
    expect(spawns).toBe(0);
  });

  it("preserves exact raw words and retries a failed spawn without creating twice", async () => {
    let creates = 0, spawns = 0;
    const raw = "  first line\nsecond line  ";
    server.use(
      http.post("/v1/tickets", async ({ request }) => {
        creates++;
        expect(await request.json()).toMatchObject({ title: "Explicit", words: raw });
        return HttpResponse.json({ ok: true, value: { id: "epic-retry" }, hint: "Created" });
      }),
      http.post("/v1/sessions/spawn", async ({ request }) => {
        spawns++;
        expect(await request.json()).toMatchObject({ ticket_id: "epic-retry" });
        return spawns === 1 ? HttpResponse.json({ ok: false, hint: "Pool offline" }, { status: 503 }) : HttpResponse.json({ ok: true, value: {} });
      }),
    );
    mount();
    expect(screen.getByTestId("new-epic-title")).toHaveFocus();
    fireEvent.change(screen.getByTestId("new-epic-title"), { target: { value: " Explicit " } });
    fireEvent.change(screen.getByTestId("new-epic-words"), { target: { value: raw } });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("new-epic-spawn"));
    fireEvent.click(screen.getByTestId("new-epic-create"));
    expect(await screen.findByText(/The architect could not start/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open existing epic" })).toHaveAttribute("href", "/epic/epic-retry");
    fireEvent.click(screen.getByRole("button", { name: "Retry architect" }));
    expect(await screen.findByTestId("landed")).toBeInTheDocument();
    expect(creates).toBe(1); expect(spawns).toBe(2);
  });

  it("when the pool cannot spawn, the checkbox is disabled and says why", async () => {
    mount({ resume_parked: false, resume_closed: false, park: false, spawn: false, reason: "pool offline" } as never);
    await screen.findByRole("dialog", { name: "New epic" });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).toBeDisabled());
    expect(screen.getByText(/pool offline/)).toBeInTheDocument();
  });
});
