import { afterEach, describe, expect, it, vi } from "vitest";
import { readFlag, writeFlag } from "./viewerPrefs";

// S17: per-viewer collapse state — keyed by viewer, and a throwing storage never breaks the page.
describe("viewerPrefs", () => {
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

  it("remembers a flag per viewer and key", () => {
    writeFlag("owner", "rail-collapsed", true);
    expect(readFlag("owner", "rail-collapsed")).toBe(true);
    expect(readFlag("someone-else", "rail-collapsed")).toBe(false);
    expect(localStorage.getItem("edp8.ui.owner.rail-collapsed")).toBe("1");
    writeFlag("owner", "rail-collapsed", false);
    expect(readFlag("owner", "rail-collapsed", true)).toBe(false);
  });

  it("falls back to the default when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(readFlag("owner", "composer-collapsed", true)).toBe(true);
    expect(() => writeFlag("owner", "composer-collapsed", false)).not.toThrow();
  });
});
