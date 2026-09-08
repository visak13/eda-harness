import { expect, test, type Locator } from "@playwright/test";

// Criterion c-fee415dda3: at 1440×900 the shell geometry, tokens, type and focus ring
// match the Folio plate (design §4.2, board-concepts-r2/source/design.css `.folio`).
const BASE = process.env.EDP8_E2E_BASE!;

// Folio (default theme) token colours as the browser reports them.
const RAIL = "rgb(238, 229, 216)"; // #EEE5D8
const PANEL = "rgb(255, 253, 248)"; // #FFFDF8
const ACCENTINK = "rgb(135, 63, 56)"; // #873F38

const style = (loc: Locator, prop: string) =>
  loc.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

test.describe("shell fidelity @ 1440×900", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("sidebar / header / main geometry, rail token, active nav, h1, focus ring", async ({ page }) => {
    await page.goto(`${BASE}/app/me?as=owner`);

    // Sidebar: x=0, width 216, background = the rail token.
    const sidebar = page.locator("aside");
    const sb = (await sidebar.boundingBox())!;
    expect(sb.x).toBeLessThan(1);
    expect(Math.abs(sb.width - 216)).toBeLessThan(1);
    expect(await style(sidebar, "background-color")).toBe(RAIL);

    // Header: height 72, starting at x=216.
    const header = page.getByTestId("app-header");
    const hb = (await header.boundingBox())!;
    expect(Math.abs(hb.x - 216)).toBeLessThan(1);
    expect(Math.abs(hb.height - 72)).toBeLessThan(1);

    // Main: x=256, width 1144.
    const main = page.locator("main");
    const mb = (await main.boundingBox())!;
    expect(Math.abs(mb.x - 256)).toBeLessThan(1);
    expect(Math.abs(mb.width - 1144)).toBeLessThan(1);

    // Active nav row (Decisions on /me): 43px tall, on the panel colour, icon in accentink.
    const active = page.locator("a[aria-current='page']");
    const ab = (await active.boundingBox())!;
    expect(Math.abs(ab.height - 43)).toBeLessThan(1);
    expect(await style(active, "background-color")).toBe(PANEL);
    expect(await style(active.locator("[data-nav-icon] svg"), "color")).toBe(ACCENTINK);

    // Page h1: Georgia 38px.
    const h1 = page.locator("main h1");
    expect(await style(h1, "font-family")).toContain("Georgia");
    expect(await style(h1, "font-size")).toBe("38px");

    // Focus ring on a nav link: 2px accentink, offset 3px. Keyboard focus so :focus-visible
    // engages (the first Tab lands on the Decisions link, first focusable in the DOM).
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const s = getComputedStyle(el);
      return {
        text: el.textContent ?? "",
        width: s.outlineWidth,
        color: s.outlineColor,
        offset: s.outlineOffset,
      };
    });
    expect(ring.text).toContain("Decisions");
    expect(ring.width).toBe("2px");
    expect(ring.offset).toBe("3px");
    expect(ring.color).toBe(ACCENTINK);
  });
});
