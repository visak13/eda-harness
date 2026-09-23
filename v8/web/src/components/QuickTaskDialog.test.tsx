import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { QuickTaskDialog } from "./QuickTaskDialog";

// S-QUICK (c-05fe4d9444): title, words and an engineer-catalog model; ONE submit is ONE POST
// /v1/quick-tasks (create + assign + spawn on the board); success lands on the new story's page.
function mount(spawn = true, onClose = () => {}) {
  server.use(http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true,
    value: { resume_parked: true, resume_closed: false, park: true, spawn, ...(spawn ? {} : { reason: "pool unreachable" }) } })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/epics"]}>
        <Routes>
          <Route path="/epics" element={<QuickTaskDialog open onClose={onClose} />} />
          <Route path="/ticket/:id" element={<div data-testid="landed">ticket page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const opts = (tid: string) => Array.from((screen.getByTestId(tid) as HTMLSelectElement).options).map((o) => o.value);

describe("QuickTaskDialog (S-QUICK)", () => {
  it("offers the engineer catalog, posts one quick-task call with the picked model, and lands on the story", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(http.post("/v1/quick-tasks", async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ ok: true, value: { ticket: { id: "s-q1", kind: "story", title: "Rename" }, seat: "engineer.s-q1" },
        hint: "s-q1 is ready; engineer.s-q1 is starting on it" });
    }));
    mount();
    expect(await screen.findByRole("dialog", { name: "Quick task" })).toBeInTheDocument();
    await waitFor(() => expect(opts("quick-task-model")).toEqual(["claude-opus-5-5", "gpt-6-sol"]));
    expect((screen.getByTestId("quick-task-model") as HTMLSelectElement).value).toBe("claude-opus-5-5");
    expect(screen.getByTestId("quick-task-create")).toBeDisabled();
    fireEvent.change(screen.getByTestId("quick-task-title"), { target: { value: "  Rename the tab  " } });
    fireEvent.change(screen.getByTestId("quick-task-words"), { target: { value: "The Seats tab says Sessions. Call it Seats." } });
    fireEvent.change(screen.getByTestId("quick-task-model"), { target: { value: "gpt-6-sol" } });
    await waitFor(() => expect(screen.getByTestId("quick-task-create")).not.toBeDisabled());
    expect(screen.getByTestId("quick-task-preview")).toHaveTextContent("starts an engineer on GPT-6 Sol and assigns it");
    fireEvent.click(screen.getByTestId("quick-task-create"));
    expect(await screen.findByTestId("landed")).toBeInTheDocument();
    expect(bodies).toEqual([{ title: "Rename the tab", words: "The Seats tab says Sessions. Call it Seats.", model: "gpt-6-sol" }]);
  });

  it("refuses to open a task the pool cannot start, and says why", async () => {
    mount(false);
    fireEvent.change(await screen.findByTestId("quick-task-title"), { target: { value: "T" } });
    fireEvent.change(screen.getByTestId("quick-task-words"), { target: { value: "w" } });
    await waitFor(() => expect(screen.getByTestId("quick-task-preview")).toHaveTextContent("pool unreachable"));
    expect(screen.getByTestId("quick-task-create")).toBeDisabled();
  });

  it("keeps the dialog open with the board's hint and a link when the ticket opened but no engineer started", async () => {
    server.use(http.post("/v1/quick-tasks", () => HttpResponse.json({ ok: true,
      value: { ticket: { id: "s-q2" }, seat: null, spawn_error: "at capacity" },
      hint: "s-q2 is open but no engineer started (at capacity); use Spawn seat on the ticket to retry" })));
    mount();
    fireEvent.change(await screen.findByTestId("quick-task-title"), { target: { value: "T" } });
    fireEvent.change(screen.getByTestId("quick-task-words"), { target: { value: "w" } });
    await waitFor(() => expect(screen.getByTestId("quick-task-create")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("quick-task-create"));
    const banner = await screen.findByTestId("quick-task-stranded");
    expect(banner).toHaveTextContent("no engineer started (at capacity)");
    expect(screen.getByRole("link", { name: "Open the task" })).toHaveAttribute("href", "/ticket/s-q2");
    expect(screen.getByTestId("quick-task-create")).toBeDisabled();  // never a second ticket
  });

  it("shows the board's refusal verbatim", async () => {
    server.use(http.post("/v1/quick-tasks", () => HttpResponse.json({ ok: false, hint: "the owner opens quick tasks" }, { status: 400 })));
    mount();
    fireEvent.change(await screen.findByTestId("quick-task-title"), { target: { value: "T" } });
    fireEvent.change(screen.getByTestId("quick-task-words"), { target: { value: "w" } });
    await waitFor(() => expect(screen.getByTestId("quick-task-create")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("quick-task-create"));
    expect(await screen.findByTestId("quick-task-error")).toHaveTextContent("the owner opens quick tasks");
  });
});
