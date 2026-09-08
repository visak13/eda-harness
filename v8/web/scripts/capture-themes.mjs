// One-off look-evidence capture: loads the shell on the live board in each theme and
// writes a 1440×900 PNG. Not part of the test suite — run manually to refresh demo shots.
//   node scripts/capture-themes.mjs <outDir> [baseUrl]
import { chromium } from "@playwright/test";
import path from "node:path";

const OUT = process.argv[2] ?? ".";
const BASE = process.argv[3] ?? "http://127.0.0.1:9400";
const CHROMIUM =
  process.env.EDP8_CHROMIUM ??
  path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1234", "chrome-win64", "chrome.exe");
const THEMES = ["folio", "dusk", "ember", "folio-hc"];

const browser = await chromium.launch({ executablePath: CHROMIUM });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();

await page.goto(`${BASE}/app/me?as=owner`);
for (const t of THEMES) {
  await page.evaluate((theme) => localStorage.setItem("edp8.theme", theme), t);
  await page.reload();
  await page.locator("main h1").waitFor();
  const file = path.join(OUT, `shell-${t}.png`);
  await page.screenshot({ path: file });
  console.log(`wrote ${file}`);
}

await browser.close();
