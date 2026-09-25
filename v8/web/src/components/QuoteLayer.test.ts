import { describe, expect, it } from "vitest";
import { resolvePick } from "./QuoteLayer";

describe("resolvePick (message)", () => {
  it("gives the board code-point offsets, not UTF-16 units (Python slices by code point)", async () => {
    const text = "\u{1F600} hello world";
    const r = await resolvePick({ region: { kind: "message", id: "m-1", text }, selected: "hello", before: "\u{1F600} " }, "");
    if ("error" in r) throw new Error(r.error);
    expect(r.quote.locator).toEqual({ char_start: 2, char_end: 7 });
    expect(Array.from(text).slice(2, 7).join("")).toBe("hello");
  });
});
