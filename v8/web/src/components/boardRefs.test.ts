import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { activeRef, boardRows, rankRefs, refHref, refIds, refKind, refLabel, refToken, scopeRows, splitRefs, type RefRow } from "./boardRefs";

// C24: the $-reference contract, read from the one fixture the extension's tests read too.
const fixture = JSON.parse(readFileSync(resolve(__dirname, "../../../tests/fixtures/ref_cases.json"), "utf-8")) as {
  trigger: { text: string; expect: string | null }[];
  split: { text: string; expect: [string, string | null][] }[];
};

describe("$ trigger contract", () => {
  for (const c of fixture.trigger) {
    it(JSON.stringify(c.text), () => {
      const caret = c.text.indexOf("|");
      const text = c.text.replace("|", "");
      const hit = activeRef(text, caret);
      expect(hit?.query ?? null).toBe(c.expect);
      if (hit) expect(text.slice(hit.start, caret)).toBe(`$${hit.query}`);
    });
  }
});

describe("$ chip contract", () => {
  for (const c of fixture.split) {
    it(JSON.stringify(c.text), () => {
      const refs = splitRefs(c.text).filter((p) => typeof p !== "string") as { id: string; label: string | null }[];
      expect(refs.map((r) => [r.id, r.label])).toEqual(c.expect);
      expect(splitRefs(c.text).map((p) => (typeof p === "string" ? p : `$${p.id}${p.label ? ` (${p.label})` : ""}`)).join("")).toBe(c.text);
    });
  }
  it("code spans never render chips", () => {
    expect(refIds("`$s-5d1b171d57` and ```\n$dec-bf6aab8b73\n``` but $epic-52edacd059")).toEqual(["epic-52edacd059"]);
  });
});

const row = (id: string, title: string): RefRow => ({ id, kind: refKind(id)!, title, group: "scope" });

describe("ranking", () => {
  const scope = [row("s-aaaaaaaaaa", "C20 VS Code quotes"), row("s-bbbbbbbbbb", "C24 $-references"), row("design-cccccccccc", "EDP chat design"), row("dec-dddddddddd", "C2 ruling on trailers")];
  const board = [{ ...row("epic-eeeeeeeeee", "C2 other epic"), group: "board" as const }, { ...row("s-bbbbbbbbbb", "dup of a scope row"), group: "board" as const }];

  it("puts the current scope first, then the board, without duplicates", () => {
    const out = rankRefs("C2", scope, board);
    expect(out.map((r) => [r.id, r.group])).toEqual([
      ["s-aaaaaaaaaa", "scope"], ["s-bbbbbbbbbb", "scope"], ["dec-dddddddddd", "scope"], ["epic-eeeeeeeeee", "board"],
    ]);
  });
  it("ranks an id prefix before a title match", () => {
    expect(rankRefs("design", scope, [])[0].id).toBe("design-cccccccccc");
  });
  it("word-start title matches beat substrings", () => {
    const out = rankRefs("quo", [row("s-1111111111", "misquoted"), row("s-2222222222", "VS Code quotes")], []);
    expect(out.map((r) => r.id)).toEqual(["s-2222222222", "s-1111111111"]);
  });
  it("caps the list", () => {
    const many = Array.from({ length: 30 }, (_, i) => row(`s-${String(i).padStart(10, "0")}`, `C2 item ${i}`));
    expect(rankRefs("c2", many, [])).toHaveLength(12);
  });
});

describe("insertion", () => {
  it("inserts the id and the title as the label", () => {
    expect(refToken({ id: "s-5d1b171d57", title: "C24 $-references" })).toBe("$s-5d1b171d57 (C24 $-references) ");
  });
  it("the label never mentions anyone, never breaks the parens, stays short", () => {
    expect(refLabel("Quote notes take @mentions (C23)")).toBe("Quote notes take ＠mentions C23");
    expect(refLabel("x".repeat(100))).toHaveLength(60);
    expect(refLabel("a\n  b")).toBe("a b");
  });
  it("round-trips: what is inserted renders as one chip with its label", () => {
    const text = `see ${refToken({ id: "dec-bf6aab8b73", title: "C3 no longer waits (on S6)" })}ok`;
    const parts = splitRefs(text).filter((p) => typeof p !== "string");
    expect(parts).toEqual([{ id: "dec-bf6aab8b73", kind: "decision", label: "C3 no longer waits on S6" }]);
  });
});

describe("targets", () => {
  it("tickets and epics get their page, docs the drawer, decisions the History drawer", () => {
    expect(refHref("epic-52edacd059", "epic", "/ticket/s-1")).toBe("/epic/epic-52edacd059");
    expect(refHref("s-5d1b171d57", "story", "/epic/e")).toBe("/ticket/s-5d1b171d57");
    expect(refHref("design-10b21760d9", "design", "/ticket/s-1")).toBe("/ticket/s-1?doc=design-10b21760d9");
    expect(refHref("dec-bf6aab8b73", "decision", "/ticket/s-1")).toBe("/ticket/s-1?view=history&category=decisions");
  });
});

describe("rows from the board's routes", () => {
  it("scope: tickets, the four doc kinds, live decisions", () => {
    const out = scopeRows(
      [{ id: "epic-52edacd059", title: "E" }, { id: "s-5d1b171d57", title: "S" }],
      [{ id: "design-10b21760d9", title: "D" }, { id: "note-23c452b368", title: "plan" }],
      [{ id: "dec-bf6aab8b73", text: "live one", status: "live" }, { id: "dec-0000000000", text: "gone", status: "withdrawn" }],
    );
    expect(out.map((r) => [r.id, r.kind])).toEqual([["epic-52edacd059", "epic"], ["s-5d1b171d57", "story"], ["design-10b21760d9", "design"], ["dec-bf6aab8b73", "decision"]]);
  });
  it("board: open epics and open tickets only, decisions titled by their text", () => {
    const out = boardRows(
      [{ type: "ticket", id: "s-1111111111", title: "open", status: "ready" }, { type: "ticket", id: "s-2222222222", title: "closed", status: "done" },
        { type: "decision", id: "dec-3333333333", snippet: "the [ruling] text" }, { type: "message", id: "m-4444444444" }],
      [{ id: "epic-5555555555", title: "live epic", status: "in_progress" }, { id: "epic-6666666666", title: "old", status: "done" }],
    );
    expect(out.map((r) => [r.id, r.title])).toEqual([["epic-5555555555", "live epic"], ["s-1111111111", "open"], ["dec-3333333333", "the ruling text"]]);
  });
});
