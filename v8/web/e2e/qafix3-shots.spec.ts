// architect m-7e741f6860 items 1-4, shot at 1280 and 390. SHOT_SET=before|after names the folder under e2e/evidence/qafix3/.
// Assertions run only in the "after" set. Remote shows synthetic data only (the real page shows the owner's tailnet name).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { BASE, expect, test } from "./fixtures";

const SET = process.env.SHOT_SET ?? "after";
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "qafix3", SET);
test.use({ boardFile: "qafix3-shots" });
test.describe.configure({ mode: "serial", timeout: 120_000 });
test.beforeAll(() => { fs.mkdirSync(OUT, { recursive: true }); });

const ok = (value: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, value, hint: "" }) });
const shoot = (page: Page, name: string, label: string) => page.screenshot({ path: path.join(OUT, `${name}-${label}.png`), fullPage: false });
const go = async (page: Page, url: string, as = true) => { await page.goto(`${BASE()}/ui${url}${as ? (url.includes("?") ? "&" : "?") + "as=owner" : ""}`); await page.waitForTimeout(900); };
const signedOut = async (page: Page) => {
  await page.route("**/v1/whoami", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ ok: false, error: { code: "unauthorized", message: "sign in" } }) }));
  await page.route("**/v1/access-requests/available", (route) => route.fulfill(ok({ enabled: true, reason: null, roles: ["guest", "owner"] })));
};

for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`1 design: every move table, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await go(page, "/design?wf=standard@1");
    const d = page.getByTestId("pipeline-transitions");
    await d.locator("summary").click();
    await d.scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
    await shoot(page, "1-design-moves", label);
    await (SET === "after" ? Promise.resolve().then(async () => {
      const t = await d.locator("table").boundingBox(); const vw = size.width;
      expect(t!.x + t!.width, "the table fits the page").toBeLessThanOrEqual(vw);
    }) : Promise.resolve());
  });

  test(`2 remote: every check, synthetic data, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route("**/v1/admin/tailnet", (route) => route.fulfill(ok({
      tailscale: { backend: "Running", dns: "example-host.example.ts.net" }, serve: null, serve_proxies: [], public_url: null, tailnet_url: "https://example-host.example.ts.net",
      public_mode: false, blockers: 0, auth_keys: { configured: true },
      rows: [["OK", "tokens.json", "every participant has a token"], ["OK", "humans", "2 people can sign in"], ["OK", "tailscale", "running and signed in"], ["OK", "certificates", "HTTPS is enabled for the tailnet"],
        ["WARN", "funnel", "off: this board is not on the public internet", "nothing to do"], ["OK", "board bind", "127.0.0.1 only"]].map(([level, area, text, fix]) => ({ level, area, text, fix })) })));
    await go(page, "/admin?tab=remote");
    const d = page.getByTestId("remote-readiness");
    await d.locator("summary").click();
    await d.scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
    await shoot(page, "2-remote-checks", label);
    if (SET === "after") {
      const broken = await d.evaluate((el) => Array.from(el.querySelectorAll("td")).filter((c) => { const r = document.createRange(); r.selectNodeContents(c); const w = (c.textContent ?? "").trim(); return /^[\w.-]{5,}$/.test(w) && new Set(Array.from(r.getClientRects()).map((q) => Math.round(q.top))).size > 1; }).map((c) => c.textContent));
      expect(broken, "no check name breaks mid-word").toEqual([]);
    }
  });

  test(`3 request access: the role option fits, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await signedOut(page);
    await go(page, "/epics", false);
    await page.getByTestId("access-open").click();
    await page.getByTestId("access-name").fill("A visitor");
    await page.waitForTimeout(300);
    await shoot(page, "3-request-access", label);
    if (SET === "after") {
      const sel = page.getByTestId("access-role");
      const clipped = await sel.evaluate((s) => Array.from((s as HTMLSelectElement).options).map((o) => o.text).filter((t) => t.length > 22));
      expect(clipped, "every role option is short enough for a phone select").toEqual([]);
    }
  });

  test(`4 sign-in: Participant starts empty, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await signedOut(page);
    await go(page, "/epics", false);
    await expect(page.getByTestId("identity-panel")).toBeVisible();
    await shoot(page, "4-sign-in", label);
    if (SET === "after") await expect(page.getByTestId("identity-as")).toHaveValue("");
  });
}
