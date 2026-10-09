// architect m-2f22a4e121 items 2 and 3, shot at 299/390/1280. SHOT_SET=before|after names the folder under e2e/evidence/qafix4/.
// Remote shows synthetic data only (the example host, never the owner's tailnet name). Assertions run only in the "after" set.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { BASE, expect, test } from "./fixtures";

const SET = process.env.SHOT_SET ?? "after";
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "qafix4", SET);
test.use({ boardFile: "qafix4-shots" });
test.describe.configure({ mode: "serial", timeout: 120_000 });
test.beforeAll(() => { fs.mkdirSync(OUT, { recursive: true }); });

const ok = (value: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, value, hint: "" }) });
const shoot = (page: Page, name: string, label: string) => page.screenshot({ path: path.join(OUT, `${name}-${label}.png`), fullPage: false });
const HOST = "your-pc.tail1234.ts.net";

for (const [label, size] of [["299", { width: 299, height: 700 }], ["390", { width: 390, height: 844 }], ["1280", { width: 1280, height: 800 }]] as const) {
  test(`3 failed sign-in states the failure once, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.addInitScript(() => { try { sessionStorage.setItem("edp8.sign-in-tried", "1"); sessionStorage.setItem("edp8.token", "wrong"); } catch { /* blocked */ } });
    await page.route("**/v1/whoami", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ ok: false, error: "X-Token does not match", hint: "check your token" }) }));
    await page.goto(`${BASE()}/ui/epics?as=maria`);
    await expect(page.getByTestId("identity-panel")).toBeVisible();
    await page.waitForTimeout(300);
    await shoot(page, "3-failed-sign-in", label);
    if (SET === "after") {
      const text = (await page.getByTestId("identity-panel").innerText()).toLowerCase();
      expect((text.match(/did not accept|don't match|not match/g) ?? []).length, "the failure is stated once").toBe(1);
    }
  });

  if (label === "299") continue;
  test(`2 remote: the example host stays on one line, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route("**/v1/admin/tailnet", (route) => route.fulfill(ok({
      tailscale: { backend: "Running", dns: HOST }, serve: null, serve_proxies: [], public_url: null, tailnet_url: `https://${HOST}`,
      public_mode: false, blockers: 0, auth_keys: { configured: true }, rows: [] })));
    await page.route("**/v1/admin/tailnet/guide", (route) => route.fulfill(ok({ name: "remote-access", path: "docs/operator/remote-access.md",
      html: `<h2>3. Sign in</h2><p><strong>Done when</strong> <code>tailscale status</code> reports <strong>Running</strong> and a machine name such as <code>${HOST}</code>. Then press <strong>Check again</strong> on the page.</p>` })));
    await page.goto(`${BASE()}/ui/admin?tab=remote&as=owner`);
    await page.waitForTimeout(900);
    await page.getByTestId("remote-guide").locator("summary").click();
    await page.waitForTimeout(500);
    const signin = page.getByTestId("remote-signin");
    await signin.scrollIntoViewIfNeeded();
    await shoot(page, "2-remote-host-signin", label);
    await page.getByTestId("remote-guide").scrollIntoViewIfNeeded();
    await shoot(page, "2-remote-host-guide", label);
    if (SET === "after") {
      const lines = await page.evaluate((host) => {
        const out: number[] = [];
        for (const el of Array.from(document.querySelectorAll("[data-testid=remote-signin] *, [data-testid=remote-guide] code, [data-testid=remote-step-serve] code"))) {
          if (!(el.textContent ?? "").includes(host)) continue;
          const r = document.createRange(); r.selectNodeContents(el);
          out.push(new Set(Array.from(r.getClientRects()).map((q) => Math.round(q.top))).size);
        }
        return out;
      }, HOST);
      expect(lines.length, "the host is on the page").toBeGreaterThan(0);
      expect(Math.max(...lines), "no host name wraps").toBe(1);
    }
  });
}
