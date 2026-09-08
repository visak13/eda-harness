// G3b e2e fixtures. Seeds, through the real /v1 endpoints, a story parked at `ready` and assigned
// to the owner, carrying ONE pending owner-checked criterion that already has evidence — the exact
// shape the S16 close-every-loop spec needs to walk ready → in_progress → in_review → done from the
// ticket page and record a verdict on the way. Self-contained + per-call suffix so runs don't clash.
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

export interface G3bLoopFixture {
  epic: string;
  story: string;
  doc: string;
  criterion: string;
}

let counter = 0;

/** A story at `ready`, assigned to the owner, with one pending owner-checked criterion that already
 *  cites a doc as evidence. Reaching `ready` walks the real status path (drafted → designed →
 *  signed_off → ready) so the board's own guards produce the state — nothing is forced. */
export async function seedLoopStory(): Promise<G3bLoopFixture> {
  const n = ++counter;
  const arch = `architect.g3b-${n}`;
  await call("POST", "/v1/participants", { type: "agent", role: "architect", handle: `barch${n}`, id: arch }, admin).catch(() => {});

  // Epic authored BY THE OWNER so epic_owner === owner — the owner may then verdict the sign-off
  // criterion and mark the story done (board checker guard).
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: `Loop epic ${n}` }, as("owner"))).id;
  const story = (
    await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: `Close the loop ${n}`, parent_id: epic, assignee: "owner" }, as(arch))
  ).id;

  // A design doc + the design_ref, so the architect can mark the story `designed`.
  const doc = (
    await call("POST", "/v1/docs", { doc_type: "design", title: `Loop design ${n}`, body_md: "# Loop\n\nEvidence body.", scope: epic }, as(arch))
  ).id;
  await call("PATCH", `/v1/tickets/${story}`, { design_ref: doc }, as(arch));

  // One owner-checked criterion (needs an override_reason when the owner authors checked_by=owner),
  // then the engineer-less evidence_ref is set by the owner assignee. Its presence lets the story
  // reach in_review and gives the spec something to verdict.
  const c = await call(
    "POST",
    "/v1/criteria",
    { ticket_id: story, text: "The loop closes end to end.", check: "look", checked_by: "owner", override_reason: "e2e loop fixture" },
    as("owner"),
  );
  await call("PATCH", `/v1/criteria/${c.id}`, { evidence_ref: doc }, as("owner"));

  // Walk the real status path to `ready` via the board's guards.
  await call("PATCH", `/v1/tickets/${story}`, { status: "designed" }, as(arch)); // architect marks designed
  await call("PATCH", `/v1/tickets/${story}`, { status: "signed_off" }, as("owner")); // owner signs off → auto-releases to ready

  return { epic, story, doc, criterion: c.id };
}
