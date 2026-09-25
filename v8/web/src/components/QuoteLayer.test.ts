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

describe("the quote chord (C20 ruling m-db0d013529)", () => {
  const k = (o: Partial<KeyboardEvent>) => ({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, key: "", code: "", ...o });
  it("is Ctrl+Alt+Q only; Ctrl+Shift+Q is not bound", async () => {
    const { isQuoteKey } = await import("./QuoteLayer");
    expect(isQuoteKey(k({ ctrlKey: true, altKey: true, key: "q", code: "KeyQ" }))).toBe(true);
    expect(isQuoteKey(k({ ctrlKey: true, altKey: true, key: "@", code: "KeyQ" }))).toBe(true); // AltGr layouts: handled by isTyping + a selection
    expect(isQuoteKey(k({ ctrlKey: true, shiftKey: true, key: "Q", code: "KeyQ" }))).toBe(false);
    expect(isQuoteKey(k({ ctrlKey: true, altKey: true, shiftKey: true, key: "Q", code: "KeyQ" }))).toBe(false);
    expect(isQuoteKey(k({ ctrlKey: true, key: "q", code: "KeyQ" }))).toBe(false);
  });
  it("never fires from a text field", async () => {
    const { isTyping } = await import("./QuoteLayer");
    expect(isTyping(document.createElement("textarea"))).toBe(true);
    expect(isTyping(document.createElement("input"))).toBe(true);
    expect(isTyping(document.createElement("p"))).toBe(false);
    expect(isTyping(null)).toBe(false);
  });
});
