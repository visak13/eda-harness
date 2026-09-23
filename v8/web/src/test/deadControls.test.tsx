// Dead-control lint (human ruling #26): walk the REAL route table (src/routes.tsx) and fail on any
// rendered control that does nothing — an <a> without href, or a button with no click handler and
// no submitting form. React props are read off the fiber (`__reactProps$…`) so a handler wired in
// JSX counts even though jsdom cannot see it as an attribute. The historical proof cases were the
// Epics-page "New epic" (data-testid=new-epic-open) and the rail Find (data-testid=find-open).
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "./setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import { appRoutes } from "../routes";

// ------------------------------------------------------------------ the linter

function reactProps(el: Element): Record<string, unknown> | undefined {
  const key = Object.keys(el).find((k) => k.startsWith("__reactProps$"));
  return key ? ((el as unknown as Record<string, unknown>)[key] as Record<string, unknown>) : undefined;
}

function hasHandler(props: Record<string, unknown> | undefined): boolean {
  if (!props) return false;
  return (
    typeof props.onClick === "function" ||
    typeof props.onMouseDown === "function" ||
    typeof props.onPointerDown === "function"
  );
}

function label(el: Element): string {
  const testid = el.getAttribute("data-testid");
  const text = (el.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
  const aria = el.getAttribute("aria-label");
  return `${el.tagName}${testid ? `#${testid}` : ""}:${text || aria || ""}`;
}

/** Every dead control under `root`, as readable `TAG#testid:text` labels. */
export function findDeadControls(root: ParentNode): string[] {
  const dead: string[] = [];
  for (const el of Array.from(root.querySelectorAll('a, button, [role="button"]'))) {
    if (el.tagName === "A") {
      if (!el.hasAttribute("href")) dead.push(label(el));
      continue;
    }
    const isButton = el.tagName === "BUTTON";
    if (isButton && (el as HTMLButtonElement).disabled) continue;
    if (el.getAttribute("aria-disabled") === "true") continue;
    if (hasHandler(reactProps(el))) continue;
    // A submit button is live when its form submits somewhere (a React onSubmit).
    const type = isButton ? (el as HTMLButtonElement).type : el.getAttribute("type");
    if (type === "submit") {
      const form = el.closest("form");
      if (form && typeof reactProps(form)?.onSubmit === "function") continue;
    }
    dead.push(label(el));
  }
  return dead;
}

// ------------------------------------------------------------------ fixtures (shapes from the page suites)

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });

const EPIC_ROW = {
  id: "epic-1",
  title: "Upgrade the board UI",
  status: "in_progress",
  created_at: "2026-09-01T10:00:00Z",
  criteria: { passed: 2, failed: 0, pending: 2, total: 4 },
  open_gates: 0,
  waiting_reason: { reason: "engineer building", presence: "alive", latest_status: "on it" },
  assigned_seats: ["engineer.s-1"],
  latest_status: "on it",
};

const STORY_NODE = {
  id: "s-1",
  kind: "story",
  work_type: "feature",
  title: "First story",
  status: "in_progress",
  assignee: "engineer.s-1",
  criteria: "2/4",
  gates: [],
  blocked_by: [],
  children: [],
};
const EPIC_NODE = {
  id: "epic-1",
  kind: "epic",
  work_type: "feature",
  title: "Upgrade the board UI",
  status: "in_progress",
  assignee: null,
  criteria: "0/0",
  gates: [],
  blocked_by: [],
  children: [STORY_NODE],
};
const DOC = { id: "d-1", doc_type: "design", title: "The design", version: 2, scope: "epic-1", summary: "", full: "" };
const CRITERION = {
  id: "c-1",
  text: "the report proves it",
  check: "look",
  checked_by: "owner",
  verdict: "pending",
  evidence_ref: "d-1",
  evidence_version: 2,
};
const MESSAGE = { id: "m1", by: "engineer.s-1", to: null, kind: "note", text: "working on it", at: "2026-09-02T10:00:00Z", reply_to: null };
const GATE = { ticket_id: "s-1", gate: "demo", by: "architect.epic-1", note: "does it work?", opened_at: "2026-09-02T10:00:00Z", epic: "epic-1" };

const EPIC_PAGE = {
  board: { epic: EPIC_NODE, counts: { in_progress: 1 }, ready: [], in_review: [], open_gates: [GATE], words: EPIC_NODE.title },
  words: "Upgrade the board UI so that a first-time human can read it without a shell",
  title: EPIC_NODE.title,
  counts: { in_progress: 1 },
  thread: [MESSAGE, { ...MESSAGE, id: "m2", by: "owner", kind: "steer", text: "concepts first, then build" }],
  docs: [DOC],
  open_gates: [GATE],
  answerable_gates: [GATE],
  criteria: [CRITERION],
};

const TICKET_PAGE = {
  ticket: {
    id: "s-1",
    kind: "story",
    work_type: "feature",
    title: "Build the epic page",
    description: "Render the epic destination.",
    status: "in_review",
    assignee: "engineer.s-1",
    tags: ["web", "epics"],
    design_ref: "d-1",
    epic_id: "epic-1",
  },
  epic_id: "epic-1",
  criteria: [CRITERION, { ...CRITERION, id: "c-2", text: "e2e is green", verdict: "pass" }],
  docs: [{ ...DOC, relation: "designed_by" }],
  thread: [MESSAGE],
  assignee: { id: "engineer.s-1", handle: "engineer.s-1", role: "engineer" },
  waiting_reason: { reason: "awaiting qa", presence: "alive", latest_status: "on it" },
  open_gates: [GATE],
};

const DOC_HTML = {
  id: "d-1",
  title: "The design",
  doc_type: "design",
  scope: "epic-1",
  owner_role: "architect",
  version: 2,
  versions: [1, 2],
  html: "<h1>Design</h1><p>Safe body</p>",
  signoff_criterion: null,
};

const ARTIFACT = {
  id: "art-1",
  form: "file",
  uri: "file:///x/notes.txt",
  note: "the seat rail at 1024",
  created_by: "engineer.s-1",
  created_at: "2026-09-10T10:00:00Z",
  content_type: "text/plain",
  filename: "notes.txt",
};

const now = Date.now();
const ago = (ms: number) => new Date(now - ms).toISOString();
const SEATS = {
  seats: [
    {
      id: "engineer.s-1", handle: "engineer.s-1", role: "engineer", state: "alive",
      ticket_id: "s-1", ticket_title: "Build the epic page", last_output_at: ago(20_000),
      presence_stale_since: null, reason: "",
      latest_status: { text: "Owner checks are ready for review.", status: "reviewed", role: "engineer", at: ago(20_000) },
    },
    {
      id: "reviewer.s-1", handle: "reviewer.s-1", role: "reviewer", state: "parked",
      ticket_id: "s-1", ticket_title: "Build the epic page", last_output_at: ago(3 * 60_000),
      presence_stale_since: null, reason: "waiting on evidence", latest_status: null,
    },
    {
      id: "qa.s-2", handle: "qa.s-2", role: "qa", state: "dead",
      ticket_id: "s-2", ticket_title: "Verify session resume", last_output_at: ago(26 * 3600_000),
      presence_stale_since: null, reason: "closed by self", latest_status: null,
    },
  ],
  people: [{ id: "owner", handle: "owner", role: "owner" }],
};
const CAPS = { resume_parked: true, resume_closed: true, park: true, spawn: true };

const SIGNOFF = {
  criterion: CRITERION,
  ticket: { id: "s-1", title: "Build the epic page", epic_id: "epic-1", epic_title: "Upgrade the board UI", assignee: "engineer.s-1" },
  doc: { id: "d-1", title: "The design", doc_type: "report", version: 2 },
  excerpt: "excerpt",
};
const QUESTION = {
  id: "m-q1", ticket_id: "s-1", created_by: "engineer.s-1", to: "owner", kind: "question", text: "which theme?",
  from_role: "engineer", asker: { type: "agent", role: "engineer", seat_state: "alive", note: "its shell is alive" },
};
const DECISIONS = {
  signoffs: [SIGNOFF],
  questions: [QUESTION],
  gates: [GATE],
  counts: { signoffs: 1, questions: 1, gates: 1 },
};

const LIBRARY = {
  docs: [DOC],
  artifacts: [
    { id: "art-1", form: "image", uri: "/v1/artifacts/art-1/content", note: "a shot", created_by: "engineer.s-1", created_at: "2026-09-01T10:00:00Z" },
    { id: "art-2", form: "file", uri: "http://x/two.txt", note: "", created_by: "engineer.s-1", created_at: "2026-09-01T10:00:00Z" },
  ],
  links: [{ id: "l-1", from_id: "s-1", to_id: "d-1", relation: "designed_by", created_by: "architect.epic-1" }],
};
const TABLE = {
  rows: [
    {
      id: "s-1", epic_id: "epic-1", title: "Build the epic page", kind: "story", work_type: "feature",
      status: "in_progress", assignee: "engineer.s-1", tags: ["web"],
      criteria: { passed: 1, failed: 0, pending: 1, total: 2 }, blocked_by: [],
    },
  ],
  count: 1,
};
const ACTIVITY = [
  { day: "Monday 01 Sep", events: [{ line: "moved ready → in_progress", subject_id: "s-1", kind: "status_changed", at: "2026-09-01T09:30:00Z" }] },
];

/** Endpoints that fell through to the catch-all during a walk — reported, never fatal. */
const unhandled: string[] = [];

function installBoard(): void {
  const catchAll = (kind: string) => ({ request }: { request: Request }) => {
    const u = new URL(request.url);
    const line = `${kind} ${u.pathname}${u.search}`;
    if (!unhandled.includes(line)) unhandled.push(line);
    console.warn(`[deadControls] catch-all: ${line}`);
    return ok([]);
  };
  server.use(
    http.get("/v1/whoami", () => ok({ participant: { id: "owner", handle: "owner", role: "owner" }, tickets: [] })),
    http.get("/v1/me/summary", () => ok({ decisions: 3, epics: 1, seats: 3, library: 4 })),
    http.get("/v1/me/decisions", () => ok(DECISIONS)),
    http.get("/v1/me/decisions/resolved", () => ok([])),
    http.get("/v1/me/people", () => ok([{ id: "owner", handle: "owner", role: "owner" }])),
    http.get("/v1/me/conversations", () => ok([])),
    http.get("/v1/me/replies", () => ok([])),
    http.get("/v1/me/avatar", () => ok({ avatar_id: null })),
    http.get("/v1/epics/summary", () => ok([EPIC_ROW])),
    http.get("/v1/epics/epic-1/page", () => ok(EPIC_PAGE)),
    http.get("/v1/tickets/table", () => ok(TABLE)),
    http.get("/v1/tickets/s-1/page", () => ok(TICKET_PAGE)),
    http.get("/v1/tickets/:id/contextual", ({ params }) => ok({
      ticket_id: params.id, title: "Work context", kind: params.id === "epic-1" ? "epic" : "story",
      status: "in_progress", owner: "owner", requester: "owner", assignee: null,
      design_ref: null, scope: "epic-1", gates: [], blockers: [], unresolved_asks: [], records: [], events: [],
    })),
    http.get("/v1/tickets/:id/transitions", () =>
      ok({ status: "in_progress", transitions: [{ to: "done", allowed: true, reason: null }] }),
    ),
    http.get("/v1/docs/d-1/html", () => ok(DOC_HTML)),
    http.get("/v1/artifacts/art-1", () => ok(ARTIFACT)),
    http.get("/v1/artifacts/:id/content", () =>
      new HttpResponse("hello", { headers: { "content-type": "text/plain", "content-disposition": 'attachment; filename="notes.txt"' } }),
    ),
    http.get("/v1/library", () => ok(LIBRARY)),
    http.get("/v1/activity", () => ok(ACTIVITY)),
    http.get("/v1/seats", () => ok(SEATS)),
    http.get("/v1/pool/capabilities", () => ok(CAPS)),
    http.get("/v1/messages", () => ok([])),
    http.get("/v1/events", () => ok([])),
    http.post("/v1/messages/resolve", () => ok({ to: null, wakes: [], plan: [], note: "nobody is woken" })),
    // The live feed: an open stream that never emits (the shared default, re-declared so the catch-all
    // below does not shadow it — server.use handlers take precedence over the setup defaults).
    http.get("/v1/feed", () => new HttpResponse(new ReadableStream(), { headers: { "content-type": "text/event-stream" } })),
    http.get("/v1/*", catchAll("GET")),
    http.post("/v1/*", catchAll("POST")),
  );
}

// ------------------------------------------------------------------ harness

async function walk(path: string): Promise<void> {
  installBoard();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(document.querySelector('[data-testid="page-framing"]')).toBeTruthy());
}

async function settle(ms = 50): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
  await waitFor(() => expect(document.querySelectorAll("*").length).toBeGreaterThan(0));
}

function expectNoDead(): void {
  // Never vacuously green: the shell alone carries its nav links + Find + identity. The floor is 6
  // since Notifications left the rail (c-1165c735b6, 8ed7ffa) and Usage was removed (S19).
  expect(document.body.querySelectorAll('a, button, [role="button"]').length).toBeGreaterThanOrEqual(6);
  const dead = findDeadControls(document.body);
  expect(dead, `dead controls on ${window.location.pathname}: ${dead.join(", ")}`).toEqual([]);
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/1");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ------------------------------------------------------------------ self-test

describe("findDeadControls (self-test)", () => {
  it("reports exactly the href-less anchor and the handler-less button", () => {
    render(
      <div data-testid="fixture">
        <button type="button">Dead</button>
        <a>Nowhere</a>
        <button onClick={() => {}}>Live</button>
        <form onSubmit={(e) => e.preventDefault()}>
          <button type="submit">Go</button>
        </form>
      </div>,
    );
    expect(findDeadControls(screen.getByTestId("fixture"))).toEqual(["BUTTON:Dead", "A:Nowhere"]);
  });

  it("a submit button in a form WITHOUT onSubmit is dead; a disabled button is not counted", () => {
    render(
      <div data-testid="fixture">
        <form>
          <button type="submit">Orphan</button>
        </form>
        <button type="button" disabled>
          Off
        </button>
      </div>,
    );
    expect(findDeadControls(screen.getByTestId("fixture"))).toEqual(["BUTTON:Orphan"]);
  });
});

// ------------------------------------------------------------------ the walk

describe("dead-control lint over the real route table (human #26)", () => {
  it("/me (Decisions) — and the historical proof cases New epic / Find are live", async () => {
    await walk("/me");
    await screen.findByTestId("featured-signoff");
    await settle();
    expect(screen.getByTestId("find-open")).toBeInTheDocument();
    const dead = findDeadControls(document.body);
    expect(dead.some((d) => d.includes("#find-open"))).toBe(false);
    expectNoDead();
  });

  it("/epics", async () => {
    await walk("/epics");
    await screen.findByTestId("epic-list");
    await settle();
    // New epic moved here from the old header (design-a2e5369133); it stays a live proof case
    expect(screen.getByTestId("new-epic-open")).toBeInTheDocument();
    expect(findDeadControls(document.body).some((d) => d.includes("#new-epic-open"))).toBe(false);
    expectNoDead();
  });

  it("/epic/epic-1", async () => {
    await walk("/epic/epic-1");
    await screen.findByText("Upgrade the board UI", { selector: "h1" });
    await settle();
    expectNoDead();
  });

  it("/ticket/s-1", async () => {
    await walk("/ticket/s-1");
    await screen.findByText("Build the epic page", { selector: "h1" });
    await settle();
    expectNoDead();
  });

  it("/doc/d-1", async () => {
    await walk("/doc/d-1");
    await screen.findByRole("heading", { level: 1, name: "The design" });
    await settle();
    expectNoDead();
  });

  it("/artifact/art-1", async () => {
    await walk("/artifact/art-1");
    await screen.findByTestId("artifact-download");
    await settle();
    expectNoDead();
  });

  it("/seats", async () => {
    await walk("/seats");
    await screen.findByText("engineer.s-1");
    await settle();
    expectNoDead();
  });

  it("/library/tickets", async () => {
    await walk("/library/tickets");
    await screen.findByTestId("tickets-table");
    await settle();
    expectNoDead();
  });

  it("/library/documents", async () => {
    await walk("/library/documents");
    await screen.findByText("The design");
    await settle();
    expectNoDead();
  });

  it("/library/artifacts", async () => {
    await walk("/library/artifacts");
    await screen.findByText("a shot");
    await settle();
    expectNoDead();
  });

  it("/library/links", async () => {
    await walk("/library/links");
    await screen.findByText("designed_by");
    await settle();
    expectNoDead();
  });

  it("/library/history", async () => {
    await walk("/library/history");
    await screen.findByText("Monday 01 Sep");
    await settle();
    expectNoDead();
  });

  it("/nowhere (NotFound)", async () => {
    await walk("/nowhere");
    await screen.findByText("Not found");
    await settle();
    expectNoDead();
  });

  it("reports every endpoint that fell through to the catch-all (informational)", () => {
    // Not a failure: an endpoint listed here got `{ok:true,value:[]}` — add a fixture above if a
    // page needs real data there to render its controls.
    if (unhandled.length) console.warn(`[deadControls] catch-all endpoints:\n  ${unhandled.join("\n  ")}`);
    expect(Array.isArray(unhandled)).toBe(true);
  });
});
