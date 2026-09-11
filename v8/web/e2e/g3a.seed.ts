// G3a e2e fixtures. Each spec seeds its own rich epic via the real /v1 endpoints (not board.ts,
// which stays the shared minimal rig) so the specs are self-contained and order-independent. The
// board is the one globalSetup spawned; ADMIN is its admin token. Mirrors test_ui_live.py: X-Admin
// for participants, X-Participant for authored objects.
const BASE = () => process.env.EDP8_E2E_BASE!;
const ADMIN = () => process.env.EDP8_ADMIN_TOKEN ?? "t";

async function call(method: string, path: string, body: unknown, headers: Record<string, string>): Promise<any> {
  const r = await fetch(`${BASE()}${path}`, {
    method,
    headers: { "content-type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = (await r.json()) as { ok: boolean; value?: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${path} → ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

const admin = { "X-Admin": ADMIN() };
const as = (id: string) => ({ "X-Participant": id });

export interface G3aFixture {
  epic: string;
  story: string;
  doc: string;
  signoffCriterion: string;
  words: string;
  steer: string;
  /** the board's derived short title (human #32, Board.derive_title: first clause ≤80) */
  title: string;
}

let counter = 0;

/** Seed an epic with the owner's words, an owner steer (directive), a story with criteria and a
 *  seat, a strategy doc, and one pending owner-checked criterion citing that doc (the §14 sign-off).
 *  Idempotent-ish via a per-call suffix so repeated specs don't collide. */
export async function seedEpic(): Promise<G3aFixture> {
  const n = ++counter;
  const words = "Upgrade the live board UI with a white background and orange accents — concepts first.";
  const steer = "Concepts first from Astra before any planning.";
  const arch = `architect.g3a-${n}`;
  const eng = `engineer.g3a-${n}`;

  // Participants (ignore 'already exists'). The board's role scopes decide who may author what:
  // epics are the owner's, stories + their criteria the architect's, docs the architect's, and a
  // criterion's evidence_ref is set by the ticket's doer (the engineer). We seed one of each.
  await call("POST", "/v1/participants", { type: "agent", role: "architect", handle: `arch${n}`, id: arch }, admin).catch(() => {});
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: `eng${n}`, id: eng }, admin).catch(() => {});

  // Epic authored BY THE OWNER so epic_owner resolves to `owner` — that is what lets the owner
  // rule the §14 sign-off criterion on this epic (board.epic_owner / criterion verdict guard).
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: words }, as("owner"))).id;
  const story = (
    await call(
      "POST",
      "/v1/tickets",
      { kind: "story", work_type: "feature", title: "Epic page destination", parent_id: epic, assignee: eng },
      as(arch),
    )
  ).id;

  // Story criterion (checker derived → qa; enough to show a tally), authored by the architect.
  await call("POST", "/v1/criteria", { ticket_id: story, text: "RTL is green", check: "command" }, as(arch)).catch(() => {});

  // Owner steer on the epic → the directive callout.
  await call("POST", "/v1/messages", { ticket_id: epic, kind: "steer", text: steer }, as("owner"));

  // A doc scoped to the epic (opens in the reader / drawer). doc_type=design so the architect may
  // author it (strategy_* docs are the sme's); the reader renders any type identically. A second
  // version is written so the reader shows version pills (v1 + latest v2).
  const doc = (
    await call(
      "POST",
      "/v1/docs",
      {
        doc_type: "design",
        title: "Folio craft bars",
        // v1 is HOSTILE (adversary finding #13, 2026-09-10): a script, an onerror image and a
        // javascript: link. The reader must render the safe text and none of these.
        body_md:
          "# Craft\n\nSafe body text.\n\n<script>window.__pwned = 1</script>\n<img src=x onerror=\"window.__pwned=2\">\n<a href=\"javascript:window.__pwned=3\">click</a>",
        scope: epic,
      },
      as(arch),
    )
  ).id;
  await call("PATCH", `/v1/docs/${doc}`, { body_md: "# Craft\n\nSafe body text, revised." }, as(arch));

  // One pending owner-checked criterion citing the doc → the §14 one-click sign-off. The owner may
  // write a checked_by="owner" criterion only with an override_reason (board owner_override path);
  // its evidence_ref is then recorded by the ticket's doer (the engineer assignee).
  const c = await call(
    "POST",
    "/v1/criteria",
    {
      ticket_id: story,
      text: "The Folio craft bars read well and are complete.",
      check: "look",
      checked_by: "owner",
      override_reason: "e2e sign-off fixture",
    },
    as("owner"),
  );
  await call("PATCH", `/v1/criteria/${c.id}`, { evidence_ref: doc }, as(eng));

  const title = ((await call("GET", `/v1/tickets/${epic}`, undefined, as("owner"))) as { title: string }).title;
  return { epic, story, doc, signoffCriterion: c.id, words, steer, title };
}
