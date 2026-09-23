import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
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
  replies?: unknown[];
  epics?: unknown[];
  seats?: unknown[];
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
    http.get("/v1/me/replies", () => HttpResponse.json({ ok: true, value: f.replies ?? [] })),
    http.get("/v1/epics/summary", () => HttpResponse.json({ ok: true, value: f.epics ?? [] })),
    http.get("/v1/seats", () => HttpResponse.json({ ok: true, value: { seats: f.seats ?? [], people: [] } })),
    http.get("/v1/pool/capabilities", () =>
      HttpResponse.json({ ok: true, value: { resume_parked: true, resume_closed: false, park: true, spawn: false } })),
    http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { to: null, wakes: [], plan: [], note: "nobody is woken" } })),
  );
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DraftGuardProvider>
          <DecisionsPage />
        </DraftGuardProvider>
      </MemoryRouter>
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

  it("a handed-off quick task lists one row per criterion, tagged Quick task (S-QUICK)", async () => {
    const q = (id: string) => {
      const row = sign(id, "Quick report");
      return { ...row, ticket: { ...row.ticket, id: "s-q", title: "Rename the tab", epic_id: "s-q", epic_title: "Rename the tab", quick: true } };
    };
    setBoard({ signoffs: [q("1"), q("2")] });
    mount();
    const featured = await screen.findByTestId("featured-signoff");
    expect(within(featured).getByText("Quick task")).toBeInTheDocument();
    expect(within(featured).getByRole("heading", { name: "criterion 1" })).toBeInTheDocument();
    const more = screen.getByTestId("more-docs");
    expect(more).toHaveTextContent("criterion 2");
    expect(more).toHaveTextContent("Quick task · Rename the tab");
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

  it("Seats-now reads /v1/seats with the Seats presence rule: alive seat, its ticket, honest 'no update'", async () => {
    setBoard({
      seats: [{
        id: "engineer.s-9", handle: "engineer.s-9", role: "engineer", state: "alive",
        ticket_id: "s-9", ticket_title: "Ship the sheet", last_output_at: new Date().toISOString(),
        latest_status: null, reason: null,
      }],
    });
    mount();
    const seats = await screen.findByTestId("seats-now");
    // a compact card per seat (spacing pass 2026-09-10), same source + presenceOf as the Seats page
    expect(await within(seats).findByTestId("seat-row")).toBeInTheDocument();
    expect(within(seats).getByTestId("seat-state")).toHaveTextContent("Working");
    expect(within(seats).getByText("Ship the sheet")).toBeInTheDocument();
    // honest by construction: a seat that reported no status says so, never a fake progress number
    expect(within(seats).getByTestId("no-status")).toHaveTextContent("Last work update unavailable");
    expect(within(seats).getByText("Shell alive ≠ work progressing")).toBeInTheDocument();
  });

  it("refreshes the queues live under a dirty composer and keeps the half-typed reply (S19)", async () => {
    let reads = 0;
    setBoard({
      signoffs: [sign("1", "Oldest report"), sign("2", "Newer report")],
      questions: [{ id: "m-1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "which theme?", from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "alive", note: "its shell is alive" } }],
    });
    server.use(http.get("/v1/me/decisions", () => {
      reads += 1;
      return HttpResponse.json({ ok: true, value: { signoffs: [], questions: [{ id: "m-1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "which theme?", from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "alive", note: "its shell is alive" } }], gates: [], counts: { signoffs: 0, questions: 1, gates: 0 } } });
    }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Questions/ }));
    fireEvent.click(await screen.findByTestId("reply"));
    const draft = await screen.findByTestId("composer-text");
    fireEvent.change(draft, { target: { value: "folio" } });
    const before = reads;
    // A live event arrives while the reply is half-typed: no "N new — refresh" hold any more.
    act(() => fire!({ seq: 99 }));
    await waitFor(() => expect(reads).toBeGreaterThan(before));
    expect(screen.queryByTestId("page-refresh")).toBeNull();
    expect(screen.getByTestId("composer-text")).toBe(draft);
    expect(draft).toHaveValue("folio");
  });

  it("frames a question through AgentLine — name-first, id in mono, a reader-relative tag (§15)", async () => {
    setBoard({
      questions: [{ id: "m-1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "which theme?", from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "alive", note: "its shell is alive" } }],
    });
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Questions/ }));
    const line = await screen.findByTestId("agent-line");
    expect(line).toHaveTextContent("engineer"); // name/role first, not a bare id
    expect(within(line).getByTestId("agent-id")).toHaveTextContent("engineer.s-1");
    expect(within(line).getByTestId("reader-tag")).toBeInTheDocument();
  });
});

describe("Decisions question rows say why (§16.2, promise #21)", () => {
  const q = (why?: string) => ({
    id: "m-1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "which theme?",
    from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "alive", note: "its shell is alive" },
    ...(why ? { why } : {}),
  });

  it("renders the board's why clause verbatim as a muted line", async () => {
    setBoard({ questions: [q("addressed to you (@owner)")] });
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Questions/ }));
    const row = await screen.findByTestId("question");
    expect(within(row).getByTestId("why")).toHaveTextContent("Why you see it: addressed to you (@owner)");
  });

  it("omits the line when the board sent no why (older boards)", async () => {
    setBoard({ questions: [q()] });
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Questions/ }));
    const row = await screen.findByTestId("question");
    expect(within(row).queryByTestId("why")).toBeNull();
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

// Coverage pass (c-7c51c6b69b): the Gates / Resolved tabs (filled and empty), the board-unreachable
// sentence, the featured card's optional fields, the "more" list opening the ruling drawer, the
// Replies section, the conversations "By counterpart" grouping + the ticket picker, and the
// Seats-now card variants (parked, ticket without a title, no ticket, a latest status, error).
describe("Decisions coverage pass", () => {
  it("shows one calm sentence when the decisions call fails, and the seats rail says it is unavailable", async () => {
    setBoard({});
    server.use(
      http.get("/v1/me/decisions", () => HttpResponse.json({ ok: false, error: "down" }, { status: 500 })),
      http.get("/v1/seats", () => HttpResponse.json({ ok: false, error: "down" }, { status: 500 })),
    );
    mount();
    expect(await screen.findByText(/The board could not be reached/)).toBeInTheDocument();
    expect(await screen.findByText("Seats are unavailable right now.")).toBeInTheDocument();
  });

  it("Gates tab lists a GateForm per open gate; Resolved tab lists verdicts and gate answers", async () => {
    setBoard({
      gates: [{ ticket_id: "epic-1", gate: "scope", by: "architect.epic-1", note: "widen?", opened_at: "x", epic: "epic-1" }],
      resolved: [
        { at: "x", kind: "verdict", ticket_id: "s-1", criterion: "c-1", verdict: "pass" },
        { at: "x", kind: "gate", ticket_id: "epic-1", gate: "scope", answer: "yes" },
      ],
      conversations: [{ ticket_id: "s-1", title: "Named story", epic_id: "epic-1", unread: false, last: null }],
      epics: [{ id: "epic-1", title: "Board redesign", status: "in_progress", created_at: "x", criteria: { passed: 0, failed: 0, pending: 0, total: 0 }, open_gates: 1, waiting_reason: { reason: "", presence: null, latest_status: null }, assigned_seats: [], latest_status: null }],
    });
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Gates/ }));
    expect(await screen.findByTestId("gate-form")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Resolved/ }));
    const resolved = await screen.findByTestId("resolved");
    expect(resolved).toHaveTextContent("pass · c-1");
    expect(resolved).toHaveTextContent("Named story");
    expect(resolved).toHaveTextContent("scope gate · yes");
    expect(resolved).toHaveTextContent("Board redesign");
    // a conversation with no last message is live by definition and shows no "last" line
    const convos = screen.getByTestId("conversations");
    expect(within(convos).getByText("on your ticket")).toBeInTheDocument();
  });

  it("empty Gates / Resolved / Questions tabs each render their own calm sentence", async () => {
    setBoard({});
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Gates/ }));
    expect(await screen.findByText(/No open gates/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Resolved/ }));
    expect(await screen.findByText(/Nothing resolved yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Questions/ }));
    expect(await screen.findByText(/No questions in your inbox/)).toBeInTheDocument();
  });

  it("a question without an asker block still counts and renders without the note", async () => {
    setBoard({
      questions: [
        { id: "m-1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "bare?", from_role: "engineer" },
        { id: "m-2", ticket_id: "s-1", created_by: "engineer.s-2", to: "owner", kind: "question", text: "gone?", from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "dead", note: "its shell is dead" } },
      ],
    });
    mount();
    await waitFor(() => expect(screen.getByRole("tab", { name: /Questions/ })).toHaveTextContent("1"));
    fireEvent.click(screen.getByRole("tab", { name: /Questions/ }));
    const rows = await screen.findAllByTestId("question");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("bare?");
  });

  it("featured card copes with no excerpt / no doc / no assignee; the 'more' rows open the ruling drawer", async () => {
    server.use(
      http.get("/v1/docs/:id/html", () => HttpResponse.json({ ok: true, value: { id: "report-2", title: "Second", doc_type: "report", version: 1, versions: [1], html: "<p>hi</p>" } })),
    );
    const bare = { ...sign("1", "unused"), doc: null, excerpt: "", ticket: { ...sign("1", "unused").ticket, assignee: null } };
    setBoard({ signoffs: [bare, sign("2", "Second"), { ...sign("3", "unused"), doc: null }] });
    mount();
    const featured = await screen.findByTestId("featured-signoff");
    expect(within(featured).getByText("the assignee")).toBeInTheDocument();
    expect(within(featured).getByText("Ticket 1")).toBeInTheDocument();
    expect(within(featured).queryByText(/excerpt/)).toBeNull();
    const more = screen.getByTestId("more-docs");
    expect(more).toHaveTextContent("2 more documents awaiting your sign-off");
    // the doc-less rest row shows the ticket title in the doc slot
    expect(within(more).getAllByText("Ticket 3").length).toBeGreaterThan(0);
    fireEvent.click(within(more).getByText("Second"));
    const panel = await screen.findByTestId("drawer-panel");
    expect(panel).toHaveTextContent("2 of 3 sign-offs");
  });

  it("Replies to you: quotes the viewer's words, links epic and ticket threads, and replies in place", async () => {
    setBoard({
      replies: [
        { id: "m-r1", ticket_id: "epic-1", ticket_title: "Epic thread", created_by: "architect.epic-1", kind: "answer", text: "yes, folio", at: "x", reply_to: "m-0", in_reply_to: { by: "owner", text: "which theme?" } },
        { id: "m-r2", ticket_id: "s-1", ticket_title: "Story thread", created_by: "engineer.s-1", kind: "note", text: "done", at: "x", reply_to: null, in_reply_to: null },
      ],
    });
    mount();
    const replies = await screen.findByTestId("replies");
    expect(replies).toHaveTextContent("Replies to you (2)");
    expect(within(replies).getByText(/which theme\?/)).toBeInTheDocument();
    expect(within(replies).getByRole("link", { name: "Epic thread" })).toHaveAttribute("href", "/epic/epic-1#m-r1");
    expect(within(replies).getByRole("link", { name: "Story thread" })).toHaveAttribute("href", "/ticket/s-1#m-r2");
    const rows = within(replies).getAllByTestId("reply-row");
    expect(within(rows[1]).queryByText("you wrote:")).toBeNull();
    fireEvent.click(within(rows[0]).getByTestId("reply-to-reply"));
    expect(await within(rows[0]).findByTestId("composer")).toBeInTheDocument();
  });

  it("conversations group by counterpart on toggle, and the new-conversation picker selects a ticket", async () => {
    const people = [{ id: "owner", handle: "owner", type: "human", role: "owner", seat_ticket: null, seat_state: null, label: "person", self: false }];
    setBoard({
      people,
      conversations: [
        { ticket_id: "s-1", title: "Silent", epic_id: "epic-1", unread: false, last: null },
        { ticket_id: "s-2", title: "Spoken", epic_id: "epic-1", unread: true, last: { by: "owner", text: "hello", at: "x" } },
        { ticket_id: "s-3", title: "Quiet closed", epic_id: "epic-1", unread: false, last: { by: "engineer.gone", text: "bye", at: "x" } },
      ],
    });
    mount();
    const convos = await screen.findByTestId("conversations");
    expect(await within(convos).findAllByTestId("convo-group")).toHaveLength(1);
    expect(within(convos).getByText("owner: hello")).toBeInTheDocument();
    fireEvent.click(within(convos).getByRole("button", { name: "By counterpart" }));
    expect(within(convos).getAllByTestId("convo-group")).toHaveLength(2);
    expect(within(convos).getByText("thread")).toBeInTheDocument();
    expect(within(convos).getByRole("button", { name: "By ticket" })).toHaveAttribute("aria-pressed", "true");
    expect(within(convos).queryByText("owner: hello")).toBeNull();
    // closed seat with nothing unread shows no dead-seat flag
    fireEvent.click(within(convos).getByTestId("closed-seats"));
    expect(within(convos).getByText("Quiet closed")).toBeInTheDocument();
    expect(within(convos).queryByTestId("dead-seat-flag")).toBeNull();
    // the picker
    fireEvent.click(within(convos).getByTestId("new-conversation"));
    const select = (await within(convos).findByTestId("new-conversation-ticket")) as HTMLSelectElement;
    expect(select.value).toBe("s-1");
    fireEvent.change(select, { target: { value: "s-2" } });
    expect(select.value).toBe("s-2");
  });

  it("Seats-now cards: parked seat with a bare ticket id, a seat with no ticket but a latest status; dead seats are left out", async () => {
    setBoard({
      seats: [
        { id: "engineer.s-1", handle: "engineer.s-1", role: "engineer", state: "parked", ticket_id: "s-1", ticket_title: null, last_output_at: null, presence_stale_since: null, reason: "", latest_status: null },
        { id: "qa.epic-1", handle: "qa.epic-1", role: "qa", state: "stalled", ticket_id: null, ticket_title: null, last_output_at: new Date().toISOString(), presence_stale_since: null, reason: "", latest_status: { text: "checking the sheet", status: null, role: null, at: "x" } },
        { id: "engineer.s-2", handle: "engineer.s-2", role: "engineer", state: "dead", ticket_id: "s-2", ticket_title: "Gone", last_output_at: null, presence_stale_since: null, reason: "", latest_status: null },
      ],
    });
    mount();
    const seats = await screen.findByTestId("seats-now");
    const rows = await within(seats).findAllByTestId("seat-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "s-1" })).toHaveAttribute("href", "/ticket/s-1");
    expect(within(rows[1]).queryByRole("link", { name: /s-/ })).toBeNull();
    expect(within(rows[1]).getByTestId("latest-status")).toHaveTextContent("checking the sheet");
    expect(within(seats).queryByText("Gone")).toBeNull();
  });
});

describe("S-UI: Decisions defaults to one epic, Needs you first (c-ef986a3491)", () => {
  const q = (id: string, epic: string, text: string) => ({
    id, ticket_id: epic === "epic-1" ? "s-a" : "s-b", created_by: "architect.x", to: "owner", kind: "question", text, epic_id: epic,
    asker: { type: "agent", role: "architect", seat_state: "alive", note: "" }, why: "addressed to you (@owner)" });
  const fixtures = {
    epics: ["epic-1", "epic-2"].map((id, i) => ({ id, title: i ? "Space game" : "Board redesign", status: "in_progress", created_at: "x", criteria: { passed: 0, failed: 0, pending: 0, total: 0 }, open_gates: 0, waiting_reason: { reason: "", presence: null, latest_status: null }, assigned_seats: [], latest_status: null })),
    questions: [q("m-1", "epic-1", "Which icon set?"), q("m-2", "epic-2", "Ship thrust?")],
    gates: [{ ticket_id: "epic-2", gate: "design_signoff", by: "architect.y", note: null, opened_at: "2026-09-20T10:00:00Z", epic: "epic-2" }],
    signoffs: [sign("k1", "Report one"), { ...sign("k2", "Report two"), ticket: { ...sign("k2", "x").ticket, epic_id: "epic-2" } }],
  };
  function mountAt(url: string) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[url]}><DraftGuardProvider><DecisionsPage /></DraftGuardProvider></MemoryRouter></QueryClientProvider>);
  }
  beforeEach(() => { try { sessionStorage.clear(); } catch { /* ignore */ } });

  it("opened from an epic (?epic=) shows only that epic; Needs you sits before the tabs", async () => {
    setBoard(fixtures);
    mountAt("/me?epic=epic-1");
    const needs = await screen.findByTestId("needs-you");
    await waitFor(() => expect(within(needs).getAllByTestId("needs-you-ask").map((r) => r.getAttribute("data-ask"))).toEqual(["m-1"]));
    expect(within(needs).queryAllByTestId("needs-you-gate")).toHaveLength(0);
    expect((screen.getByTestId("decisions-epic-filter") as HTMLSelectElement).value).toBe("epic-1");
    // Needs you precedes the queues in document order
    expect(needs.compareDocumentPosition(screen.getByRole("tablist")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Sign-offs/ })).toHaveTextContent("1");
    expect(within(needs).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/ticket/s-a#m-1");
  });

  it("\"All epics\" is a choice, not the default; choosing it shows every epic's asks and gates", async () => {
    setBoard(fixtures);
    mountAt("/me?epic=epic-2");
    const filter = await screen.findByTestId("decisions-epic-filter") as HTMLSelectElement;
    await waitFor(() => expect(within(screen.getByTestId("needs-you")).getAllByTestId("needs-you-gate")).toHaveLength(1));
    expect(Array.from(filter.options).map((o) => o.textContent)).toEqual(["All epics", "Board redesign", "Space game"]);
    fireEvent.change(filter, { target: { value: "all" } });
    await waitFor(() => expect(within(screen.getByTestId("needs-you")).getAllByTestId("needs-you-ask")).toHaveLength(2));
    expect(screen.getByRole("tab", { name: /Sign-offs/ })).toHaveTextContent("2");
  });

  it("with no ?epic= the last epic seen this session is the default", async () => {
    sessionStorage.setItem("edp8.ui.last-epic", "epic-2");
    setBoard(fixtures);
    mountAt("/me");
    await waitFor(() => expect(within(screen.getByTestId("needs-you")).getAllByTestId("needs-you-ask").map((r) => r.getAttribute("data-ask"))).toEqual(["m-2"]));
  });
});
