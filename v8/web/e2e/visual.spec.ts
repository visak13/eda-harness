import { expect, test, BASE } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { seedEpic, type G3aFixture } from "./g3a.seed";

test.use({ boardFile: "visual" }); // one fresh board per spec file (fixtures.ts)

// Criterion c-80b50710a6 (screenshot project): each Folio plate {Decisions, Epic, Ruling, Library}
// renders pixel-stable across the four themes (maxDiffPixelRatio 0.01). Reference PNGs are win32
// renders, so the whole file is skipped off win32 (matching the visual-baseline policy in
// fidelity.spec.ts / tests/fidelity/README.md), and playwright.config.ts keys snapshots by
// {platform} so a non-win32 run can never diff against a win32 baseline.
//
// BASELINES ARE NOT COMMITTED HERE. They are generated on the FIRST qa win32 run with
// `npx playwright test e2e/visual.spec.ts --update-snapshots`, land under e2e/__screenshots__
// (web/.gitignore negates that path), and are committed from that run. Do NOT run playwright here.
const THEMES = ["folio", "dusk", "ember", "folio-hc"] as const;

let g3a: G3aFixture;

test.describe("Folio plates — visual regression @ 1440×900", () => {
  test.skip(process.platform !== "win32", "reference plates are win32 renders (visual-baseline policy)");

  test.beforeAll(async () => {
    await seedDecisions(); // a pending owner sign-off → the ruling drawer opens from it
    g3a = await seedEpic();
  });

  // Each plate: navigate + settle into the exact captured state.
  const PLATES: { name: string; open: (page: import("@playwright/test").Page) => Promise<void> }[] = [
    {
      name: "decisions",
      open: async (page) => {
        await page.goto(`${BASE()}/ui/me?as=owner`);
        await expect(page.getByTestId("decisions")).toBeVisible();
      },
    },
    {
      name: "epic",
      open: async (page) => {
        await page.goto(`${BASE()}/ui/epic/${g3a.epic}?as=owner`);
        await expect(page.locator("main h1")).toBeVisible();
      },
    },
    {
      name: "library",
      open: async (page) => {
        await page.goto(`${BASE()}/ui/library/tickets?as=owner`);
        await expect(page.getByTestId("tickets-table")).toBeVisible();
      },
    },
    {
      name: "ruling",
      open: async (page) => {
        await page.goto(`${BASE()}/ui/me?as=owner`);
        await expect(page.getByTestId("decisions")).toBeVisible();
        await page.getByTestId("review-evidence").click();
        await expect(page.getByTestId("drawer-panel")).toBeVisible();
      },
    },
  ];

  for (const plate of PLATES) {
    for (const theme of THEMES) {
      test(`${plate.name} — ${theme}`, async ({ page }) => {
        // Apply the theme pre-paint so there is no post-mount flash in the capture.
        await page.addInitScript((t) => localStorage.setItem("edp8.theme", t), theme);
        await plate.open(page);
        await expect(page).toHaveScreenshot(`${plate.name}-${theme}.png`, { maxDiffPixelRatio: 0.01 });
      });
    }
  }
});
