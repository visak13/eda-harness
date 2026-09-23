import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { NewEpicDialog } from "./NewEpicDialog";

// Human #22: the dialog posts the words verbatim as an epic, spawns the architect when asked, and
// navigates to the new epic's page. Both POST bodies are asserted. Owner m-2d7ef9243d: the seat
// model + effort chosen here ride the epic as tags and the (opt-in, unticked by default) spawn body.
function mount(caps = { resume_parked: true, resume_closed: false, park: true, spawn: true }, onClose = () => {}) {
  server.use(http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: caps })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/me"]}>
        <Routes>
          <Route path="/me" element={<NewEpicDialog open onClose={onClose} />} />
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
    expect(screen.getByTestId("new-epic-preview")).toHaveTextContent(/verbatim.*model and effort chosen above.*spawns role=architect.*wakes/);
    expect(screen.getByTestId("new-epic-create")).toHaveTextContent("Create and spawn the architect");
    fireEvent.click(screen.getByTestId("new-epic-create"));
    await waitFor(() => expect(spawnBody).not.toBeNull());
    expect(ticketBody).toEqual({
      kind: "epic",
      work_type: "feature",
      title: "Readable board",
      words: "Make the board readable for a first-time human. No jargon.",
      // every catalog role prefilled with its default (S-ROLES)
      tags: ["model:architect=claude-fable-5-1", "model:engineer=claude-opus-5-5", "model:qa=claude-fable-5-1",
             "model:adversary=gpt-6-astra", "model:sme=claude-opus-5-5",
             "seat-effort:architect=medium", "seat-effort:engineer=medium", "seat-effort:qa=medium",
             "seat-effort:adversary=medium", "seat-effort:sme=medium"],
    });
    expect(spawnBody).toEqual({
      role: "architect",
      participant_id: "architect.epic-new1",
      ticket_id: "epic-new1",
      model: "claude-fable-5-1",
      effort: "medium",
    });
    expect(await screen.findByTestId("landed")).toBeInTheDocument();
  });

  it("one model select per role, prefilled from the catalog; the picks ride the epic tags and the architect spawn", async () => {
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
    const sel = (r: string) => screen.getByTestId(`new-epic-model-${r}`) as HTMLSelectElement;
    await waitFor(() => expect(sel("architect")).toBeInTheDocument());
    const opts = (r: string) => Array.from(sel(r).options).map((o) => o.value);
    expect(opts("architect")).toEqual(["claude-fable-5-1", "gpt-6-astra"]);
    expect(opts("engineer")).toEqual(["claude-opus-5-5", "gpt-6-sol"]);
    expect(opts("adversary")).toEqual(["gpt-6-astra"]);
    expect(["architect", "engineer", "qa", "adversary", "sme"].map((r) => sel(r).value)).toEqual(
      ["claude-fable-5-1", "claude-opus-5-5", "claude-fable-5-1", "gpt-6-astra", "claude-opus-5-5"]);
    expect(Array.from(sel("architect").options).map((o) => o.textContent)).toEqual(["Claude Fable 5.1", "GPT-6 Astra"]);
    fireEvent.change(sel("architect"), { target: { value: "gpt-6-astra" } });
    fireEvent.change(sel("engineer"), { target: { value: "gpt-6-sol" } });
    // S-UI: effort per role beside each model; the old global dropdown is gone
    expect(screen.queryByTestId("new-epic-effort")).toBeNull();
    const eff = (r: string) => screen.getByTestId(`new-epic-effort-${r}`) as HTMLSelectElement;
    expect(["architect", "engineer", "qa", "adversary", "sme"].map((r) => eff(r).value)).toEqual(Array(5).fill("medium"));
    // a Claude row cannot pick high and says so; a GPT row can
    const high = (r: string) => Array.from(eff(r).options).find((o) => o.value === "high")!;
    expect(high("qa").disabled).toBe(true);
    expect(screen.getByTestId("new-epic-cap-qa")).toHaveTextContent("Claude: medium max");
    expect(high("architect").disabled).toBe(false);
    expect(screen.getByTestId("new-epic-cap-architect")).toHaveTextContent("");
    fireEvent.change(eff("architect"), { target: { value: "high" } });
    fireEvent.change(eff("adversary"), { target: { value: "low" } });
    expect(screen.getByTestId("new-epic-effort-cap")).toHaveTextContent(/capped at effort medium/);
    // a provider glyph sits beside each model, a role glyph beside each role
    expect(screen.getByTestId("new-epic-row-architect").querySelector("[data-provider-icon='gpt']")).not.toBeNull();
    expect(screen.getByTestId("new-epic-row-qa").querySelector("[data-provider-icon='claude']")).not.toBeNull();
    expect(screen.getByTestId("new-epic-row-sme").querySelector("[data-role-icon='sme']")).not.toBeNull();
    fireEvent.change(screen.getByTestId("new-epic-title"), { target: { value: "Astra" } });
    fireEvent.change(screen.getByTestId("new-epic-words"), { target: { value: "Ship it on Astra." } });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("new-epic-spawn"));
    fireEvent.click(screen.getByTestId("new-epic-create"));
    await waitFor(() => expect(spawnBody).not.toBeNull());
    expect((ticketBody as Record<string, unknown> | null)?.tags).toEqual([
      "model:architect=gpt-6-astra", "model:engineer=gpt-6-sol", "model:qa=claude-fable-5-1",
      "model:adversary=gpt-6-astra", "model:sme=claude-opus-5-5",
      "seat-effort:architect=high", "seat-effort:engineer=medium", "seat-effort:qa=medium",
      "seat-effort:adversary=low", "seat-effort:sme=medium"]);
    expect(spawnBody).toEqual({
      role: "architect",
      participant_id: "architect.epic-astra",
      ticket_id: "epic-astra",
      model: "gpt-6-astra",
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

  it("blocks duplicate pending submits and dismissal, then keeps failed drafts", async () => {
    let finish!: () => void;
    const wait = new Promise<void>((resolve) => { finish = resolve; });
    let posts = 0;
    server.use(http.post("/v1/tickets", async () => { posts++; await wait; return HttpResponse.json({ ok: false, hint: "Create failed" }, { status: 503 }); }));
    const close = vi.fn();
    mount(undefined, close);
    fireEvent.change(screen.getByTestId("new-epic-title"), { target: { value: "Title" } });
    fireEvent.change(screen.getByTestId("new-epic-words"), { target: { value: "  raw request  " } });
    fireEvent.submit(screen.getByTestId("new-epic-dialog"));
    fireEvent.submit(screen.getByTestId("new-epic-dialog"));
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(screen.getByTestId("new-epic-scrim"));
    await waitFor(() => expect(posts).toBe(1));
    expect(close).not.toHaveBeenCalled();
    finish();
    await screen.findByText("Create failed");
    expect(screen.getByTestId("new-epic-title")).toHaveValue("Title");
    expect(screen.getByTestId("new-epic-words")).toHaveValue("  raw request  ");
  });

  it("when the pool cannot spawn, the checkbox is disabled and says why", async () => {
    mount({ resume_parked: false, resume_closed: false, park: false, spawn: false, reason: "pool offline" } as never);
    await screen.findByRole("dialog", { name: "New epic" });
    await waitFor(() => expect(screen.getByTestId("new-epic-spawn")).toBeDisabled());
    expect(screen.getByText(/pool offline/)).toBeInTheDocument();
  });
});
