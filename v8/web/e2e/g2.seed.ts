// G2 Decisions e2e fixtures. Seeds, via the real /v1 endpoints (not mocks), the owner's
// Decisions surface: one pending owner sign-off (a report doc cited by an owner-checked
// criterion, §14), one question in the owner's inbox from a LIVE engineer seat, one open
// design_signoff gate, a second 0/0 epic for the pulse, and a DEAD seat that asked a question
// (the §18.2 "seat closed before answering" collapse). X-Admin authors participants/sessions;
// X-Participant authors tickets, criteria, docs and messages. Mirrors tests/test_ui_live.py.
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

const admin = () => ({ "X-Admin": ADMIN() });
const as = (id: string) => ({ "X-Participant": id });

export interface G2Fixture {
  epic: string; // the owner-owned epic carrying the sign-off, question and gate
  freshEpic: string; // a 0/0 epic → Epic pulse "None defined"
  story: string; // the story under `epic`, assigned to the live engineer seat
  liveSeat: string; // engineer.<story>, session state=alive
  deadSeat: string; // engineer.<deadStory>, session state=dead — a question of theirs is collapsed
  deadStory: string;
  doc: string; // the report cited by the sign-off criterion
  signoffCriterion: string; // pending owner-checked criterion (the §14 sign-off)
  question: string; // the question message id in the owner's inbox
  gate: string; // "design_signoff"
  words: string;
}

let counter = 0;

/** One self-contained Decisions scenario. Idempotent-ish via a per-call suffix. */
export async function seedDecisions(): Promise<G2Fixture> {
  const n = ++counter;
  const words = `Decisions surface fixture ${n}`;
  const gate = "design_signoff";
  const liveSeatEng = `eng-live-${n}`;
  const deadSeatEng = `eng-dead-${n}`;

  // The owner-owned epic (owner is seeded by board.ts startBoard).
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: words }, as("owner"))).id;
  const freshEpic = (
    await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: `${words} — fresh` }, as("owner"))
  ).id;

  // Story under the epic. Its assignee is the live engineer SEAT id (role.ticket), so Seats-now
  // and seat_for_role resolve it. We register that participant first.
  const story = (
    await call(
      "POST",
      "/v1/tickets",
      { kind: "story", work_type: "feature", title: "Decisions home story", parent_id: epic },
      as("owner"),
    )
  ).id;
  const liveSeat = `engineer.${story}`;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: liveSeatEng, id: liveSeat }, admin()).catch(
    () => {},
  );
  await call("PATCH", `/v1/tickets/${story}`, { assignee: liveSeat }, as("owner")).catch(() => {});
  // Make the seat ALIVE via a session record (seat_state reads the latest session).
  await call(
    "PUT",
    `/v1/sessions/sess-live-${n}`,
    { participant_id: liveSeat, ticket_id: story, pool_id: "e2e", state: "alive" },
    admin(),
  );

  // Two extra story criteria → a non-trivial tally on the epic pulse (0 of N passed).
  await call("POST", "/v1/criteria", { ticket_id: story, text: "RTL is green", check: "command" }, as("owner")).catch(() => {});
  await call("POST", "/v1/criteria", { ticket_id: story, text: "e2e is green", check: "command" }, as("owner")).catch(() => {});

  // The report the owner must sign off, scoped to the story (opens in the ruling drawer).
  const doc = (
    await call(
      "POST",
      "/v1/docs",
      {
        doc_type: "report",
        title: "Decisions engineer report",
        body_md: "# Decisions report\n\nThe surface proves the criterion from cold. Evidence follows.",
        scope: story,
      },
      as(liveSeat),
    )
  ).id;

  // The §14 sign-off: a pending owner-checked criterion citing that report as evidence.
  const c = await call(
    "POST",
    "/v1/criteria",
    {
      ticket_id: story,
      text: "The report proves the Decisions surface end-to-end.",
      check: "look",
      checked_by: "owner",
      override_reason: "e2e sign-off fixture",
    },
    as("owner"),
  );
  await call("PATCH", `/v1/criteria/${c.id}`, { evidence_ref: doc }, as("owner"));

  // A question from the LIVE seat to the owner → lands in the owner inbox (Questions tab, count 1).
  const q = await call(
    "POST",
    "/v1/messages",
    { ticket_id: story, to: "owner", kind: "question", text: "Which theme should the featured card use?" },
    as(liveSeat),
  );

  // An open design_signoff gate on the epic → owner Gates tab, count 1.
  await call("POST", `/v1/gates/${epic}/${gate}/open`, { note: "please rule on the design" }, as("owner"));

  // A DEAD seat that asked the owner a question on its own story → §18.2 collapse + dead-seat flag.
  const deadStory = (
    await call(
      "POST",
      "/v1/tickets",
      { kind: "story", work_type: "feature", title: "Abandoned story", parent_id: epic },
      as("owner"),
    )
  ).id;
  const deadSeat = `engineer.${deadStory}`;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: deadSeatEng, id: deadSeat }, admin()).catch(
    () => {},
  );
  await call("PATCH", `/v1/tickets/${deadStory}`, { assignee: deadSeat }, as("owner")).catch(() => {});
  await call(
    "POST",
    "/v1/messages",
    { ticket_id: deadStory, to: "owner", kind: "question", text: "Old question nobody answered." },
    as(deadSeat),
  );
  // Kill the seat AFTER it asked (state=dead) so the question stays but the counterpart is closed.
  await call(
    "PUT",
    `/v1/sessions/sess-dead-${n}`,
    { participant_id: deadSeat, ticket_id: deadStory, pool_id: "e2e", state: "dead", reason: "clean exit" },
    admin(),
  );

  return {
    epic,
    freshEpic,
    story,
    liveSeat,
    deadSeat,
    deadStory,
    doc,
    signoffCriterion: c.id,
    question: q.id,
    gate,
    words,
  };
}
