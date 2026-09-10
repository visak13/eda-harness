import { expect, test, BASE } from "./fixtures";
import { seedDecisions, type G2Fixture } from "./g2.seed";

test.use({ boardFile: "find" }); // one fresh board per spec file (fixtures.ts)

// Find / command palette (human defect #12, m-783e725c2f, 2026-09-10): Ctrl-K and the sidebar
// button open it over GET /v1/find; typing a word from an epic's title lists that epic first under
// "Epics"; Enter opens the epic page; Esc closes and returns focus to the opener.
test.describe("Find (Ctrl-K)", () => {
  let fx: G2Fixture;
  test.beforeAll(async () => {
    fx = await seedDecisions();
  });

  test("type an epic word, Enter opens the epic; Esc closes and restores focus", async ({ page }) => {
    await page.goto(`${BASE()}/ui/me?as=owner`);
    await expect(page.getByTestId("decisions")).toBeVisible();

    await page.keyboard.press("Control+k");
    const input = page.getByTestId("find-input");
    await expect(input).toBeFocused();
    const word = fx.words.split(" ").slice(-1)[0]; // the per-run fixture number: unique to this epic
    await input.fill(`fixture ${word}`);
    const rows = page.getByTestId("find-row");
    await expect(rows.first()).toBeVisible();
    await expect(rows.first()).toHaveAttribute("data-group", "Epics");
    await expect(rows.first()).toContainText(fx.words);

    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/ui/epic/${fx.epic}`));
    await expect(page.locator("main h1")).toContainText(fx.words);
    await expect(page.getByTestId("find-dialog")).toHaveCount(0);

    // The sidebar button opens it too; Esc closes it and the button has focus again.
    await page.getByTestId("find-open").click();
    await expect(page.getByTestId("find-input")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("find-dialog")).toHaveCount(0);
    await expect(page.getByTestId("find-open")).toBeFocused();
  });

  test("a message hit lands on its thread row", async ({ page }) => {
    await page.goto(`${BASE()}/ui/me?as=owner`);
    await expect(page.getByTestId("decisions")).toBeVisible(); // the shell's key listener is mounted
    await page.keyboard.press("Control+k");
    await page.getByTestId("find-input").fill("featured card use");
    const row = page.getByTestId("find-row").filter({ hasText: "featured card" }).first();
    await expect(row).toBeVisible();
    await row.click();
    await expect(page).toHaveURL(new RegExp(`/ui/ticket/${fx.story}#${fx.question}`));
    await expect(page.locator(`#${fx.question}`)).toHaveAttribute("data-found", "true");
  });
});
