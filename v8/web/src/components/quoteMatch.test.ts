import { describe, expect, it } from "vitest";
import { contextOf, findRendered, linesOf, locateInSource, projectMarkdown } from "./quoteMatch";

// The board's own check (edp8/quotes.py): " ".join(s.split()) of the passage must occur in the same
// normalisation of the cited source. Every located slice below must pass it.
const norm = (s: string) => s.split(/\s+/).filter(Boolean).join(" ");
function verifies(src: string, text: string): boolean {
  return norm(src).includes(norm(text));
}

const DOC = [
  "# Design",                                   // 1
  "",                                           // 2
  "## 14.5 Quotes",                             // 3
  "The board **validates** each quote: the text must occur in that source.", // 4
  "",                                           // 5
  "- `source`: `doc` | `message` | `code`.",    // 6
  "- For `doc`: `id` and `version`.",           // 7
  "",                                           // 8
  "See [the plan](https://example.com/p) and \\*stars\\*.", // 9
  "",                                           // 10
  "| story | blocked by |",                     // 11
  "|---|---|",                                  // 12
  "| C19 | C18 |",                              // 13
  "",                                           // 14
  "Fish &amp; chips repeat. Fish &amp; chips repeat.", // 15
].join("\n");

describe("locateInSource", () => {
  it("finds rendered text through bold markup and returns the verbatim source slice", () => {
    const span = locateInSource(DOC, "The board validates each quote")!;
    expect(span.text).toBe("The board **validates** each quote");
    expect(verifies(DOC, span.text)).toBe(true);
    expect(linesOf(DOC, span)).toEqual({ line_start: 4, line_end: 4 });
  });

  it("spans list items (bullets and code spans are not rendered text)", () => {
    const span = locateInSource(DOC, "source: doc | message | code.\nFor doc: id and version.")!;
    expect(span).not.toBeNull();
    expect(span.text).toBe("source`: `doc` | `message` | `code`.\n- For `doc`: `id` and `version`.");
    expect(linesOf(DOC, span)).toEqual({ line_start: 6, line_end: 7 });
    expect(verifies(DOC, span.text)).toBe(true);
  });

  it("skips link targets and backslash escapes", () => {
    const span = locateInSource(DOC, "See the plan and *stars*")!;
    // the closing escaped star is syntax on both sides, so the slice ends at "stars": still verbatim
    expect(span.text).toBe("See [the plan](https://example.com/p) and \\*stars");
    expect(verifies(DOC, span.text)).toBe(true);
  });

  it("matches table cells across rows (pipes and the separator row are structure)", () => {
    const span = locateInSource(DOC, "story\tblocked by\nC19\tC18")!;
    expect(linesOf(DOC, span)).toEqual({ line_start: 11, line_end: 13 });
    expect(verifies(DOC, span.text)).toBe(true);
  });

  it("maps an entity to the character it renders and picks the n-th repeat from the text before", () => {
    const first = locateInSource(DOC, "Fish & chips repeat")!;
    const second = locateInSource(DOC, "Fish & chips repeat", "… see the table … Fish & chips repeat. ")!;
    expect(first.text).toBe("Fish &amp; chips repeat");
    expect(second.start).toBeGreaterThan(first.start);
    expect(second.text).toBe("Fish &amp; chips repeat");
  });

  it("returns null for text the source does not hold", () => {
    expect(locateInSource(DOC, "not in the design at all")).toBeNull();
    expect(locateInSource(DOC, "   ")).toBeNull();
  });

  it("works on a message's plain text (the char range is the board's locator)", () => {
    const msg = "quote once, quote multiple times. **quote with context**. this just is sugar";
    const span = locateInSource(msg, "quote with context. this just")!;
    expect(msg.slice(span.start, span.end)).toBe(span.text);
    expect(span.text).toBe("quote with context**. this just");
  });
});

describe("projectMarkdown", () => {
  it("drops fences, rules and heading markers but keeps code inside the fence", () => {
    const p = projectMarkdown("### Title\n```ts\nconst x = 1;\n```\n---\ntext");
    expect(p.chars).toBe("Titleconstx=1;text");
  });
});

describe("contextOf / findRendered", () => {
  it("gives the nearest non-blank lines within reach", () => {
    expect(contextOf(DOC, 6, 7)).toEqual({ before: "The board **validates** each quote: the text must occur in that source.", after: "See [the plan](https://example.com/p) and \\*stars\\*." });
    expect(contextOf(DOC, 1, 1).before).toBe("");
  });

  it("finds the rendered passage of a line range", () => {
    const rendered = "Design\n14.5 Quotes\nThe board validates each quote: the text must occur in that source.\nsource: doc | message | code.";
    const r = findRendered(rendered, DOC, 4, 4)!;
    expect(rendered.slice(r.start, r.end)).toBe("The board validates each quote: the text must occur in that source.");
    expect(findRendered(rendered, DOC, 15, 15)).toBeNull();
  });
});
