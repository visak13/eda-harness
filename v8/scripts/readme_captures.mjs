// README screenshots: real 1440x900 captures of a running board (never a render).
//
//   node scripts/readme_captures.mjs <board-base-url> <epic-id> [out-dir]
//
// Point it at a PRIVATE board serving a copy of the fleet DB (sqlite backup), not at the live
// fleet board: opening pages as the owner can move the owner's read state. Default out-dir is
// ../docs/readme (repo root). Uses the chromium that `npx --prefix web playwright install` fetched.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [base, epic, outArg] = process.argv.slice(2);
if (!base || !epic) { console.error("usage: node scripts/readme_captures.mjs <base-url> <epic-id> [out-dir]"); process.exit(2); }
const OUT = outArg ?? path.join(here, "..", "..", "docs", "readme");
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: "light" });
const page = await context.newPage();
const shot = async (name) => { await page.waitForTimeout(600); await page.screenshot({ path: path.join(OUT, `${name}.png`) }); console.log(`wrote ${name}.png`); };
const settle = async () => { await page.waitForLoadState("networkidle").catch(() => {}); await page.waitForTimeout(400); };

try {
  // Epic page: title bar and composer expanded, conversation with Markdown messages.
  await page.goto(`${base}/ui/epic/${epic}?as=owner`);
  await page.getByTestId("conversation").waitFor();
  await settle();
  await shot("epic-expanded");

  // Same page with the title bar and the message box collapsed (remembered per viewer).
  await page.getByRole("button", { name: "Collapse title bar" }).click();
  await page.getByRole("button", { name: "Collapse message box" }).click();
  await page.getByTestId("composer-collapsed-bar").waitFor();
  await shot("epic-collapsed");
  await page.getByRole("button", { name: "Expand title bar" }).click();
  await page.getByTestId("composer-collapsed-bar").click();

  // Design review modal over the epic.
  await page.getByTestId("work-design").click();
  await page.getByRole("dialog").first().waitFor();
  await settle();
  await shot("design-review");
  await page.keyboard.press("Escape");

  // Needs you (the owner's open asks and gates).
  await page.goto(`${base}/ui/me?as=owner`);
  await settle();
  await shot("needs-you");

  // Seats.
  await page.goto(`${base}/ui/seats?as=owner`);
  await page.getByRole("table", { name: "Seats" }).waitFor();
  await settle();
  await shot("seats");

  // Settings.
  await page.goto(`${base}/ui/settings?as=owner`);
  await settle();
  await shot("settings");
} finally {
  await browser.close();
}
