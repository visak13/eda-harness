import { describe, it, expect } from "vitest";
import type { PoolCapabilities, SeatRow } from "../api/types";
import { presenceOf, STALE_MS } from "./presence";

// The presence rule, off the clock (design §18.3, criterion c-c98b3e4319). `now` is injected so a
// "heartbeat under 60s" vs "over 60s" is exact, not timing-dependent.

const NOW = Date.parse("2026-09-08T14:24:08Z");
const base: SeatRow = {
  id: "engineer.s-1", handle: "engineer.s-1", role: "engineer", state: "alive",
  ticket_id: "s-1", ticket_title: "Read documents", last_output_at: null,
  presence_stale_since: null, reason: "", latest_status: null,
};
const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString();
const CAPS_YES: PoolCapabilities = { resume_parked: true, resume_closed: true, park: true, spawn: true };
const CAPS_NO: PoolCapabilities = { resume_parked: true, resume_closed: false, park: true, spawn: true };

describe("presenceOf", () => {
  it("alive with a heartbeat under 60s reads Working, no Resume", () => {
    const p = presenceOf({ ...base, last_output_at: iso(30_000) }, CAPS_YES, NOW);
    expect(p.word).toBe("Working");
    expect(p.dot).toBe("success");
    expect(p.showResume).toBe(false);
  });

  it("alive but silent for 60s–10min reads 'Presence not refreshed' with the last-known state", () => {
    const p = presenceOf({ ...base, last_output_at: iso(STALE_MS + 5 * 60_000) }, CAPS_YES, NOW);
    expect(p.word).toBe("Presence not refreshed");
    expect(p.detail).toMatch(/last known/i);
    expect(p.kind).toBe("stale"); // never "closed" — silence is not death
  });

  it("the board's own stale flag forces 'Presence not refreshed' even with a recent timestamp", () => {
    const p = presenceOf({ ...base, last_output_at: iso(1_000), presence_stale_since: iso(0) }, CAPS_YES, NOW);
    expect(p.word).toBe("Presence not refreshed");
  });

  it("a closed (dead) seat shows its recorded reason verbatim", () => {
    const p = presenceOf({ ...base, state: "dead", reason: "closed by self: work completed; session saved" }, CAPS_YES, NOW);
    expect(p.word).toBe("Closed");
    expect(p.detail).toBe("closed by self: work completed; session saved");
  });

  it("Resume on a closed seat depends on the pool: shown when resume_closed, hidden otherwise", () => {
    const dead: SeatRow = { ...base, state: "dead", reason: "reaped" };
    expect(presenceOf(dead, CAPS_YES, NOW).showResume).toBe(true);
    expect(presenceOf(dead, CAPS_NO, NOW).showResume).toBe(false);
  });

  it("a parked seat reads Parked and offers Resume by default", () => {
    const p = presenceOf({ ...base, state: "parked", reason: "waiting on evidence" }, CAPS_YES, NOW);
    expect(p.word).toBe("Parked");
    expect(p.dot).toBe("accentink");
    expect(p.showResume).toBe(true);
  });

  it("a seat with no mirrored session reads 'Availability unknown', never a death", () => {
    const p = presenceOf({ ...base, state: null }, CAPS_YES, NOW);
    expect(p.word).toBe("Availability unknown");
    expect(p.showResume).toBe(false);
  });
});
