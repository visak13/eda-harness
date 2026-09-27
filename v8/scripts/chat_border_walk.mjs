// t-6129a95a3d chat-pane frame screenshots: the epic, ticket and topic chats in the light and dark Heronry
// themes. Private board only (drill_cutover_copy.ps1 -WebDist <dir> -Shots <dir> runs it on the imported copy).
//
//   WALK_OWNER_TOKEN=<token> node scripts/chat_border_walk.mjs <board-base-url> <out-dir> <epic> <ticket> <topic>
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [base, out, epic, ticket, topic] = process.argv.slice(2);
if (!base || !out || !epic || !ticket || !topic) {
  console.error("usage: node scripts/chat_border_walk.mjs <base-url> <out-dir> <epic> <ticket> <topic>");
  process.exit(2);
}
const as = `as=owner&token=${encodeURIComponent(process.env.WALK_OWNER_TOKEN ?? "")}`;
const views = [
  ["epic", `/ui/epic/${epic}`, "thread"],
  ["ticket", `/ui/ticket/${ticket}`, "thread"],
  ["topic", `/ui/library/topics/${topic}`, "topic-thread"],
];
const browser = await chromium.launch();
let failed = 0;
try {
  for (const theme of ["heronry", "heronry-dark"]) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript((t) => { try { localStorage.setItem("edp8.theme", t); } catch { /* private mode */ } }, theme);
    const page = await ctx.newPage();
    for (const [name, url, testid] of views) {
      await page.goto(`${base}${url}?${as}`);
      const pane = page.getByTestId(testid).first();
      await pane.waitFor({ timeout: 20000 });
      await pane.scrollIntoViewIfNeeded();
      await page.waitForTimeout(700);
      const border = await page.evaluate((id) => {
        const el = document.querySelector(`[data-testid="${id}"]`);
        const list = id === "thread" ? el : el?.querySelector("ul");
        if (!list) return "none";
        const s = getComputedStyle(list);
        return `${s.borderTopWidth} ${s.borderTopStyle} ${s.borderTopColor}; overflow-y ${s.overflowY}`;
      }, testid);
      const set = await page.evaluate(() => document.documentElement.dataset.theme);
      console.log(`${theme} ${name}: data-theme=${set} border=${border}`);
      if (!border.startsWith("1px solid")) failed++;
      await page.screenshot({ path: path.join(out, `${theme}-${name}.png`) });
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
console.log(failed ? `RESULT: ${failed} view(s) without the frame` : "RESULT: every chat pane is framed");
process.exit(failed ? 1 : 0);
