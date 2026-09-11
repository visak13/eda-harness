import { expect, test, type Locator, BASE } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
import { seedEpic, type G3aFixture } from "./g3a.seed";
import { GEOMETRY } from "./geometry";

test.use({ boardFile: "g3a-fidelity" }); // one fresh board per spec file (fixtures.ts)

// G3a fidelity + accessibility (c-a23e72f460): at 1440×900 the epic page matches the Folio plate
// (744/336 split, gap 64, Georgia 38 title, Georgia 22 owner's-words quote, accentwash+3px-rule
// directive, 3px tab underline, 40px steer button), and every destination is axe-clean across the
// four themes.
const ACCENTINK = "rgb(135, 63, 56)"; // #873F38
const THEMES = ["folio", "dusk", "ember", "folio-hc"] as const;
let fx: G3aFixture;

test.beforeAll(async () => {
  fx = await seedEpic();
});

const style = (loc: Locator, prop: string) =>
  loc.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

test.describe("epic page fidelity @ 1440×900", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("split geometry, type scale, directive rule, tab underline and steer button", async ({ page }) => {
    await page.goto(`${BASE()}/ui/epic/${fx.epic}?as=owner`);
    await expect(page.getByTestId("directive")).toBeVisible();

    // Two-column split: main content 744, rail 336, gap 64.
    const rail = page.getByRole("complementary", { name: "Epic details" });
    const rb = (await rail.boundingBox())!;
    expect(Math.abs(rb.width - GEOMETRY.homeGrid.right)).toBeLessThan(1);
    const mainCol = page.getByRole("tablist").locator("..");
    const mb = (await mainCol.boundingBox())!;
    expect(Math.abs(mb.width - GEOMETRY.homeGrid.left)).toBeLessThan(1);
    expect(Math.abs(rb.x - (mb.x + mb.width) - GEOMETRY.homeGrid.gap)).toBeLessThan(1);

    // Title Georgia 38; owner's-words request Georgia 26/32 (Astra #36 item 1, ruling m-5887eb1a20,
    // supersedes the 22px quote named in c-a23e72f460 — the criterion text awaits the architect's reword).
    const h1 = page.locator("main h1");
    expect(await style(h1, "font-family")).toContain(GEOMETRY.type.h1.family);
    expect(await style(h1, "font-size")).toBe(`${GEOMETRY.type.h1.px}px`);
    const quote = page.getByTestId("owner-words-text");
    expect(await style(quote, "font-family")).toContain(GEOMETRY.type.h1.family);
    expect(await style(quote, "font-size")).toBe("26px");

    // Directive callout: accentwash ground + 3px accentink left rule.
    const directive = page.getByTestId("directive");
    expect(await style(directive, "border-left-width")).toBe("3px");
    expect(await style(directive, "border-left-color")).toBe(ACCENTINK);

    // Active tab underline: a 3px accentink ::after rule.
    const under = await page.evaluate(() => {
      const el = document.querySelector("[role='tab'][aria-selected='true']")!;
      const s = getComputedStyle(el, "::after");
      return { h: s.height, bg: s.backgroundColor };
    });
    expect(under.h).toBe(`${GEOMETRY.tabUnderline}px`);
    expect(under.bg).toBe(ACCENTINK);

    // Steer button 40px tall.
    const steer = page.getByRole("button", { name: "Steer this epic" });
    const stb = (await steer.boundingBox())!;
    expect(Math.abs(stb.height - GEOMETRY.button.h)).toBeLessThan(1);
  });
});

test.describe("accessibility across the four themes", () => {
  for (const theme of THEMES) {
    test(`${theme}: epic, ticket, doc and library are axe-clean (no serious/critical)`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("edp8.theme", t), theme);
      for (const path of [
        `/ui/epic/${fx.epic}?as=owner`,
        `/ui/ticket/${fx.story}?as=owner`,
        `/ui/doc/${fx.doc}?as=owner`,
        `/ui/library/tickets?as=owner`,
      ]) {
        await page.goto(`${BASE()}${path}`);
        await expect(page.locator("main h1")).toBeVisible();
        // @axe-core/playwright pins its own playwright-core copy, so its Page type is nominally a
        // different structural type than @playwright/test's Page here — the same object at runtime.
        // @ts-expect-error dual playwright-core type identities
        const results = await new AxeBuilder({ page }).analyze();
        const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(bad, `${theme} ${path}: ${bad.map((v) => v.id).join(", ")}`).toEqual([]);
      }
    });
  }
});
