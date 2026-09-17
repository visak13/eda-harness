// G3b-owned endpoint functions for the Seats page (design §4.2, §18.3). Kept in its own module so
// it never collides with G2's decisions.ts or G3a's endpoints.ts during the parallel build (G4
// folds all three into one endpoints.ts). Reads unwrap via api<T>(); the pool actions go through
// postJson so the board's plain-sentence error (pool down, not permitted) is read verbatim.
import { api, postJson } from "./client";
import type { PoolCapabilities, SeatsView } from "./types";

export const getSeats = () => api<SeatsView>("/v1/seats");

/** GET /v1/pool/capabilities — read live what the pool can do; the UI shows Resume/Spawn only
 *  when the pool reports it (design §18.3, §21.4). Pool down → every capability false + a reason. */
export const getPoolCapabilities = () => api<PoolCapabilities>("/v1/pool/capabilities");

/** POST /v1/sessions/resume — resume a parked or (per capabilities) closed seat from its stored
 *  session (design §18.3). The board picks resume vs resume-from-closed by the pool row's state. */
export const resumeSeat = (participantId: string, ticketId?: string | null) =>
  postJson<Record<string, unknown>>("/v1/sessions/resume", {
    participant_id: participantId,
    ticket_id: ticketId ?? null,
  });

/** The seat choice a spawn may name (owner m-2d7ef9243d): `model` is a models.json seat name
 *  ("claude" = the Claude roles column, "astra" = GPT-6 Astra on Pi); `effort` low|medium|high.
 *  Omitted = the board resolves both from the ticket's EPIC (its seat-model/seat-effort tags). */
export interface SeatChoiceIn {
  model?: string | null;
  effort?: string | null;
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
  });
