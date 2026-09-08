import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page, BASE } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { GEOMETRY } from "./geometry";

test.use({ boardFile: "g2-fidelity" }); // one fresh board per spec file (fixtures.ts)

// G2 geometry + a11y, proven at 1440×900 through the real Folio shell (design §4.2/§6/§14):
//   c-f7b9e7983c: home grid 744/336 gap 64, featured padding 23 + 3px salmon top rule + Georgia
//     27px title, 'Review evidence' 40px ink-on-accent, tab underline 3px accentink; axe clean
//     on Decisions in all four themes.
//   c-03436484b6: ruling drawer 1112 wide, top 20, right edge 1420, radius 12, header 73; panes
//     650/462; both buttons 40px; Georgia 31px evidence title; sidebar + queue visible behind the
//     dim; Tab cycles inside the drawer; axe clean in all four themes.
const THEMES = ["folio", "dusk", "ember", "folio-hc"] as const;

const box = async (loc: Locator) => (await loc.boundingBox())!;
const style = (loc: Locator, prop: string) =>
  loc.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

/** Resolve a CSS custom property to the rgb the browser paints, via a throwaway probe. */
async function token(page: Page, name: string): Promise<string> {
  return page.evaluate((n) => {
    const el = document.createElement("span");
    el.style.color = `var(${n})`;
    document.body.appendChild(el);
    const rgb = getComputedStyle(el).color;
    el.remove();
    return rgb;
  }, name);
}

async function setTheme(page: Page, theme: string) {
  await page.evaluate((t) => {
    document.documentElement.dataset.theme = t;
  }, theme);
}

async function axeClean(page: Page, selector: string) {
  // AxeBuilder resolves a nested playwright-core Page type; cast across the dual-package boundary.
  const results = await new AxeBuilder({ page: page as never }).include(selector).analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id} (${v.impact})`)).toEqual([]);
}

test.use({ viewport: { width: 1440, height: 900 } });

test.describe("Decisions home geometry + a11y", () => {
  test.beforeEach(async ({ page }) => {
    await seedDecisions();
    await page.goto(`${BASE()}/ui/me?as=owner`);
    await expect(page.getByTestId("featured-signoff")).toBeVisible();
  });

  test("grid 744/336 gap 64, featured 23/salmon/Georgia-27, button 40 ink-on-accent, tab underline 3px", async ({
    page,
  }) => {
    // Two-column grid: 744 + 336 with a 64px gap.
    const cols = await style(page.getByTestId("decisions"), "grid-template-columns");
    expect(cols).toBe(`${GEOMETRY.homeGrid.left}px ${GEOMETRY.homeGrid.right}px`);
    expect(await style(page.getByTestId("decisions"), "column-gap")).toBe(`${GEOMETRY.homeGrid.gap}px`);

    // Featured card: 23px padding, a 3px salmon TOP rule, a Georgia 27px title.
    const featured = page.getByTestId("featured-signoff");
    const body = featured.locator("> div").filter({ hasText: "" }).first();
    // The 3px top rule sits on the accent fill.
    const rule = featured.locator(":scope > *").first();
    expect(Math.round((await box(rule)).height)).toBe(3);
    expect(await style(rule, "background-color")).toBe(await token(page, "--accent"));
    const title = featured.getByRole("heading");
    expect(await style(title, "font-family")).toContain("Georgia");
    expect(await style(title, "font-size")).toBe("27px");
    void body;

    // 'Review evidence': 40px high, ink text on the accent fill (salmon carries no small text).
    const btn = page.getByTestId("review-evidence");
    expect(Math.round((await box(btn)).height)).toBe(GEOMETRY.button.h);
    expect(await style(btn, "background-color")).toBe(await token(page, "--accent"));
    expect(await style(btn, "color")).toBe(await token(page, "--buttonink"));

    // Active tab: a 3px accentink underline.
    const activeTab = page.getByRole("tab", { selected: true });
    expect(await style(activeTab, "border-bottom-width")).toBe("3px");
    expect(await style(activeTab, "border-bottom-color")).toBe(await token(page, "--accentink"));
  });

  for (const theme of THEMES) {
    test(`axe: zero serious/critical on Decisions in ${theme}`, async ({ page }) => {
      await setTheme(page, theme);
      await axeClean(page, '[data-testid="decisions"]');
    });
  }
});

test.describe("ruling drawer geometry + a11y", () => {
  test.beforeEach(async ({ page }) => {
    await seedDecisions();
    await page.goto(`${BASE()}/ui/me?as=owner`);
    await page.getByTestId("review-evidence").click();
    await expect(page.getByTestId("drawer-panel")).toBeVisible();
  });

  test("drawer 1112/top20/right1420/radius12/header73, panes 650/462, buttons 40, Georgia-31 title", async ({ page }) => {
    const panel = page.getByTestId("drawer-panel");
    const pb = await box(panel);
    expect(Math.round(pb.width)).toBe(GEOMETRY.drawer.w);
    expect(Math.round(pb.y)).toBe(GEOMETRY.drawer.top);
    expect(Math.round(pb.x + pb.width)).toBe(GEOMETRY.drawer.rightEdge);
    expect(await style(panel, "border-radius")).toBe(`${GEOMETRY.drawer.radius}px`);

    // Header 73px tall.
    const header = panel.locator(":scope > *").first();
    expect(Math.round((await box(header)).height)).toBe(73);

    // Panes 650 (evidence) and 462 (ruling).
    expect(Math.round((await box(page.getByTestId("ruling-evidence"))).width)).toBe(GEOMETRY.drawer.splitLeft);
    expect(Math.round((await box(page.getByTestId("ruling-pane"))).width)).toBe(GEOMETRY.drawer.splitRight);

    // Both action buttons 40px.
    expect(Math.round((await box(page.getByTestId("approve"))).height)).toBe(GEOMETRY.button.h);
    expect(Math.round((await box(page.getByTestId("needs-work"))).height)).toBe(GEOMETRY.button.h);

    // Georgia 31px evidence title.
    const evTitle = page.getByTestId("ruling-evidence").getByRole("heading").first();
    expect(await style(evTitle, "font-family")).toContain("Georgia");
    expect(await style(evTitle, "font-size")).toBe("31px");

    // The sidebar and the originating queue stay visible behind the dim scrim.
    await expect(page.locator("aside").first()).toBeVisible();
    await expect(page.getByTestId("decisions")).toBeVisible();
  });

  test("keyboard focus stays trapped inside the drawer (Tab never lands on the queue behind it)", async ({ page }) => {
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => {
        const panel = document.querySelector('[data-testid="drawer-panel"]');
        return panel ? panel.contains(document.activeElement) : false;
      });
      expect(inside).toBe(true);
    }
  });

  for (const theme of THEMES) {
    test(`axe: zero serious/critical on the drawer in ${theme}`, async ({ page }) => {
      await setTheme(page, theme);
      await axeClean(page, '[data-testid="drawer-panel"]');
    });
  }
});
