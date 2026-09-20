import { test, expect, EPIC } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
import { THEMES } from "../src/theme/themes";
import { contrastRatio } from "../src/theme/contrast";

test.use({ boardFile: "s2-foundations" });
const sizes = [[1440,900],[1280,800],[1100,768],[1024,768],[768,600],[390,844],[320,568],[844,390]];
for (const [width,height] of sizes) test(`preferences bounded and keyboard usable ${width}x${height}`, async ({ page }) => {
  await page.setViewportSize({ width, height });
  await page.goto("/ui/epics?as=owner");
  const trigger = page.getByRole("button", { name: "Account and preferences", exact: true });
  if (width < 768) await page.getByRole("button", { name: "Workspace navigation", exact: true }).click();
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Account and preferences", exact: true });
  await expect(dialog).toBeVisible();
  const box = (await dialog.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(11); expect(box.y).toBeGreaterThanOrEqual(11);
  expect(box.x + box.width).toBeLessThanOrEqual(width - 11); expect(box.y + box.height).toBeLessThanOrEqual(height - 11);
  await dialog.getByRole("radio", { name: "Obsidian", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "obsidian");
  const avatars = dialog.getByTestId("avatar-picker").getByRole("radio");
  await avatars.last().click(); await expect(avatars.last()).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); await expect(trigger).toBeFocused();
  await page.reload(); await expect(page.locator("html")).toHaveAttribute("data-theme", "obsidian");
  if (width < 768) await page.getByRole("button", { name: "Workspace navigation", exact: true }).click();
  await trigger.click(); await expect(avatars.last()).toHaveAttribute("aria-checked", "true");
  await dialog.getByRole("radio", { name: "Obsidian", exact: true }).focus();
  await page.keyboard.press("ArrowLeft"); await expect(page.locator("html")).toHaveAttribute("data-theme", "midnight");
  await page.setViewportSize({ width: 320, height: 568 });
  const resized = (await dialog.boundingBox())!; expect(resized.x + resized.width).toBeLessThanOrEqual(309);
  await page.keyboard.press("Escape");
  await trigger.click();
  await page.getByRole("button", { name: "Close Account and preferences" }).focus();
  await page.keyboard.press("Shift+Tab"); // 457ae20: the panel traps Tab, focus wraps and stays inside
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(":focus")).toHaveCount(1);
  await page.mouse.click(2, 2); // outside the 12px-clamped panel, without forced targeting
  await expect(dialog).toHaveCount(0);
});

for (const theme of THEMES) test(`built theme ${theme.id}: prepaint, axe, screenshot`, async ({ page }) => {
  await page.addInitScript((id) => localStorage.setItem("edp8.theme", id), theme.id);
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme.id);
  await expect(page.getByRole("heading", { name: "Spike epic", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Account and preferences", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Account and preferences", exact: true })).toBeVisible();
  // @ts-expect-error dual playwright-core types; existing axe.spec.ts uses the same runtime adapter
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  const borders = await page.locator('input:not([type="radio"]):not([type="checkbox"]), textarea, select').evaluateAll((elements) => elements.filter((el) => el.getClientRects().length).map((el) => {
    const css = getComputedStyle(el);
    const hex = (rgb: string) => "#" + rgb.match(/\d+/g)!.slice(0, 3).map((n) => Number(n).toString(16).padStart(2, "0")).join("");
    let parent = el.parentElement!;
    while (parent.parentElement && getComputedStyle(parent).backgroundColor === "rgba(0, 0, 0, 0)") parent = parent.parentElement;
    return { border: hex(css.borderTopColor), ground: hex(getComputedStyle(parent).backgroundColor), label: el.getAttribute("aria-label") ?? el.tagName };
  }));
  for (const pair of borders) expect(contrastRatio(pair.border, pair.ground), `${theme.id} ${pair.label} actual boundary`).toBeGreaterThanOrEqual(3);
  await page.screenshot({ path: `e2e/evidence/s2-${theme.id}.png`, fullPage: true });
  await page.keyboard.press("Escape");
  for (const route of ["me", "epics", "seats"]) {
    await page.goto(`/ui/${route}?as=owner`);
    // @ts-expect-error dual playwright-core types, as above
    const audit = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(audit.violations.filter((v) => v.impact === "serious" || v.impact === "critical"), `${theme.id}/${route}`).toEqual([]);
  }
});
