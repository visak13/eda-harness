import { test, expect, EPIC } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
import { THEMES } from "../src/theme/themes";

test.use({ boardFile: "s6-usage" });
const bucket = (key: string, minutes: number | null, used: number | null) => ({
  key, window_minutes: minutes, used_percent: used, resets_at: used === null ? null : 4102444800,
  observed_at: null, status: used === null ? "unavailable" : "stale", reason: used === null ? "Window not reported" : "Observation time unknown; may be stale",
});
const sample = { providers: [
  { provider: "claude", source: "Claude Code statusline", account_binding: "Linked account", received_at: "2026-09-18T08:56:52Z", retry_after_seconds: 30,
    windows: [bucket("five_hour", 300, 0), bucket("seven_day", 10080, 15), bucket("fable", null, null)] },
  { provider: "codex", source: "Codex App Server", account_binding: "Linked account", received_at: "2026-09-18T08:16:59Z", retry_after_seconds: 30,
    windows: [bucket("five_hour", 300, null), bucket("seven_day", 10080, 92)] },
] };

test("real endpoint defaults unlinked; Usage directly precedes Find without navigation", async ({ page }) => {
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  const trigger = page.getByRole("button", { name: "Usage", exact: true });
  await expect(trigger).toBeVisible();
  const before = page.url();
  const response = page.waitForResponse((r) => r.url().endsWith("/v1/me/usage"));
  await trigger.click();
  expect((await (await response).json()).ok).toBe(true);
  await expect(page.getByText("No account linked", { exact: false }).first()).toBeVisible();
  const find = page.getByRole("button", { name: "Find (Ctrl-K)" });
  expect(await trigger.evaluate((el) => el.closest("#shell-usage-slot")?.nextElementSibling?.getAttribute("data-testid"))).toBe("find-open");
  expect(page.url()).toBe(before);
  await page.keyboard.press("Escape"); await expect(trigger).toBeFocused();
  await expect(find).toBeVisible();
});

for (const [width, height] of [[1440, 900], [320, 568], [844, 390]]) test(`synthetic usage all themes bounded, nonmodal, draft-safe ${width}x${height}`, async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width, height });
  await page.route("**/v1/me/usage", (route) => route.fulfill({ json: { ok: true, value: sample } }));
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  const draft = page.getByRole("textbox", { name: /Message/ }).first();
  await draft.fill("Synthetic source draft stays intact");
  const trigger = page.getByRole("button", { name: "Usage", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Subscription usage" });
  await expect(dialog.getByText("0% used", { exact: true })).toBeVisible();
  expect(await page.locator("#root").evaluate((el) => (el as HTMLElement).inert)).toBe(false);
  for (const theme of THEMES) {
    await page.evaluate((id) => { document.documentElement.dataset.theme = id; }, theme.id);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(11); expect(box.y).toBeGreaterThanOrEqual(11);
    expect(box.x + box.width).toBeLessThanOrEqual(width - 11);
    expect(box.y + box.height).toBeLessThanOrEqual(height - 11);
    expect(box.width).toBeLessThanOrEqual(304);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // @ts-expect-error shared axe adapter has dual playwright-core types
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical"), theme.id).toEqual([]);
    if (["folio", "obsidian", "folio-hc"].includes(theme.id)) {
      await dialog.evaluate((el) => { el.scrollTop = 0; });
      await page.screenshot({ path: `e2e/evidence/s6-usage-${width}-${theme.id}.png` });
    }
    const refresh = dialog.getByRole("button", { name: /Refresh/ });
    await refresh.scrollIntoViewIfNeeded(); await expect(refresh).toBeInViewport();
    if (theme.id === "folio") await page.screenshot({ path: `e2e/evidence/s6-usage-${width}-bottom.png` });
  }
  const close = dialog.getByRole("button", { name: "Close Subscription usage" });
  await close.scrollIntoViewIfNeeded(); await close.focus();
  await page.keyboard.press("Escape"); await expect(trigger).toBeFocused();
  await expect(draft).toHaveValue("Synthetic source draft stays intact");
  await trigger.click(); await dialog.getByRole("button", { name: "Close Subscription usage" }).click();
  await expect(trigger).toBeFocused();
  await trigger.click(); await draft.focus();
  await expect(dialog).toHaveCount(0); await expect(draft).toBeFocused();
});
