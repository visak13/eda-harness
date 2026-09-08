import { describe, it, expect } from "vitest";
import {
  TICKET_STATUSES,
  TICKET_KINDS,
  WORK_TYPES,
  GATE_KINDS,
  MESSAGE_KINDS,
  ROLES,
  CHECKS,
  VERDICTS,
  SESSION_STATES,
} from "../api/types";
import * as types from "../api/types";
import { GLOSSARY, REQUIRED_COVERAGE, term, label, meaning } from "./glossary";

// The table test that makes the glossary a contract (design §15, criterion c-581d50496d): every
// value of every board enum in api/types.ts has a label AND a one-line meaning, and dropping one
// turns this red NAMING the missing key.

describe("glossary coverage", () => {
  // One row per (category, enum array). If REQUIRED_COVERAGE drifts from the enum arrays this
  // itself fails, so the test cannot silently stop covering a category.
  const cases: Array<[string, readonly string[]]> = [
    ["ticket_status", TICKET_STATUSES],
    ["ticket_kind", TICKET_KINDS],
    ["work_type", WORK_TYPES],
    ["gate", GATE_KINDS],
    ["message_kind", MESSAGE_KINDS],
    ["role", ROLES],
    ["check", CHECKS],
    ["verdict", VERDICTS],
    ["session_state", SESSION_STATES],
  ];

  it.each(cases)("every %s value has a label and a one-line meaning", (category, values) => {
    for (const value of values) {
      const entry = term(category as never, value);
      // The failure message names the exact missing key, so a red run points straight at it.
      expect(entry, `glossary is missing key: ${category}.${value}`).toBeDefined();
      expect(entry!.label.length, `${category}.${value} has an empty label`).toBeGreaterThan(0);
      const words = entry!.meaning.trim().split(/\s+/);
      expect(words.length, `${category}.${value} meaning must be a real sentence`).toBeGreaterThanOrEqual(3);
      // "one-line": a single sentence, not a paragraph.
      expect(entry!.meaning, `${category}.${value} meaning must be one line`).not.toContain("\n");
    }
  });

  it("REQUIRED_COVERAGE lists exactly the board-enum categories the criterion names", () => {
    expect(REQUIRED_COVERAGE.map(([c]) => c)).toEqual(cases.map(([c]) => c));
  });

  // The real guard against the S15 hole the second-opinion caught (SESSION_STATES shipped unglossed):
  // don't hand-list the enums — DISCOVER every string-enum array exported by api/types.ts and prove
  // each is one that REQUIRED_COVERAGE actually covers. A new enum array added to types.ts turns this
  // red until it is glossed, by array identity, so a subset that "asserts itself" can't hide a gap.
  it("every string-enum array exported by api/types.ts is covered by REQUIRED_COVERAGE", () => {
    const covered = new Set<readonly string[]>(REQUIRED_COVERAGE.map(([, arr]) => arr));
    const enumArrays = Object.entries(types).filter(
      ([name, v]) =>
        name === name.toUpperCase() &&
        Array.isArray(v) &&
        v.length > 0 &&
        (v as unknown[]).every((x) => typeof x === "string"),
    );
    const uncovered = enumArrays
      .filter(([, arr]) => !covered.has(arr as readonly string[]))
      .map(([name]) => name);
    expect(uncovered, `enum arrays in api/types.ts with no glossary coverage: ${uncovered.join(", ")}`).toEqual([]);
  });

  it("fails NAMING the missing key when an entry is removed (proves it pins, not just runs)", () => {
    // Simulate a dropped key on a copy of the table; the guard must throw naming ticket_status.ready.
    const check = (t: typeof GLOSSARY) => {
      const missing: string[] = [];
      for (const [category, values] of REQUIRED_COVERAGE) {
        for (const value of values) if (!t[category]?.[value]) missing.push(`${category}.${value}`);
      }
      if (missing.length) throw new Error(`glossary is missing keys: ${missing.join(", ")}`);
    };
    const broken = { ...GLOSSARY, ticket_status: { ...GLOSSARY.ticket_status } };
    delete (broken.ticket_status as Record<string, unknown>).ready;
    expect(() => check(broken)).toThrow(/ticket_status\.ready/);
    expect(() => check(GLOSSARY)).not.toThrow();
  });

  it("label() and meaning() fall back to the de-underscored raw value, never a blank", () => {
    expect(label("ticket_status", "in_progress")).toBe("In progress");
    expect(label("ticket_status", "unknown_future_state")).toBe("unknown future state");
    expect(meaning("ticket_status", "unknown_future_state")).toBeUndefined();
    expect(label("verdict", "fail")).toBe("Needs work"); // the plain word, never "fail"
  });
});
