import { expect, test } from "@playwright/test";
import { seedDecisions } from "./g2.seed";
import { seedEpic, type G3aFixture } from "./g3a.seed";
import { GEOMETRY } from "./geometry";

// Criterion c-10bd85c316 @ 1024×768: the shell reflows without horizontal overflow, the sidebar
// collapses to a 56px icon rail (nav still keyboard-reachable), and the ruling drawer spans the
// viewport minus 20px margins.
//
// GAP-FLAGS (confirmed against the CSS at 1024, this run):
//  • sidebar 56px collapse — BUILT: AppShell.module.css:343 `@media (max-width: 1279px)` sets
//    .sidebar width 56 (1024 ≤ 1279), .header left 56, .main margin-left 96.
//  • drawer margins (width === vw-40, insets 20) — BUILT: Drawer.module.css:12-16 `.panel` has
//    margin:20 + max-width:calc(100vw - 40px); the inline width:1112 is clamped to 984 at 1024, in
//    a flex-end scrim → left/right insets of 20. (The ≤959 media query at :69 does NOT fire at 1024;
//    the clamp is what delivers the contract here.)
//  • NO horizontal overflow on Decisions / Epic — UNBUILT at 1024. The two-column content grids
//    (Decisions.module.css:2-6 and Epic.module.css:69-72, both 744px+336px+64 gap = 1144px) only
//    collapse to one column at `@media (max-width: 1279px)`… no — at `@media (max-width: 959px)`
//    (Decisions.module.css:423, Epic.module.css:307). But the SIDEBAR collapses at ≤1279, so between
//    960–1279 the main column is only ~888px (1024 − 96 − 40) while the content grid is still 1144px
//    → the grid overflows and the page scrolls horizontally. These two assertions therefore FAIL on
//    qa's run until the page grids also collapse at ≤1279 (align the content breakpoint with the
//    sidebar's). Written as the criterion specifies — NOT weakened to pass against the unbuilt CSS.
const BASE = process.env.EDP8_E2E_BASE!;
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
  // NB: expected to FAIL until the content grids collapse at ≤1279 (see GAP-FLAGS above).
  await page.goto(`${BASE}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();
  expect(await scrollWidth(page), "Decisions horizontal overflow").toBe(VW);

  await page.goto(`${BASE}/ui/epic/${epicFx.epic}?as=owner`);
  await expect(page.locator("main h1")).toBeVisible();
  expect(await scrollWidth(page), "Epic page horizontal overflow").toBe(VW);
});

test("the sidebar collapses to a 56px icon rail, nav still keyboard-reachable", async ({ page }) => {
  await page.goto(`${BASE}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();

  const aside = page.locator("aside");
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
  await page.goto(`${BASE}/ui/me?as=owner`);
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
});
