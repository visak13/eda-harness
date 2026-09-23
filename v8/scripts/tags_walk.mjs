// Browser half of scripts/tags_walk.py (t-683d0033bb): the owner types tags into the quick-task and new-epic
// dialogs of a PRIVATE board. Prints one JSON line with what it saw; screenshots go to the out dir.
//   node scripts/tags_walk.mjs <base> <quick-task|new-epic> '<json args>' <outdir>
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(path.resolve("web/package.json"));
const { chromium } = require("playwright");

const [base, mode, rawArgs, out] = process.argv.slice(2);
const A = JSON.parse(rawArgs || "{}");
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1,
  extraHTTPHeaders: { "X-Participant": "owner" } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
const shot = (name) => page.screenshot({ path: path.join(out, `${name}.png`), fullPage: false });
const go = async (p, sel) => {
  await page.goto(`${base}/ui${p}${p.includes("?") ? "&" : "?"}as=owner`, { waitUntil: "load" });
  if (sel) await page.waitForSelector(sel, { timeout: 30000 });
};
const t = (id) => page.getByTestId(id);
const result = {};
try {
  if (mode === "quick-task") {
    await go("/epics", '[data-testid="quick-task-open"]');
    await t("quick-task-open").click();
    await t("quick-task-title").fill(A.title);
    await t("quick-task-words").fill(A.words);
    await t("quick-task-tags").fill(A.tags);
    result.help = await t("quick-task-tags-help").innerText();
    await page.waitForFunction(() => !document.querySelector('[data-testid="quick-task-create"]')?.disabled, null, { timeout: 30000 });
    await shot("01-quick-task-dialog-tags");
    await t("quick-task-create").click();
    await page.waitForURL(/\/ui\/ticket\/s-/, { timeout: 30000 });
    result.story = page.url().match(/s-[0-9a-f]+/)[0];
    await page.waitForSelector('[data-testid="conversation-composer"]', { timeout: 30000 });
    await page.getByText("Library auto-link at quick task").first().waitFor({ timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(800);
    result.thread = (await page.locator("body").innerText()).split("\n").filter((l) => l.includes("Library auto-link")).join(" | ");
    const note = page.getByText("Library auto-link at quick task").first();
    if (await note.count()) await note.scrollIntoViewIfNeeded();
    await shot("02-quick-task-autolink-note");
  } else if (mode === "new-epic") {
    await go("/epics", '[data-testid="new-epic-open"]');
    await t("new-epic-open").click();
    await t("new-epic-title").fill(A.title);
    await t("new-epic-words").fill(A.words);
    await t("new-epic-tags").fill(A.tags);
    await page.waitForSelector('[data-testid^="new-epic-row-"]', { timeout: 30000 });
    result.help = await t("new-epic-tags-help").innerText();
    await shot("03-new-epic-dialog-tags");
    await t("new-epic-create").click();
    await page.waitForURL(/\/ui\/epic\/epic-/, { timeout: 30000 });
    result.epic = page.url().match(/epic-[0-9a-f]+/)[0];
    await page.waitForTimeout(800);
    await shot("04-new-epic-page");
  }
} catch (e) {
  result.error = String(e).slice(0, 400);
  await shot(`error-${mode}`).catch(() => {});
} finally {
  result.pageErrors = errors;
  console.log(JSON.stringify(result));
  await browser.close();
}
