import { test, expect, EPIC } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
import { THEMES } from "../src/theme/themes";
test.use({ boardFile: "s3-workflow" });
for (const [width, height] of [[1440, 900], [320, 568], [844, 390]]) test(`New epic bounded focus and exact creation ${width}x${height}`, async ({ page }) => {
  await page.setViewportSize({ width, height });
  await page.goto("/ui/epics?as=owner");
  const trigger = page.getByRole("button", { name: "New epic", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "New epic", exact: true });
  await expect(page.getByTestId("new-epic-title")).toBeFocused();
  await page.getByTestId("new-epic-title").fill("  Separate title  ");
  const words = "  Raw first line\nSecond line  ";
  await page.getByTestId("new-epic-words").fill(words);
  const box = (await dialog.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(width); expect(box.y + box.height).toBeLessThanOrEqual(height);
  await page.getByTestId("new-epic-create").focus();
  await page.keyboard.press("Tab"); await expect(page.getByTestId("new-epic-title")).toBeFocused();
  await page.keyboard.press("Shift+Tab"); await expect(page.getByTestId("new-epic-create")).toBeFocused();
  expect(await page.locator("#root").evaluate((el) => (el as HTMLElement).inert)).toBe(true);
  await page.keyboard.press("Escape"); await expect(trigger).toBeFocused();
  expect(await page.locator("body").evaluate((el) => el.style.overflow)).not.toBe("hidden");
  await trigger.click(); await expect(page.getByTestId("new-epic-words")).toHaveValue(words);
  await page.screenshot({ path: `e2e/evidence/s3-new-epic-${width}.png` });
  for (const theme of THEMES) {
    await page.evaluate((id) => { document.documentElement.dataset.theme = id; localStorage.setItem("edp8.theme", id); }, theme.id);
    await page.getByTestId("new-epic-title").scrollIntoViewIfNeeded();
    await page.getByTestId("new-epic-create").click({ trial: true });
    // @ts-expect-error shared axe adapter has dual playwright-core types
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical"), theme.id).toEqual([]);
    if (["folio", "obsidian", "folio-hc"].includes(theme.id)) await page.screenshot({ path: `e2e/evidence/s3-new-epic-${width}-${theme.id}.png` });
    await page.getByTestId("new-epic-effort").scrollIntoViewIfNeeded();
    await expect(page.getByTestId("new-epic-effort")).toBeInViewport();
    await expect(page.getByTestId("new-epic-create")).toBeInViewport();
    if (["folio", "obsidian", "folio-hc"].includes(theme.id)) await page.screenshot({ path: `e2e/evidence/s3-new-epic-${width}-${theme.id}-controls.png` });
  }
  const response = page.waitForResponse((res) => res.url().endsWith("/v1/tickets") && res.request().method() === "POST");
  await page.getByTestId("new-epic-create").click();
  const made = (await (await response).json()).value;
  expect(made.title).toBe("Separate title"); expect(made.words).toBe(words);
  await expect(page).toHaveURL(new RegExp(`/epic/${made.id}`));
  // R1 (9734d1d) moved New epic off the shell onto the Epics page; the emptied form is checked there.
  await page.goto("/ui/epics?as=owner");
  await page.getByRole("button", { name: "New epic", exact: true }).click();
  await expect(page.getByTestId("new-epic-title")).toHaveValue("");
  await expect(page.getByTestId("new-epic-words")).toHaveValue("");
});
test("conversation is default and source draft survives contextual history", async ({ page }) => {
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  await expect(page.getByRole("heading", { name: "Spike epic", exact: true })).toBeVisible();
  const text = page.getByRole("textbox", { name: /Message/ }).first();
  await text.fill("Source draft remains here");
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "History", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "History category" }).selectOption("status");
  await expect(page.getByRole("link", { name: "Open in tab" })).toHaveAttribute("href", /category=status/);
  await page.keyboard.press("Escape");
  await expect(text).toHaveValue("Source draft remains here");
  await page.screenshot({ path: "e2e/evidence/s3-conversation.png", fullPage: true });
});
