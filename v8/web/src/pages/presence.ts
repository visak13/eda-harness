import type { SeatRow, PoolCapabilities } from "../api/types";

// The presence rule (design §18.3, criterion c-c98b3e4319), as ONE pure function so it is unit
// tested off the clock, not eyeballed. The cardinal rule: silence is NEVER rendered as death — a
// seat we last heard from long ago reads "Presence not refreshed" with its last-known state, never
// "Closed". A seat only reads Closed when the board actually recorded it closed (state dead + a
// reason). A seat with no session mirrored here is a remote seat: "Availability unknown".

export const STALE_MS = 60_000; // 60s without a fresh heartbeat → presence not refreshed

export type PresenceKind = "working" | "parked" | "stalled" | "closed" | "stale" | "unknown";

export interface Presence {
  kind: PresenceKind;
  /** The plain word shown as the seat's state (never colour alone — design §4.2). */
  word: string;
  /** Dot colour hint: success (alive/working), accentink (parked), muted (everything else). */
  dot: "success" | "accentink" | "muted";
  /** A second line: the closing reason (closed) or the last-known state (stale). */
  detail?: string;
  /** Whether a Resume action is offered, given what the pool reports it can do. */
  showResume: boolean;
}

function ageMs(iso: string | null, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : now - t;
}

export function presenceOf(
  seat: SeatRow,
  caps: PoolCapabilities | undefined,
  now: number = Date.now(),
): Presence {
  const canResumeClosed = caps?.resume_closed === true;
  // Never assumed (c-3831aad362): Resume shows only when the pool has REPORTED it can resume — so a
  // parked seat offers no Resume while capabilities are still loading or the pool is silent.
  const canResumeParked = caps?.resume_parked === true;

  // No mirrored session: a remote seat we cannot see. Never a death.
  if (seat.state == null) {
    return { kind: "unknown", word: "Availability unknown", dot: "muted", showResume: false };
  }

  if (seat.state === "dead") {
    return {
      kind: "closed",
      word: "Closed",
      dot: "muted",
      detail: seat.reason || undefined,
      // Resume a closed seat only when the pool reports resume-from-closed; otherwise the row
      // explains that the owner shell must spawn a fresh seat (design §18.3, §21.4).
      showResume: canResumeClosed,
    };
  }

  if (seat.state === "parked") {
    return {
      kind: "parked",
      word: "Parked",
      dot: "accentink",
      detail: seat.reason || undefined,
      showResume: canResumeParked,
    };
  }

  if (seat.state === "stalled") {
    return { kind: "stalled", word: "Stalled", dot: "muted", detail: seat.reason || undefined, showResume: false };
  }

  // Alive: fresh within 60s → Working; else Presence not refreshed with the last-known state.
  // The board's own stale flag forces the same, whatever the timestamps say.
  const age = ageMs(seat.last_output_at, now);
  const stale = seat.presence_stale_since != null || age == null || age >= STALE_MS;
  if (stale) {
    return {
      kind: "stale",
      word: "Presence not refreshed",
      dot: "muted",
      detail: "last known: Working",
      showResume: false,
    };
  }
  return { kind: "working", word: "Working", dot: "success", showResume: false };
}
