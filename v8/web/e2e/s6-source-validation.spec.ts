// Operator-approved optional real receipt comparison. Never launches providers or reads credentials.
// Cold suites skip unless EDP8_E2E_USAGE_CONFIG explicitly selects a private validation mapping.
import fs from "node:fs";
import { test, expect, EPIC } from "./fixtures";

test.use({ boardFile: "s6-source-validation" });
test("authorized installed-source receipts equal isolated API and widget", async ({ page, request }) => {
  const configPath = process.env.EDP8_E2E_USAGE_CONFIG;
  test.skip(!configPath, "Requires explicit operator-approved private receipt mapping; not synthetic proof");
  const config = JSON.parse(fs.readFileSync(configPath!, "utf8"));
  const claude = JSON.parse(fs.readFileSync(config.participants.owner.claude.snapshot, "utf8"));
  const codex = JSON.parse(fs.readFileSync(config.participants.owner.codex.snapshot, "utf8"));
  const response = await request.get("/v1/me/usage", { headers: { "X-Participant": "owner" } });
  expect(response.status()).toBe(200);
  const usage = (await response.json()).value;
  for (const [i, key] of ["five_hour", "seven_day"].entries()) {
    expect(usage.providers[0].windows[i].used_percent).toBe(claude.rate_limits[key].used_percentage);
    expect(usage.providers[0].windows[i].resets_at).toBe(claude.rate_limits[key].resets_at);
    expect(usage.providers[0].windows[i].observed_at).toBeNull();
  }
  const pool = codex.rateLimitsByLimitId?.codex ?? codex.rateLimits;
  for (const w of usage.providers[1].windows) {
    const source = [pool.primary, pool.secondary].find((r) => r?.windowDurationMins === w.window_minutes);
    expect(w.used_percent).toBe(source?.usedPercent ?? null);
    expect(w.resets_at).toBe(source?.resetsAt ?? null);
    expect(w.observed_at).toBeNull();
  }
  const unlinked = await request.get("/v1/me/usage?participant_id=owner", { headers: { "X-Participant": "arch" } });
  expect((await unlinked.json()).value.providers.every((p: { account_binding: string | null }) => p.account_binding === null)).toBe(true);
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  await page.getByRole("button", { name: "Usage", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Subscription usage" });
  for (const provider of usage.providers) {
    const region = dialog.getByRole("region", { name: provider.provider === "claude" ? "Claude" : "Codex" });
    for (const w of provider.windows) {
      if (w.used_percent !== null) await expect(region.getByText(`${w.used_percent}% used`, { exact: true }).first()).toBeAttached();
    }
  }
  await page.screenshot({ path: "e2e/evidence/s6-usage-source-real.png" });
  await dialog.getByRole("region", { name: "Codex" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/evidence/s6-usage-source-real-codex.png" });
});
