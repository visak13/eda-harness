import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ACTION_GLOSS, PAGES, SIDEBAR, RULES, actionGloss, copyItem, copyProps, pageKeyFor } from "./pages";

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

  it("S12-ui2: every Actions gloss is one plain sentence (capital, full stop, no status names or field lists)", () => {
    for (const [page, items] of Object.entries(ACTION_GLOSS)) {
      for (const [key, text] of Object.entries(items)) {
        expect(text, `${page}.${key}`).toMatch(/^[A-Z][^]*\.$/);
        expect(text, `${page}.${key}`).not.toMatch(/_|raw status|design link|\/|\(|;/);
        expect(text.length, `${page}.${key}`).toBeLessThan(80);
        expect(actionGloss(page as "epic" | "ticket", key)).toBe(text);
      }
    }
    expect(ACTION_GLOSS.ticket["change-status"]).toBe("Move this ticket to its next step.");
    expect(() => actionGloss("epic", "nonexistent")).toThrow(/no Actions gloss/);
  });

  it("copyProps gives tooltip + aria-describedby, and throws on a control without copy", () => {
    const p = copyProps("epic", "steer");
    expect(p.title).toContain("Wakes: the architect always");
    expect(p["aria-describedby"]).toBe("copy-epic-steer");
    expect(() => copyItem("epic", "nonexistent")).toThrow(/no UI copy for epic.nonexistent/);
  });
});
