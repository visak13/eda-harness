import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { SeatRow, SeatsView, PoolCapabilities } from "../api/types";
import { SeatsPage } from "./Seats";

const now = Date.now();
const ago = (ms: number) => new Date(now - ms).toISOString();

const alive: SeatRow = {
  id: "engineer.s-eng", handle: "engineer.s-eng", role: "engineer", state: "alive",
  ticket_id: "s-eng", ticket_title: "Read documents and rule in place", last_output_at: ago(20_000),
  presence_stale_since: null, reason: "",
  latest_status: { text: "Owner checks are ready for review.", status: "reviewed", role: "engineer", at: ago(20_000) },
};
const staleSeat: SeatRow = {
  id: "sme.s-sme", handle: "sme.s-sme", role: "sme", state: "alive",
  ticket_id: "s-sme", ticket_title: "Craft doc", last_output_at: ago(5 * 60_000),
  presence_stale_since: null, reason: "", latest_status: null,
};
const parked: SeatRow = {
  id: "reviewer.s-rev", handle: "reviewer.s-rev", role: "reviewer", state: "parked",
  ticket_id: "s-rev", ticket_title: "Review the Folio shell", last_output_at: ago(3 * 60_000),
  presence_stale_since: null, reason: "waiting on evidence",
  latest_status: { text: "Waiting for the engineer's evidence.", status: "handed_off", role: "reviewer", at: ago(3 * 60_000) },
};
const closed: SeatRow = {
  id: "qa.s-qa", handle: "qa.s-qa", role: "qa", state: "dead",
  ticket_id: "s-qa", ticket_title: "Verify session resume", last_output_at: ago(26 * 3600_000),
  presence_stale_since: null, reason: "closed by self: work completed; session saved",
  latest_status: { text: "Resume checks completed.", status: "done", role: "qa", at: ago(26 * 3600_000) },
};

// A remote seat with no mirrored session — state null. It is NOT closed; availability is unknown.
const remote: SeatRow = {
  id: "architect.epic-x", handle: "architect.epic-x", role: "architect", state: null,
  ticket_id: "epic-x", ticket_title: "Coordinate the epic", last_output_at: null,
  presence_stale_since: null, reason: "", latest_status: null,
};

const VIEW: SeatsView = {
  seats: [alive, staleSeat, parked, closed, remote],
  people: [{ id: "owner", handle: "owner", role: "owner" }],
};

function mockBoard(caps: PoolCapabilities) {
  server.use(
    http.get("/v1/seats", () => HttpResponse.json({ ok: true, value: VIEW })),
    http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: caps })),
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
    http.post("/v1/messages/resolve", () =>
      HttpResponse.json({ ok: true, value: { to: "engineer.s-eng", wakes: [], plan: [], note: "" } }),
    ),
  );
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SeatsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const CAPS_YES: PoolCapabilities = { resume_parked: true, resume_closed: true, park: true, spawn: true };
const CAPS_NO: PoolCapabilities = { resume_parked: true, resume_closed: false, park: true, spawn: true };
const CAPS_NO_PARKED: PoolCapabilities = { resume_parked: false, resume_closed: false, park: true, spawn: true };

/** Board where the capabilities endpoint never answers — the client must ASSUME NOTHING. */
function mockBoardCapsDown() {
  server.use(
    http.get("/v1/seats", () => HttpResponse.json({ ok: true, value: VIEW })),
    http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: false, error: { code: "down" } }, { status: 500 })),
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
  );
}

function rowFor(seatId: string): HTMLElement {
  const row = document.querySelector(`[data-seat="${seatId}"]`);
  if (!row) throw new Error(`no seat row for ${seatId}`);
  return row as HTMLElement;
}

beforeEach(() => mockBoard(CAPS_NO));

describe("Seats presence rules (RTL)", () => {
  it("a fresh alive seat reads Working with its ticket and its latest status", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    const r = rowFor("engineer.s-eng");
    expect(within(r).getByTestId("seat-state")).toHaveTextContent("Working");
    expect(within(r).getByText("Read documents and rule in place")).toBeInTheDocument();
    expect(within(r).getByTestId("latest-status")).toHaveTextContent("Owner checks are ready for review.");
  });

  it("an alive seat silent for over a minute reads 'Presence not refreshed'", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    expect(within(rowFor("sme.s-sme")).getByTestId("seat-state")).toHaveTextContent("Presence not refreshed");
  });

  it("a seat with no record_status shows 'Last work update unavailable' and never a progress number", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    const r = rowFor("sme.s-sme");
    expect(within(r).getByTestId("no-status")).toHaveTextContent("Last work update unavailable");
    expect(within(r).queryByTestId("latest-status")).not.toBeInTheDocument();
  });

  it("a closed seat shows its recorded reason verbatim", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    expect(within(rowFor("qa.s-qa")).getByTestId("seat-state")).toHaveTextContent("Closed");
    expect(rowFor("qa.s-qa")).toHaveTextContent("closed by self: work completed; session saved");
  });

  it("the human owner appears in the People block with 'Owner' and no seat state", async () => {
    mount();
    const person = await screen.findByTestId("person-row");
    expect(person).toHaveTextContent("owner");
    expect(person).toHaveTextContent("Owner");
    expect(within(person).queryByTestId("seat-state")).not.toBeInTheDocument();
  });
});

describe("Seats Resume gating (both pool answers)", () => {
  it("resume_closed=false: the closed seat offers no Resume, explaining a fresh seat instead", async () => {
    mockBoard(CAPS_NO);
    mount();
    await screen.findByText("engineer.s-eng");
    const r = rowFor("qa.s-qa");
    expect(within(r).queryByTestId("seat-resume")).not.toBeInTheDocument();
    expect(within(r).getByTestId("no-resume-note")).toHaveTextContent("spawn a fresh seat");
  });

  it("resume_closed=true: the closed seat offers Resume", async () => {
    mockBoard(CAPS_YES);
    mount();
    await screen.findByText("engineer.s-eng");
    // caps is a separate query; wait for resume-from-closed to be reported before asserting.
    await waitFor(() => expect(within(rowFor("qa.s-qa")).getByTestId("seat-resume")).toBeInTheDocument());
  });

  it("resume_parked=true: a parked seat offers Resume", async () => {
    mockBoard(CAPS_YES);
    mount();
    await screen.findByText("engineer.s-eng");
    await waitFor(() => expect(within(rowFor("reviewer.s-rev")).getByTestId("seat-resume")).toBeInTheDocument());
  });

  it("resume_parked=false: a parked seat offers NO Resume (never assumed)", async () => {
    mockBoard(CAPS_NO_PARKED);
    mount();
    await screen.findByText("engineer.s-eng");
    expect(within(rowFor("reviewer.s-rev")).queryByTestId("seat-resume")).not.toBeInTheDocument();
  });

  it("capabilities unavailable: a parked seat offers NO Resume until the pool reports it can", async () => {
    mockBoardCapsDown();
    mount();
    await screen.findByText("engineer.s-eng");
    expect(within(rowFor("reviewer.s-rev")).queryByTestId("seat-resume")).not.toBeInTheDocument();
  });
});

describe("Seats: a remote seat (no mirrored session) is unknown, never closed", () => {
  it("reads 'Availability unknown', not Closed, and carries no closed/spawn note", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    const r = rowFor("architect.epic-x");
    expect(within(r).getByTestId("seat-state")).toHaveTextContent("Availability unknown");
    expect(within(r).queryByTestId("no-resume-note")).not.toBeInTheDocument();
    expect(r).not.toHaveTextContent("Closed");
  });

  it("its message note says availability is unknown — not that it is closed, not that it wakes", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    fireEvent.click(within(rowFor("architect.epic-x")).getByTestId("seat-message"));
    const note = await screen.findByTestId("seat-delivery-note");
    expect(note).toHaveTextContent("availability is unknown");
    expect(note).not.toHaveTextContent("closed");
    expect(note).not.toHaveTextContent(/wake .* now/i);
  });

  it("the Closed tab holds only board-recorded dead seats, not the remote one", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    fireEvent.click(screen.getByRole("tab", { name: /Closed/ }));
    expect(rowFor("qa.s-qa")).toBeInTheDocument();
    expect(document.querySelector('[data-seat="architect.epic-x"]')).toBeNull();
  });
});

describe("Seats Message action", () => {
  it("opens the composer with the seat as recipient and a wake note", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    fireEvent.click(within(rowFor("engineer.s-eng")).getByTestId("seat-message"));
    await waitFor(() => expect(screen.getByTestId("composer")).toBeInTheDocument());
    expect(screen.getByTestId("seat-delivery-note")).toHaveTextContent("wake engineer.s-eng");
  });

  it("a closed seat's message note says it waits on the ticket, not that it wakes anyone", async () => {
    mount();
    await screen.findByText("engineer.s-eng");
    fireEvent.click(within(rowFor("qa.s-qa")).getByTestId("seat-message"));
    const note = await screen.findByTestId("seat-delivery-note");
    expect(note).toHaveTextContent("waits on its ticket");
    expect(note).not.toHaveTextContent(/wake .* now/i);
  });
});

describe("Seats — arriving from an Epic page 'Message' (human #24)", () => {
  it("/seats?message=<seat>#<seat> opens that seat's row with its composer showing", async () => {
    mockBoard(CAPS_NO);
    server.use(http.get("/v1/messages", () => HttpResponse.json({ ok: true, value: [] }))); // the open row's thread
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/seats?message=engineer.s-eng#engineer.s-eng"]}>
          <SeatsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("engineer.s-eng");
    // only the addressed seat's composer is open, and its delivery note names the wake
    const notes = await screen.findAllByTestId("seat-delivery-note");
    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent("wake engineer.s-eng");
    expect(within(rowFor("engineer.s-eng")).getByTestId("seat-message")).toHaveAttribute("aria-expanded", "true");
  });
});
