import { test, expect, EPIC } from "./fixtures";

// qa finding 7 (epic-44a0576511, c-d367a56fc8): Escape on a links-row viewer must hand focus back to
// the button that opened it. jsdom has no `inert`, so only a real browser can prove this.
test.use({ boardFile: "qa-drawer-focus" });
for (const name of ["Files & evidence", "History", "Work"]) test(`Escape on the ${name} drawer returns focus to its trigger`, async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  const trigger = page.getByRole("button", { name, exact: true }).first();
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name, exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(":focus")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
