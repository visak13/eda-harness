import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { CommandPalette, rowFor } from "./CommandPalette";

// Find / command palette (human defect #12, m-783e725c2f): Ctrl-K opens it over /v1/find, rows are
// grouped by type with title + epic, Enter opens the highlighted row, Esc closes.

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.hash}</div>;
}

function mount(open = true, onClose = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/me"]}>
        <Where />
        <Routes>
          <Route path="*" element={<CommandPalette open={open} onClose={onClose} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(
    http.get("/v1/find", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      if (q !== "folio") return HttpResponse.json({ ok: true, value: [] });
      return HttpResponse.json({
        ok: true,
        value: [
          { type: "ticket", id: "epic-1", score: 1, snippet: "[Folio] redesign", title: "Folio redesign", epic_id: "epic-1" },
          { type: "ticket", id: "s-2", score: 0.9, snippet: "", title: "Folio shell story", epic_id: "epic-1", status: "in_progress" },
          { type: "message", id: "m-3", score: 0.5, snippet: "ship the [folio] sheet", ticket_id: "s-2", epic_id: "epic-1" },
          { type: "doc", id: "design-4", score: 0.4, snippet: "", title: "Folio design", epic_id: "epic-1" },
        ],
      });
    }),
    http.get("/v1/epics/summary", () =>
      HttpResponse.json({ ok: true, value: [{ id: "epic-1", title: "Folio redesign", status: "in_progress", created_at: "", criteria: { passed: 0, total: 0 }, open_gates: 0, waiting_reason: { reason: "", presence: null }, assigned_seats: [] }] }),
    ),
    http.get("/v1/seats", () =>
      HttpResponse.json({ ok: true, value: { seats: [{ id: "engineer.s-2", handle: "engineer.s-2", role: "engineer", state: "alive", ticket_id: "s-2", ticket_title: "Folio shell story", last_output_at: null, presence_stale_since: null, reason: "", latest_status: null }], people: [] } }),
    ),
  );
});

describe("rowFor", () => {
  const titles = (id: string | undefined) => (id === "epic-1" ? "Folio redesign" : null);
  it("routes every hit type to its page, messages and criteria anchored on their thread", () => {
    expect(rowFor({ type: "ticket", id: "epic-1", score: 1, snippet: "", title: "E", epic_id: "epic-1" }, titles)?.to).toBe("/epic/epic-1");
    expect(rowFor({ type: "ticket", id: "s-2", score: 1, snippet: "", title: "S", epic_id: "epic-1" }, titles)?.epic).toBe("Folio redesign");
    expect(rowFor({ type: "message", id: "m-3", score: 1, snippet: "x", ticket_id: "s-2" }, titles)?.to).toBe("/ticket/s-2#m-3");
    expect(rowFor({ type: "criterion", id: "c-9", score: 1, snippet: "x", ticket_id: "s-2" }, titles)?.to).toBe("/ticket/s-2#c-9");
    expect(rowFor({ type: "doc", id: "design-4", score: 1, snippet: "", title: "D" }, titles)?.to).toBe("/doc/design-4");
    expect(rowFor({ type: "message", id: "m-0", score: 1, snippet: "orphan" }, titles)).toBeNull();
  });
});

describe("CommandPalette", () => {
  it("groups hits by type with title + epic, adds seats by handle, Enter opens the highlighted row", async () => {
    mount();
    const input = screen.getByTestId("find-input") as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "folio" } });
    await waitFor(() => expect(screen.getAllByTestId("find-row").length).toBeGreaterThanOrEqual(4));
    const rows = screen.getAllByTestId("find-row");
    expect(rows[0]).toHaveAttribute("data-group", "Epics");
    expect(rows[0]).toHaveTextContent("Folio redesign");
    const ticketRow = rows.find((r) => r.getAttribute("data-group") === "Tickets")!;
    expect(ticketRow).toHaveTextContent("Folio shell story");
    expect(ticketRow).toHaveTextContent("Folio redesign"); // its epic
    expect(rows.some((r) => r.getAttribute("data-group") === "Seats" && r.textContent?.includes("engineer.s-2"))).toBe(true);
    expect(rows.some((r) => r.getAttribute("data-group") === "Messages" && r.textContent?.includes("ship the folio sheet"))).toBe(true);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/ticket/s-2"));
  });

  it("says so when nothing matches, and Esc closes", async () => {
    let closed = 0;
    mount(true, () => closed++);
    const input = screen.getByTestId("find-input");
    fireEvent.change(input, { target: { value: "zzzz" } });
    await screen.findByTestId("find-empty");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(closed).toBe(1);
  });
});

// Adversary round 2 #11/#12 (2026-09-10): groups render in ranked order (the order ↑/↓ walk), a
// focused result button activates itself, and Enter during the debounce never opens the previous
// query's result.
describe("CommandPalette round 2", () => {
  it("#11 DOM order follows the ranking and the highlighted row is the first in the DOM", async () => {
    server.use(
      http.get("/v1/find", () =>
        HttpResponse.json({
          ok: true,
          value: [
            { type: "message", id: "m-9", score: 1, snippet: "top ranked message", ticket_id: "s-2", epic_id: "epic-1" },
            { type: "ticket", id: "s-2", score: 0.5, snippet: "", title: "Folio shell story", epic_id: "epic-1" },
          ],
        }),
      ),
    );
    mount();
    const input = screen.getByTestId("find-input");
    fireEvent.change(input, { target: { value: "folio" } });
    await waitFor(() => expect(screen.getAllByTestId("find-row").some((r) => r.getAttribute("data-group") === "Messages")).toBe(true));
    const rows = screen.getAllByTestId("find-row");
    expect(rows[0]).toHaveAttribute("data-group", "Messages");
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
    // Tab onto the second button and press Enter there: the button itself activates (no dialog Enter).
    rows[1].focus();
    fireEvent.keyDown(rows[1], { key: "Enter" });
    expect(screen.getByTestId("where")).toHaveTextContent("/me"); // dialog did not navigate on its own
    fireEvent.click(rows[1]);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/ticket/s-2"));
  });

  it("#12 Enter during the debounce does not open the previous query's result", async () => {
    mount();
    const input = screen.getByTestId("find-input");
    fireEvent.change(input, { target: { value: "folio" } });
    await waitFor(() => expect(screen.getAllByTestId("find-row").length).toBeGreaterThan(0));
    fireEvent.change(input, { target: { value: "zzzz" } });
    fireEvent.keyDown(input, { key: "Enter" }); // within the 120ms debounce
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByTestId("where")).toHaveTextContent("/me");
  });
});

// Coverage pass (c-7c51c6b69b): the row fallbacks (no title → snippet → id; unknown epic id; an
// orphan criterion; an unknown hit type), the keyboard edges (ArrowUp wrap, arrows with no rows,
// the Tab focus trap), a seats endpoint that fails, and a title-matched epic FTS ranked out.
describe("rowFor fallbacks", () => {
  const titles = (id: string | undefined) => (id === "epic-1" ? "Folio redesign" : null);
  it("falls back title → snippet → id and names an unknown epic by its id", () => {
    const t = rowFor({ type: "ticket", id: "s-7", score: 1, snippet: "[Bare] ticket", epic_id: "epic-zz" }, titles)!;
    expect(t.title).toBe("Bare ticket");
    expect(t.epic).toBe("epic-zz");
    expect(t.group).toBe("Tickets");
    const noEpic = rowFor({ type: "ticket", id: "s-8", score: 1, snippet: "", title: "T" }, titles)!;
    expect(noEpic.epic).toBeNull();
    const d = rowFor({ type: "doc", id: "report-1", score: 1, snippet: "[report] body" }, titles)!;
    expect(d.title).toBe("report body");
    expect(d.epic).toBeNull();
    const m = rowFor({ type: "message", id: "m-5", score: 1, snippet: "", ticket_id: "epic-1" }, titles)!;
    expect(m.title).toBe("m-5");
    expect(m.to).toBe("/epic/epic-1#m-5");
    const c = rowFor({ type: "criterion", id: "c-5", score: 1, snippet: "", ticket_id: "s-2" }, titles)!;
    expect(c.title).toBe("c-5");
    expect(rowFor({ type: "criterion", id: "c-6", score: 1, snippet: "orphan" }, titles)).toBeNull();
    expect(rowFor({ type: "weird" as unknown as "doc", id: "x", score: 1, snippet: "" }, titles)).toBeNull();
  });
});

describe("CommandPalette keyboard + data edges", () => {
  it("renders nothing while closed", () => {
    mount(false);
    expect(screen.queryByTestId("find-dialog")).toBeNull();
  });

  it("ArrowUp wraps to the last row, arrows with no rows are harmless, and a seat with no ticket title names its ticket id", async () => {
    server.use(
      http.get("/v1/seats", () =>
        HttpResponse.json({ ok: true, value: { seats: [{ id: "qa.folio", handle: "qa.folio", role: "qa", state: "alive", ticket_id: "s-9", ticket_title: null, last_output_at: null, presence_stale_since: null, reason: "", latest_status: null }], people: [] } }),
      ),
    );
    mount();
    const input = screen.getByTestId("find-input");
    // no rows yet: the arrows keep index at 0 without throwing
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.change(input, { target: { value: "folio" } });
    // 4 ranked hits + the one seat matched by handle (seats resolve before the hits: wait for all)
    await waitFor(() => expect(screen.getAllByTestId("find-row").length).toBe(5));
    const rows = screen.getAllByTestId("find-row");
    const seat = rows.find((r) => r.getAttribute("data-group") === "Seats")!;
    expect(seat).toHaveTextContent("s-9");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(rows[rows.length - 1]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", rows[rows.length - 1].id);
  });

  it("traps Tab inside the dialog: Shift+Tab from the input lands on the last row, Tab from the last row returns to the input", async () => {
    mount();
    const input = screen.getByTestId("find-input");
    fireEvent.change(input, { target: { value: "folio" } });
    // seats/epics resolve before the find hits: wait for the full ranked set (4 hits + 1 seat)
    await waitFor(() => expect(screen.getAllByTestId("find-row").length).toBe(5));
    const rows = screen.getAllByTestId("find-row");
    const last = rows[rows.length - 1];
    input.focus();
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(input);
    // Tab from a middle row is left to the browser (no wrap)
    rows[0].focus();
    fireEvent.keyDown(rows[0], { key: "Tab" });
    expect(document.activeElement).toBe(rows[0]);
    // any other key is ignored by the dialog handler
    fireEvent.keyDown(input, { key: "a" });
  });

  it("still lists a title-matched epic when FTS ranked it out, and survives a failed seats call", async () => {
    server.use(
      http.get("/v1/find", () => HttpResponse.json({ ok: true, value: [] })),
      http.get("/v1/seats", () => HttpResponse.json({ ok: false, error: "down" }, { status: 500 })),
    );
    mount();
    const input = screen.getByTestId("find-input");
    fireEvent.change(input, { target: { value: "redesign" } });
    await waitFor(() => expect(screen.getAllByTestId("find-row").length).toBe(1));
    const row = screen.getByTestId("find-row");
    expect(row).toHaveAttribute("data-group", "Epics");
    expect(row).toHaveTextContent("Folio redesign");
    // a hit whose epic_id is not in the summary falls back to the id; the scrim click closes
    fireEvent.click(row);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/epic/epic-1"));
  });

  it("names an unknown epic by id and closes on the scrim", async () => {
    let closed = 0;
    server.use(
      http.get("/v1/find", () =>
        HttpResponse.json({ ok: true, value: [{ type: "ticket", id: "s-3", score: 1, snippet: "", title: "Stray story", epic_id: "epic-gone" }] }),
      ),
    );
    mount(true, () => closed++);
    const input = screen.getByTestId("find-input");
    fireEvent.change(input, { target: { value: "stray" } });
    await waitFor(() => expect(screen.getAllByTestId("find-row").length).toBe(1));
    expect(screen.getByTestId("find-row")).toHaveTextContent("epic-gone");
    fireEvent.mouseEnter(screen.getByTestId("find-row"));
    fireEvent.click(screen.getByTestId("find-scrim"));
    expect(closed).toBe(1);
  });
});
