// G3b-owned endpoint functions for the Seats page (design §4.2, §18.3). Kept in its own module so
// it never collides with G2's decisions.ts or G3a's endpoints.ts during the parallel build (G4
// folds all three into one endpoints.ts). Reads unwrap via api<T>(); the pool actions go through
// postJson so the board's plain-sentence error (pool down, not permitted) is read verbatim.
import { api, postJson } from "./client";
import type { ModelCatalog, PoolCapabilities, SeatsView } from "./types";

export const getSeats = () => api<SeatsView>("/v1/seats");

/** GET /v1/pool/capabilities — read live what the pool can do; the UI shows Resume/Spawn only
 *  when the pool reports it (design §18.3, §21.4). Pool down → every capability false + a reason. */
export const getPoolCapabilities = () => api<PoolCapabilities>("/v1/pool/capabilities");

/** GET /v1/models — the per-role model catalog (S-ROLES): the new-epic dialog, the Epic page and
 *  Spawn seat all pick from this one list. A GPT id runs on the codex seat, a Claude id on Claude. */
export const getModels = () => api<ModelCatalog>("/v1/models");

/** A model id as the owner reads it. */
export function modelLabel(id: string | null | undefined, meta?: { context_window?: number | null }): string {
  const base = modelName(id);
  // S12 sweep #13: a 1M-window row says so, whether or not its id carries `[1m]`
  return meta?.context_window && meta.context_window >= 1_000_000 && !/\(1M\)$/.test(base) ? `${base} (1M)` : base;
}

function modelName(id: string | null | undefined): string {
  const known: Record<string, string> = {
    "claude-fable-5-1": "Claude Fable 5.1", "claude-opus-5-5": "Claude Opus 5.5",
    "gpt-6-astra": "GPT-6 Astra", "gpt-6-sol": "GPT-6 Sol", astra: "GPT-6 Astra", claude: "Claude",
  };
  if (!id) return "Claude (the fleet default)";
  if (known[id]) return known[id];
  // RC2 F2: any other catalog id reads as a name, not a raw id (`claude-sonnet-5-5[1m]` → "Claude Sonnet 5.5 (1M)")
  const oneM = /\[1m\]$/i.test(id);
  const base = id.replace(/\[1m\]$/i, "");
  const cap = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);
  const c = /^claude-([a-z]+)-(\d+)-(\d+)$/i.exec(base);
  const g = /^gpt-([\d.]+)-([a-z]+)$/i.exec(base);
  const name = c ? `Claude ${cap(c[1])} ${c[2]}.${c[3]}` : g ? `GPT-${g[1]} ${cap(g[2])}` : base;
  return oneM ? `${name} (1M)` : name;
}

/** POST /v1/sessions/resume — one path for parked, stalled, dead and closed seats.
 *  The pool chooses the stored harness session and reports explicit fresh starts. */
export const resumeSeat = (participantId: string, ticketId?: string | null) =>
  postJson<Record<string, unknown>>("/v1/sessions/resume", {
    participant_id: participantId,
    ticket_id: ticketId ?? null,
  });

/** POST /v1/sessions/close — the owner's Close: the pool closes the shell and the board records "closed by owner",
 *  so the close is not reported as a crash (design-63db8a7d42 G). */
export const closeSeat = (participantId: string, ticketId?: string | null) =>
  postJson<Record<string, unknown>>("/v1/sessions/close", {
    participant_id: participantId,
    ticket_id: ticketId ?? null,
  });

/** The seat choice a spawn may name (owner m-2d7ef9243d, S-ROLES): `model` is a catalog id
 *  (GET /v1/models) or a models.json seat name; `effort` low|medium|high. Omitted = the board
 *  resolves both from the ticket's EPIC (its model:<role>= / seat-effort tags, else the catalog). */
export interface SeatChoiceIn {
  model?: string | null;
  effort?: string | null;
  /** the spawned seat becomes the ticket's assignee (Seats page "Spawn seat") */
  assign?: boolean;
}

/** POST /v1/sessions/spawn — start a fresh seat for a role on a ticket (Seats "Spawn a seat",
 *  design §16). Authorisation + idempotency are the board's; the UI just names the role + ticket,
 *  plus an optional seat choice (sent only when given, so the epic's choice stays the default). */
export const spawnSeat = (role: string, participantId: string, ticketId?: string | null, choice?: SeatChoiceIn) =>
  postJson<Record<string, unknown>>("/v1/sessions/spawn", {
    role,
    participant_id: participantId,
    ticket_id: ticketId ?? null,
    ...(choice?.model ? { model: choice.model } : {}),
    ...(choice?.effort ? { effort: choice.effort } : {}),
    ...(choice?.assign ? { assign: true } : {}),
  });
