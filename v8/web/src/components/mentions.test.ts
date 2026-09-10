import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mentionedHandles } from "./mentions";

// The shared mention-tokeniser contract (adversary round 2 #6): the same cases the board test
// (tests/test_mentions_contract.py) runs, read from the one fixture at the repo root.
const fixture = JSON.parse(readFileSync(resolve(__dirname, "../../../tests/fixtures/mention_cases.json"), "utf-8")) as {
  handles: string[];
  cases: { text: string; expect: string[] }[];
};

describe("mention tokeniser contract", () => {
  const people = fixture.handles.map((h) => ({ handle: h, id: h === "bob" ? "human-b" : h }));
  for (const c of fixture.cases) {
    it(JSON.stringify(c.text), () => {
      expect(mentionedHandles(c.text, people)).toEqual(c.expect);
    });
  }
});
