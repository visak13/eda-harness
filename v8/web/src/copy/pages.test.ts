import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PAGES, SIDEBAR, RULES, copyItem, copyProps, pageKeyFor } from "./pages";

// The UI copy contract (human defect #31, note-8be9cd1f31): every SPA route has a page entry with
// a framing sentence and at least one control, every entry is verbatim non-empty copy, and a
// control key without copy fails loudly (copyProps throws) rather than rendering a blank tooltip.
describe("UI copy contract", () => {
  it("every route in routes.tsx (the table main.tsx mounts) maps to a page with framing and controls", () => {
    const main = readFileSync(resolve(__dirname, "../routes.tsx"), "utf-8");
    const paths = [...main.matchAll(/path: "([^"*]+)"/g)].map((m) => "/" + m[1].replace(":id", "x-1"));
    expect(paths.length).toBeGreaterThan(5);
    for (const p of paths) {
      const page = PAGES[pageKeyFor(p)];
      expect(page, `route ${p} has no copy page`).toBeTruthy();
      expect(page.framing.length, `${page.key} framing`).toBeGreaterThan(20);
      expect(page.items.some((i) => i.control), `${page.key} has no control copy`).toBe(true);
    }
  });

  it("every item carries verbatim, non-empty copy", () => {
    for (const p of [SIDEBAR, ...Object.values(PAGES)]) {
      for (const i of p.items) {
        expect(i.label.trim().length, `${p.key}.${i.key} label`).toBeGreaterThan(0);
        expect(i.text.trim().length, `${p.key}.${i.key} text`).toBeGreaterThan(10);
      }
    }
    expect(RULES.length).toBe(2);
  });

  it("copyProps gives tooltip + aria-describedby, and throws on a control without copy", () => {
    const p = copyProps("epic", "steer");
    expect(p.title).toContain("Wakes: the architect always");
    expect(p["aria-describedby"]).toBe("copy-epic-steer");
    expect(() => copyItem("epic", "nonexistent")).toThrow(/no UI copy for epic.nonexistent/);
  });
});
