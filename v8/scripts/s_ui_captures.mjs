// S-UI (s-32ddc49d96) before/after screenshots: real captures of a PRIVATE board serving a sqlite
// backup of the fleet DB (never the fleet board: opening pages as the owner moves read state).
//
//   node scripts/s_ui_captures.mjs <board-base-url> <epic-id> <story-id> <before|after>
//
// Writes docs/evidence/s-ui/<phase>-<name>.png at 1280 and 1920 px wide.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [base, epic, story, phase] = process.argv.slice(2);
if (!base || !epic || !story || !phase) {
  console.error("usage: node scripts/s_ui_captures.mjs <base-url> <epic-id> <story-id> <before|after>");
  process.exit(2);
}
const OUT = path.join(here, "..", "docs", "evidence", "s-ui");
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const log = (s) => console.log(s);
try {
  for (const width of [1280, 1920]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1, colorScheme: "light" });
    const page = await context.newPage();
    const settle = async () => { await page.waitForTimeout(1200); };
    const shot = async (name) => {
      await settle();
      const file = `${phase}-${name}-${width}.png`;
      await page.screenshot({ path: path.join(OUT, file) });
      log(`shot ${file}`);
    };
    const tryStep = async (label, fn) => { try { await fn(); } catch (e) { log(`skip ${label}: ${String(e.message).split("\n")[0]}`); } };

    // Epic page: header (models, attention, title/purpose) + conversation + composer.
    await page.goto(`${base}/ui/epic/${epic}?as=owner`);
    await page.getByTestId("work-header").waitFor();
    await shot("epic");

    // Composer minimized.
    await tryStep("composer-collapse", async () => {
      const toggle = page.getByTestId("composer-collapse");
      if ((await toggle.getAttribute("aria-expanded")) === "true") await toggle.click();
      await shot("epic-composer-min");
      await toggle.click();
    });

    // Composer type dropdown (the label that wrapped).
    await tryStep("composer-type", async () => {
      await page.getByTestId("kind-picker").first().scrollIntoViewIfNeeded();
      await shot("epic-composer-type");
    });

    // Attention badge click (after: scrolls to + highlights the ask, or opens the list).
    await tryStep("attention", async () => {
      const badge = page.getByTestId("attention-asks");
      await badge.click({ timeout: 3000 });
      await page.waitForTimeout(900);
      await shot("attention-click");
      await page.keyboard.press("Escape");
    });

    // Models dialog under Actions.
    await tryStep("models-dialog", async () => {
      await page.getByTestId("actions-open").click();
      await page.getByTestId("action-models").click({ timeout: 3000 });
      await page.getByTestId("models-dialog").waitFor({ timeout: 3000 });
      await shot("epic-models-dialog");
      await page.keyboard.press("Escape");
    });

    // Story page (Models… reachable there too).
    await page.goto(`${base}/ui/ticket/${story}?as=owner`);
    await page.getByTestId("work-header").waitFor();
    await shot("story");
    await tryStep("story-models-dialog", async () => {
      await page.getByTestId("actions-open").click();
      await page.getByTestId("action-models").click({ timeout: 3000 });
      await page.getByTestId("models-dialog").waitFor({ timeout: 3000 });
      await shot("story-models-dialog");
      await page.keyboard.press("Escape");
    });

    // Decisions page, opened from the epic (after: ?epic= default + Needs you first).
    await page.goto(`${base}/ui/me?as=owner${phase === "after" ? `&epic=${epic}` : ""}`);
    await page.getByTestId("decisions").waitFor();
    await shot("decisions");

    // New epic + quick task dialogs (per-role effort).
    await page.goto(`${base}/ui/epics?as=owner`);
    await settle();
    await tryStep("new-epic", async () => {
      await page.getByRole("button", { name: /New epic/ }).click();
      await page.getByRole("dialog").first().waitFor({ timeout: 3000 });
      await shot("new-epic-dialog");
      await page.keyboard.press("Escape");
    });
    await tryStep("quick-task", async () => {
      await page.getByRole("button", { name: /Quick task/ }).click();
      await page.getByRole("dialog").first().waitFor({ timeout: 3000 });
      await shot("quick-task-dialog");
      await page.keyboard.press("Escape");
    });
    await context.close();
  }
} finally {
  await browser.close();
}
