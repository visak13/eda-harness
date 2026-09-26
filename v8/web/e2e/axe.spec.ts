import { expect, test, BASE } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
import { seedDecisions, type G2Fixture } from "./g2.seed";
import { openRuling } from "./g2-owner-loop.helpers";
import { seedEpic, type G3aFixture } from "./g3a.seed";

test.use({ boardFile: "axe" }); // one fresh board per spec file (fixtures.ts)

// Criterion c-80b50710a6 (standalone accessibility sweep, distinct from the axe fold in
// g3a-fidelity): every core surface is axe-clean — zero "serious"/"critical" violations — in each
// of the four themes. Theme is switched through the real radiogroup (theme.spec.ts mechanism: the
// "Account and preferences" popover → the theme radio), which persists to localStorage so it
// survives the subsequent navigations. The axe invocation mirrors g3a-fidelity.spec.ts.
const THEMES = [
  { id: "folio", label: "Folio" },
  { id: "dusk", label: "Dusk" },
  { id: "ember", label: "Ember" },
  { id: "folio-hc", label: "Folio HC" },
] as const;

let g3a: G3aFixture;
let fx: G2Fixture;

test.beforeAll(async () => {
  fx = await seedDecisions(); // a pending owner sign-off → the ruling drawer opens from it
  g3a = await seedEpic();
});

async function axeClean(page: import("@playwright/test").Page, label: string): Promise<void> {
  // @axe-core/playwright pins its own playwright-core copy, so its Page type is nominally a
  // different structural type than @playwright/test's Page here — the same object at runtime.
  // @ts-expect-error dual playwright-core type identities
  const results = await new AxeBuilder({ page }).analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad, `${label}: ${bad.map((v) => v.id).join(", ")}`).toEqual([]);
}

for (const theme of THEMES) {
  test(`${theme.label}: Epics, Epic, Library and the ruling drawer are axe-clean (no serious/critical)`, async ({
    page,
  }) => {
    // Switch theme via the radiogroup (theme.spec.ts). It writes localStorage.edp8.theme, so every
    // navigation below re-applies it pre-paint.
    await page.goto(`${BASE()}/ui/epics?as=owner`);
    await page.getByRole("button", { name: "Account and preferences" }).click();
    await page.getByRole("radio", { name: theme.label, exact: true }).check();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe(theme.id);

    // Epics — fresh load (popover closed, theme applied pre-paint). S20: the owner home; the Needs
    // you page is gone.
    await page.goto(`${BASE()}/ui/epics?as=owner`);
    await expect(page.getByTestId("epic-list")).toBeVisible();
    await axeClean(page, `${theme.id} Epics`);

    // Epic.
    await page.goto(`${BASE()}/ui/epic/${g3a.epic}?as=owner`);
    await expect(page.locator("main h1")).toBeVisible();
    await axeClean(page, `${theme.id} Epic`);

    // Library.
    await page.goto(`${BASE()}/ui/library/tickets?as=owner`);
    await expect(page.getByTestId("tickets-table")).toBeVisible();
    await axeClean(page, `${theme.id} Library`);

    // Ruling drawer — open it from the pending owner sign-off's link (S20: /ui/ticket/<story>#<criterion>).
    await openRuling(page, fx);
    await expect(page.getByTestId("drawer-panel")).toBeVisible();
    await axeClean(page, `${theme.id} Ruling drawer`);
  });
}
