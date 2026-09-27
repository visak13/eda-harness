// S21 (s-0cfebd3862, c-b73a4537db): the code server run by an admin with no shell, on a PRIVATE board, in the
// light and dark Heronry themes. drill_code_service.ps1 -Shots <dir> runs it while the code server is stopped.
//   1. Admin → Services and the Code tab while it is down: Start only, `heronry start code`, never .\edp.ps1
//   2. the Code tab's Start (admin) brings it up and the tab embeds the editor
//   3. Admin → Services: Stop + Restart on the up row; Restart, Stop, Start again from the row; a phone width
// It leaves the code server stopped.
//
//   WALK_OWNER_TOKEN=<token> node scripts/s21_code_walk.mjs <board-base-url> <out-dir>
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [base, out] = process.argv.slice(2);
if (!base || !out) {
  console.error("usage: node scripts/s21_code_walk.mjs <base-url> <out-dir>");
  process.exit(2);
}
const as = `as=owner&token=${encodeURIComponent(process.env.WALK_OWNER_TOKEN ?? "")}`;
const THEMES = ["heronry", "heronry-dark"];
let failed = 0;
function check(ok, what) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed++;
}

const browser = await chromium.launch();
let current = null; // the page in use, for the error shot
async function open(theme, width = 1440, height = 900) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  await ctx.addInitScript((t) => { try { localStorage.setItem("edp8.theme", t); } catch { /* private mode */ } }, theme);
  current = await ctx.newPage();
  return { ctx, page: current };
}
async function services(page) {
  await page.goto(`${base}/ui/admin?tab=services&${as}`);
  const row = page.getByTestId("service-code-server");
  await row.waitFor({ timeout: 30000 });
  await page.waitForTimeout(500);
  return row;
}
const buttons = async (row) => (await row.getByRole("button").allTextContents()).map((s) => s.trim());
async function codeRowState(page, want, timeout = 150000) {
  const t0 = Date.now();
  for (;;) {
    const row = await services(page);
    const got = JSON.stringify(await buttons(row));
    if (got === (want === "up" ? '["Stop","Restart"]' : '["Start"]')) return row;
    if (Date.now() - t0 > timeout) return null;
    await page.waitForTimeout(2000);
  }
}

try {
  // 1. down
  for (const theme of THEMES) {
    const { ctx, page } = await open(theme);
    const row = await services(page);
    check(JSON.stringify(await buttons(row)) === '["Start"]', `${theme} services: the down code-server row offers Start only (${await buttons(row)})`);
    await page.getByTestId("services").screenshot({ path: path.join(out, `${theme}-services-code-down.png`) });
    await page.goto(`${base}/ui/code?${as}`);
    await page.getByTestId("code-start-command").waitFor({ timeout: 20000 });
    const txt = await page.getByTestId("code-page").innerText();
    check(txt.includes("heronry start code") && !txt.includes("edp.ps1"), `${theme} code tab down: heronry start code, never edp.ps1`);
    check(await page.getByTestId("code-start").isVisible(), `${theme} code tab down: an admin gets Start`);
    await page.screenshot({ path: path.join(out, `${theme}-code-tab-down.png`) });
    await ctx.close();
  }

  // 2. Start from the Code tab
  {
    const { ctx, page } = await open(THEMES[0]);
    await page.goto(`${base}/ui/code?${as}`);
    await page.getByTestId("code-start").click();
    const t0 = Date.now();
    const frame = page.getByTestId("code-frame");
    await frame.waitFor({ timeout: 150000 });
    check(true, `the Code tab's Start brought the code server up and the tab frames it (${Math.round((Date.now() - t0) / 1000)} s)`);
    await ctx.close();
  }
  for (const theme of THEMES) {
    const { ctx, page } = await open(theme);
    await page.goto(`${base}/ui/code?${as}`);
    await page.getByTestId("code-frame").waitFor({ timeout: 30000 });
    const fr = page.frameLocator('[data-testid="code-frame"]');
    let workbench = false;
    try { await fr.locator(".monaco-workbench").first().waitFor({ timeout: 60000 }); workbench = true; } catch { /* reported */ }
    check(workbench, `${theme} code tab: the embedded VS Code workbench renders`);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(out, `${theme}-code-tab-embedded.png`) });
    await ctx.close();
  }

  // 3. Admin → Services controls
  for (const theme of THEMES) {
    const { ctx, page } = await open(theme);
    const row = await codeRowState(page, "up", 30000);
    check(row && JSON.stringify(await buttons(row)) === '["Stop","Restart"]', `${theme} services: the up row offers Stop and Restart`);
    await page.getByTestId("services").screenshot({ path: path.join(out, `${theme}-services-code-up.png`) });
    await ctx.close();
    const phone = await open(theme, 390, 844);
    await services(phone.page);
    const sw = await phone.page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(sw <= 0, `${theme} services at 390 px: no horizontal scroll (overflow ${sw}px)`);
    await phone.page.screenshot({ path: path.join(out, `${theme}-services-phone.png`), fullPage: true });
    await phone.ctx.close();
  }
  {
    const { ctx, page } = await open(THEMES[0]);
    let row = await services(page);
    await row.getByTestId("service-code-server-restart").click();
    await page.getByTestId("service-action-done").waitFor({ timeout: 150000 }).catch(() => {});
    row = await codeRowState(page, "up");
    check(Boolean(row), "Restart from the row: the code server is up again");
    await row.getByTestId("service-code-server-stop").click();
    row = await codeRowState(page, "down");
    check(Boolean(row), "Stop from the row: the code server is down");
    await row.getByTestId("service-code-server-start").click();
    row = await codeRowState(page, "up");
    check(Boolean(row), "Start from the row: the code server is up");
    await row.getByTestId("service-code-server-stop").click();
    row = await codeRowState(page, "down");
    check(Boolean(row), "Stop from the row again: left stopped");
    await ctx.close();
  }
} catch (e) {
  check(false, `walk error: ${e?.message ?? e}`);
  if (current && !current.isClosed()) {
    console.log(`   at ${current.url()}`);
    console.log(`   page: ${(await current.locator("body").innerText().catch(() => "")).slice(0, 600).replace(/\s+/g, " ")}`);
    await current.screenshot({ path: path.join(out, "walk-error.png") }).catch(() => {});
  }
} finally {
  await browser.close();
}
console.log(failed ? `RESULT: ${failed} check(s) FAILED` : "RESULT: all walk checks passed");
process.exit(failed ? 1 : 0);
