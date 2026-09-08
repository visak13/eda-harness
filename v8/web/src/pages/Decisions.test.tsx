import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { FeedEvent } from "../live/feed";
import { server } from "../test/setup";
import { DraftGuardProvider } from "../live/useDraftGuard";
import { DecisionsPage } from "./Decisions";

// Control the feed so the draft-guard integration test can fire an event deterministically.
let fire: ((e: FeedEvent) => void) | null = null;
vi.mock("../live/feed", () => ({
  subscribeFeed: (cb: (e: FeedEvent) => void) => {
    fire = cb;
    return () => {
      fire = null;
    };
  },
}));

const sign = (id: string, docTitle: string) => ({
  criterion: { id, text: `criterion ${id}`, check: "verdict", checked_by: "owner", verdict: "pending", evidence_ref: `report-${id}`, evidence_version: 1 },
  ticket: { id: `s-${id}`, title: `Ticket ${id}`, epic_id: "epic-1", epic_title: "Board redesign", assignee: "engineer.s-1" },
  doc: { id: `report-${id}`, title: docTitle, doc_type: "report", version: 1 },
  excerpt: `excerpt ${id}`,
});

interface Fixtures {
  signoffs?: unknown[];
  questions?: unknown[];
  gates?: unknown[];
  resolved?: unknown[];
  people?: unknown[];
  conversations?: unknown[];
  epics?: unknown[];
}

function setBoard(f: Fixtures) {
  const signoffs = f.signoffs ?? [];
  const questions = f.questions ?? [];
  const gates = f.gates ?? [];
  server.use(
    http.get("/v1/me/decisions", () =>
      HttpResponse.json({
        ok: true,
        value: { signoffs, questions, gates, counts: { signoffs: signoffs.length, questions: questions.length, gates: gates.length } },
      }),
    ),
    http.get("/v1/me/decisions/resolved", () => HttpResponse.json({ ok: true, value: f.resolved ?? [] })),
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: f.people ?? [] })),
    http.get("/v1/me/conversations", () => HttpResponse.json({ ok: true, value: f.conversations ?? [] })),
    http.get("/v1/epics/summary", () => HttpResponse.json({ ok: true, value: f.epics ?? [] })),
    http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { to: null, wakes: [], plan: [], note: "nobody is woken" } })),
  );
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DraftGuardProvider>
        <DecisionsPage />
      </DraftGuardProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fire = null;
});

describe("Decisions home", () => {
  it("features the oldest (first) pending sign-off and shows the tab counts from the payload", async () => {
    setBoard({ signoffs: [sign("1", "Oldest report"), sign("2", "Newer report")] });
    mount();
    const featured = await screen.findByTestId("featured-signoff");
    expect(within(featured).getByText("Oldest report")).toBeInTheDocument();
    // The other sign-off is summarised, not featured.
    expect(screen.getByTestId("more-docs")).toHaveTextContent("1 more document awaiting your sign-off");
    // Tab counts equal the decisions counts.
    expect(screen.getByRole("tab", { name: /Sign-offs/ })).toHaveTextContent("2");
  });

  it("an empty sign-off queue renders one calm sentence", async () => {
    setBoard({});
    mount();
    expect(await screen.findByText(/A clear desk/)).toBeInTheDocument();
  });

  it("Epic pulse shows 'None defined' for 0/0 and 'N of M criteria passed' otherwise, with no bar", async () => {
    setBoard({
      epics: [
        { id: "e0", title: "Fresh epic", status: "drafted", created_at: "x", criteria: { passed: 0, failed: 0, pending: 0, total: 0 }, open_gates: 0, waiting_reason: { reason: "Waiting on scope", presence: null, latest_status: null }, assigned_seats: [], latest_status: null },
        { id: "e1", title: "Busy epic", status: "in_progress", created_at: "x", criteria: { passed: 2, failed: 0, pending: 2, total: 4 }, open_gates: 0, waiting_reason: { reason: "2/4 criteria passed", presence: null, latest_status: null }, assigned_seats: [], latest_status: null },
      ],
    });
    mount();
    const pulse = await screen.findByTestId("epic-pulse");
    expect(await within(pulse).findByText("None defined")).toBeInTheDocument();
    expect(within(pulse).getByText("2 of 4 criteria passed")).toBeInTheDocument();
    expect(pulse.querySelector("progress")).toBeNull();
  });

  it("Seats-now lists the alive agent seat with its ticket and 'Last work update unavailable'", async () => {
    setBoard({
      people: [{ id: "engineer.s-9", handle: "engineer.s-9", type: "agent", role: "engineer", seat_ticket: "s-9", seat_state: "alive", label: "engineer seat", self: false }],
    });
    mount();
    const seats = await screen.findByTestId("seats-now");
    expect(await within(seats).findByText("s-9")).toBeInTheDocument();
    expect(within(seats).getByText("Last work update unavailable")).toBeInTheDocument();
    expect(within(seats).getByText("Shell alive ≠ work progressing")).toBeInTheDocument();
  });

  it("holds the list and shows 'N new — refresh' when a feed event lands under a dirty composer", async () => {
    setBoard({
      signoffs: [sign("1", "Oldest report"), sign("2", "Newer report")],
      questions: [{ id: "m-1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "which theme?", from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "alive", note: "its shell is alive" } }],
    });
    mount();
    // Open the inline reply composer and type → the composer marks the draft guard dirty.
    fireEvent.click(await screen.findByRole("tab", { name: /Questions/ }));
    fireEvent.click(await screen.findByTestId("reply"));
    fireEvent.change(await screen.findByTestId("composer-text"), { target: { value: "folio" } });
    // A live event arrives while the reply is half-typed.
    act(() => fire!({ seq: 99 }));
    expect(await screen.findByTestId("page-refresh")).toHaveTextContent("1 new — refresh");
  });
});

describe("Decisions conversations (§16.1 / §18.2)", () => {
  const people = [{ id: "owner", handle: "owner", type: "human", role: "owner", seat_ticket: null, seat_state: null, label: "person", self: false }];
  const conversations = [
    { ticket_id: "s-1", title: "Paged ticket", epic_id: "epic-1", unread: true, last: { by: "owner", text: "answer me", at: "x" } },
    { ticket_id: "s-2", title: "On your ticket", epic_id: "epic-1", unread: false, last: { by: "owner", text: "note", at: "x" } },
    { ticket_id: "s-3", title: "Dead-seat ask", epic_id: "epic-1", unread: true, last: { by: "engineer.dead", text: "old question", at: "x" } },
  ];

  it("labels rows from why, keeps live counterparts, and collapses closed seats with a dead-seat flag", async () => {
    setBoard({ people, conversations });
    mount();
    const convos = await screen.findByTestId("conversations");
    expect(await within(convos).findByText("you were paged")).toBeInTheDocument();
    expect(within(convos).getByText("on your ticket")).toBeInTheDocument();
    // The engineer.dead counterpart is not in the reachable people list → collapsed.
    const closed = within(convos).getByTestId("closed-seats");
    expect(closed).toHaveTextContent("Closed seats (1)");
    fireEvent.click(closed);
    expect(await within(convos).findByTestId("dead-seat-flag")).toHaveTextContent("seat closed before answering");
  });

  it("'New conversation' opens the object-attached composer", async () => {
    setBoard({ people, conversations });
    mount();
    fireEvent.click(await screen.findByTestId("new-conversation"));
    expect(await screen.findByTestId("composer")).toBeInTheDocument();
  });
});
