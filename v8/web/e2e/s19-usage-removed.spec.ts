import { test, expect } from "./fixtures";

// S19 (s-d330d76467), criterion c-cc1ff0d112 — owner m-845b58f25c: "The usage context menu doesnt
// work … Only show what works". Measured on the fleet board: GET /v1/me/usage answers every window
// `unavailable — Account not linked` (no EDP8_USAGE_CONFIG), so the rail Usage button and its widget
// were removed. The endpoint stays for a later activation. This spec proves no Usage control is left
// anywhere a viewer can reach: expanded rail, collapsed rail, account menu, and at a phone width.
test.use({ boardFile: "s19-usage" });

test("no Usage control in the rail, the collapsed rail or the account menu", async ({ page }) => {
  await page.goto("/ui/epics?as=owner");
  await expect(page.getByTestId("find-open")).toBeVisible();
  const usage = page.getByRole("button", { name: /usage/i });
  await expect(usage).toHaveCount(0);
  await expect(page.getByTestId("usage-open")).toHaveCount(0);
  await expect(page.getByTestId("usage-slot")).toHaveCount(0);
  await page.screenshot({ path: "e2e/evidence/s19/after-rail-no-usage-1440.png" });
  await page.getByTestId("account-open").click();
  await expect(page.getByRole("dialog").getByText(/usage/i)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Collapse menu" }).click();
  await expect(page.getByRole("button", { name: /usage/i })).toHaveCount(0);
  await page.getByRole("button", { name: "Expand menu" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("button", { name: /usage/i })).toHaveCount(0);
});
