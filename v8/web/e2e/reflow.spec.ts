import { expect, test, BASE } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { seedEpic, type G3aFixture } from "./g3a.seed";
import { GEOMETRY } from "./geometry";

test.use({ boardFile: "reflow" }); // one fresh board per spec file (fixtures.ts)

// Criterion c-10bd85c316 @ 1024×768: the shell reflows without horizontal overflow, the sidebar
// collapses to a 56px icon rail (nav still keyboard-reachable), and the ruling drawer spans the
// viewport minus 20px margins.
//
// BUILT @ 1024 (design §4.2 amended breakpoint ≤1024, commit b4b4dc5):
//  • sidebar 56px collapse — AppShell.module.css `@media (max-width: 1279px)` sets .sidebar 56,
//    .header left 56, .main margin-left 96 (1024 ≤ 1279).
//  • drawer margins (width === vw-40, insets 20) — Drawer.module.css `.panel` has margin:20 +
//    max-width:calc(100vw - 40px); the inline width:1112 clamps to 984 at 1024 in a flex-end scrim.
//  • NO horizontal overflow on Decisions / Epic — the two-column content grids (Decisions.module
//    .css, Epic.module.css, 744+336+64 = 1144) collapse to one column at `@media (max-width:
//    1024px)`, so at 1024 the main column (~888px) holds a single column and does not overflow.
//  • ruling body inside the drawer — RulingDrawer.module.css `@media (max-width: 1024px)` stacks the
//    fixed 650/462 panes to one full-width column (second-opinion 2026-09-08), so the ruling grid no
//    longer exceeds the ≈984px drawer and is not clipped by the Drawer's overflow:hidden.
const VW = 1024;
let epicFx: G3aFixture;

test.use({ viewport: { width: VW, height: 768 } });

test.beforeAll(async () => {
  epicFx = await seedEpic();
  await seedDecisions(); // a pending owner sign-off → the ruling drawer opens from it
});

const scrollWidth = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.scrollingElement!.scrollWidth);

test("no horizontal overflow on Decisions and the Epic page", async ({ page }) => {
  await page.goto(`${BASE()}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();
  expect(await scrollWidth(page), "Decisions horizontal overflow").toBe(VW);

  await page.goto(`${BASE()}/ui/epic/${epicFx.epic}?as=owner`);
  await expect(page.locator("main h1")).toBeVisible();
  expect(await scrollWidth(page), "Epic page horizontal overflow").toBe(VW);
});

test("the sidebar collapses to a 56px icon rail, nav still keyboard-reachable", async ({ page }) => {
  await page.goto(`${BASE()}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();

  const aside = page.getByRole("complementary", { name: "Primary" }); // the Status rail is a second <aside>
  const ab = (await aside.boundingBox())!;
  expect(Math.abs(ab.width - 56), "sidebar rail width").toBeLessThan(1);

  // Nav remains reachable by keyboard: Tab lands on a link inside the Sections nav.
  let onNav = false;
  for (let i = 0; i < 8 && !onNav; i++) {
    await page.keyboard.press("Tab");
    onNav = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return !!el && el.tagName === "A" && !!el.closest("nav[aria-label='Sections']");
    });
  }
  expect(onNav, "a Sections nav link is reachable by Tab").toBe(true);
});

test("the ruling drawer spans the viewport minus 20px margins (no horizontal overflow)", async ({ page }) => {
  await page.goto(`${BASE()}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();
  await page.getByTestId("review-evidence").click();
  const drawer = page.getByTestId("drawer-panel");
  await expect(drawer).toBeVisible();

  // Body scroll is locked while the drawer is open, so the page must not scroll sideways.
  expect(await scrollWidth(page), "drawer-open horizontal overflow").toBe(VW);

  // The drawer spans the viewport minus 20px margins: width === vw − 40, insets of 20 each side.
  const db = (await drawer.boundingBox())!;
  expect(Math.abs(db.width - (VW - 40)), "drawer width vw-40").toBeLessThan(1);
  expect(Math.abs(db.x - GEOMETRY.drawer.top), "drawer left inset 20").toBeLessThan(1);
  expect(Math.abs(VW - (db.x + db.width) - GEOMETRY.drawer.top), "drawer right inset 20").toBeLessThan(1);

  // The ruling body must stay INSIDE the drawer — the fixed 650/462 grid clipped it at 1024
  // (second-opinion 2026-09-08); the ≤1024 stack keeps both panes within the panel bounds.
  const grid = (await page.getByTestId("ruling-grid").boundingBox())!;
  for (const testid of ["ruling-evidence", "ruling-pane"] as const) {
    const b = (await page.getByTestId(testid).boundingBox())!;
    expect(b.x, `${testid} left within drawer`).toBeGreaterThanOrEqual(db.x - 1);
    expect(b.x + b.width, `${testid} right within drawer`).toBeLessThanOrEqual(db.x + db.width + 1);
  }
  // One stacked column at 1024: the two panes share the same left edge (not side-by-side).
  expect(grid.width, "ruling grid within drawer").toBeLessThanOrEqual(db.width + 1);
});
