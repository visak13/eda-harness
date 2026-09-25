import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mentionedHandles, mentionTokens, previewMentionText } from "./mentions";

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

describe("previewMentionText (C23)", () => {
  // the board's fence rule (board.py _FENCE_RX): an open fence runs to the END of its text
  const boardVisible = (t: string) => mentionTokens(t.replace(/```[\s\S]*?(?:```|$)/g, " "));
  it("joins text and notes; an open fence in one source cannot swallow a later mention", () => {
    expect(previewMentionText("hi", [])).toBe("hi");
    const t = previewMentionText("```\nunclosed", ["@vishal look", undefined, "```open", "@tokuser"]);
    expect(boardVisible(t)).toEqual(["vishal", "tokuser"]);
    expect(boardVisible("```\nunclosed\n\n@vishal look")).toEqual([]); // the naive join hid it
  });
});
