// Browser half of scripts/qa_walk.py (epic-6a8a6020fd acceptance): one mode per call against a PRIVATE
// board, as the owner. Prints one JSON line with what it saw; screenshots go to the out dir.
//   node scripts/qa_walk.mjs <base> <mode> '<json args>' <outdir>
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(path.resolve("web/package.json"));
const { chromium } = require("playwright");

const [base, mode, rawArgs, out] = process.argv.slice(2);
const A = JSON.parse(rawArgs || "{}");
const who = A.as || "owner";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1,
  extraHTTPHeaders: { "X-Participant": who } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
const shot = (name) => page.screenshot({ path: path.join(out, `${name}.png`), fullPage: false });
const go = async (p, sel) => {
  await page.goto(`${base}/ui${p}${p.includes("?") ? "&" : "?"}as=${who}`, { waitUntil: "load" });
  if (sel) await page.waitForSelector(sel, { timeout: 30000 });
};
const t = (id) => page.getByTestId(id);
const actions = async (label) => {
  await t("actions-open").click();
  await page.getByRole("menuitem", { name: new RegExp(label, "i") }).click();
};
const result = {};
try {
  if (mode === "new-epic") {
    await go("/epics", '[data-testid="new-epic-open"]');
    await t("new-epic-open").click();
    await t("new-epic-title").fill(A.title);
    await t("new-epic-words").fill(A.words);
    const rows = await t("new-epic-role-models").locator('[data-testid^="new-epic-row-"]').count();
    result.roleRows = rows;
    result.defaults = {};
    for (const r of ["architect", "engineer", "qa", "adversary", "sme"]) result.defaults[r] = await t(`new-epic-model-${r}`).inputValue();
    for (const [r, m] of Object.entries(A.picks || {})) await t(`new-epic-model-${r}`).selectOption(m);
    for (const [r, e] of Object.entries(A.efforts || {})) await t(`new-epic-effort-${r}`).selectOption(e);
    await shot("01-new-epic-dialog");
    const spawn = t("new-epic-spawn");
    if (await spawn.count()) { if (A.spawn === false) { if (await spawn.isChecked()) await spawn.uncheck(); } }
    await t("new-epic-create").click();
    await page.waitForURL(/\/ui\/epic\/epic-/, { timeout: 30000 });
    result.epic = page.url().match(/epic-[0-9a-f]+/)[0];
    await page.waitForSelector('[data-testid="conversation-composer"]', { timeout: 30000 });
    await shot("02-epic-page");
    result.headerText = (await page.locator("header, [data-testid='epic-pulse']").allInnerTexts()).join(" | ").slice(0, 600);
    result.modelsStrip = await page.locator("text=/^MODELS$/").count();
    await actions("Models");
    await page.waitForSelector('[data-testid="models-dialog"]');
    result.dialogFresh = {};
    for (const r of ["architect", "engineer", "qa", "adversary", "sme"]) result.dialogFresh[r] = await t(`models-model-${r}`).inputValue();
    await page.reload({ waitUntil: "load" });
    await page.waitForSelector('[data-testid="conversation-composer"]', { timeout: 30000 });
    await actions("Models");
    await page.waitForSelector('[data-testid="models-dialog"]');
    result.dialog = {};
    for (const r of ["architect", "engineer", "qa", "adversary", "sme"]) result.dialog[r] = await t(`models-model-${r}`).inputValue();
    await shot("03-models-dialog-epic");
  } else if (mode === "models-story") {
    await go(`/ticket/${A.story}`, '[data-testid="conversation-composer"]');
    result.modelsStrip = await page.locator("text=/^MODELS$/").count();
    await actions("Models");
    await page.waitForSelector('[data-testid="models-dialog"]');
    result.before = await t(`models-model-engineer`).inputValue();
    await t("models-model-engineer").selectOption(A.engineer);
    await t("models-save").click();
    await page.waitForSelector('[data-testid="models-saved"]', { timeout: 15000 });
    result.saved = await t("models-saved").innerText();
    await shot("04-models-dialog-story");
  } else if (mode === "seats-spawn") {
    await go("/seats", '[data-testid="spawn-seat-form"]');
    result.roles = await t("spawn-seat-role").locator("option").allTextContents();
    await t("spawn-seat-role").selectOption("engineer");
    await t("spawn-seat-ticket").fill(A.story);
    await page.waitForFunction(() => document.querySelector('[data-testid="spawn-seat-model"] option'), null, { timeout: 15000 });
    result.models = await t("spawn-seat-model").locator("option").allInnerTexts();
    if (A.model) await t("spawn-seat-model").selectOption(A.model);
    result.preview = await t("spawn-seat-preview").innerText();
    await shot("05-seats-spawn-form");
    await t("spawn-seat-submit").click();
    await page.waitForSelector('[data-testid="spawn-seat-done"], [data-testid="spawn-seat-error"]', { timeout: 30000 });
    result.done = (await t("spawn-seat-done").count()) ? await t("spawn-seat-done").innerText() : null;
    result.error = (await t("spawn-seat-error").count()) ? await t("spawn-seat-error").innerText() : null;
    await shot("06-seats-spawn-done");
  } else if (mode === "quick-task") {
    await go("/epics", '[data-testid="quick-task-open"]');
    await t("quick-task-open").click();
    await t("quick-task-title").fill(A.title);
    await t("quick-task-words").fill(A.words);
    result.models = await t("quick-task-model-engineer").locator("option").allInnerTexts();
    await t("quick-task-model-engineer").selectOption(A.model);
    result.preview = await t("quick-task-preview").innerText();
    await shot("07-quick-task-dialog");
    await t("quick-task-create").click();
    await page.waitForURL(/\/ui\/ticket\/s-/, { timeout: 30000 });
    result.story = page.url().match(/s-[0-9a-f]+/)[0];
    await page.waitForSelector('[data-testid="conversation-composer"]', { timeout: 30000 });
    await page.waitForTimeout(800);
    result.assignedSeat = (await t("assigned-seat").count()) ? (await t("assigned-seat").innerText()).slice(0, 200) : null;
    await shot("08-quick-task-story");
  } else if (mode === "needs-you") {
    await go("/me", '[data-testid="needs-you"]');
    await page.waitForSelector('[data-testid="featured-signoff"]', { timeout: 30000 });
    result.needsYou = (await t("needs-you").innerText()).slice(0, 300);
    result.featured = (await t("featured-signoff").innerText()).slice(0, 300);
    await shot(`09-needs-you-${A.tag}`);
    await t("review-evidence").click();
    await page.waitForSelector('[data-testid="ruling-pane"]', { timeout: 15000 });
    result.buttons = { approve: await t("approve").count(), needsWork: await t("needs-work").count() };
    if (A.note) await t("note").fill(A.note);
    await shot(`10-ruling-${A.tag}`);
    await t(A.verdict === "pass" ? "approve" : "needs-work").click();
    await page.waitForTimeout(1500);
    await shot(`11-after-${A.tag}`);
  } else if (mode === "story-spawn") {
    await go(`/ticket/${A.story}`, '[data-testid="conversation-composer"]');
    await actions("Spawn seat");
    await page.waitForSelector('[data-testid="spawn-seat-form"]');
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="spawn-seat-role"] option').length > 0, null, { timeout: 15000 });
    result.roles = await t("spawn-seat-role").evaluate((el) => [...el.options].map((o) => o.value));
    await t("spawn-seat-role").selectOption(A.role);
    await page.waitForFunction(() => document.querySelector('[data-testid="spawn-seat-model"] option'), null, { timeout: 15000 });
    result.models = await t("spawn-seat-model").locator("option").allInnerTexts();
    if (A.model) await t("spawn-seat-model").selectOption(A.model);
    result.checkerNote = (await t("spawn-seat-checker-note").count()) ? await t("spawn-seat-checker-note").innerText() : null;
    result.assignVisible = await t("spawn-seat-assign").count();
    result.preview = await t("spawn-seat-preview").innerText();
    await shot(`12-story-spawn-${A.role}-form`);
    await t("spawn-seat-submit").click();
    await page.waitForSelector('[data-testid="spawn-seat-done"], [data-testid="spawn-seat-error"]', { timeout: 30000 });
    result.done = (await t("spawn-seat-done").count()) ? await t("spawn-seat-done").innerText() : null;
    result.error = (await t("spawn-seat-error").count()) ? await t("spawn-seat-error").innerText() : null;
    await shot(`13-story-spawn-${A.role}-done`);
  } else if (mode === "library") {
    await go("/library/knowledge", '[data-testid="knowledge"]');
    result.navIcon = await page.locator('nav a[href*="/library"] svg, nav a[href*="/library"] img').count();
    result.rowsAll = await t("knowledge-row").count();
    result.kinds = [...new Set(await t("knowledge-kind").allInnerTexts())];
    await shot("14-library-list");
    await t("knowledge-search").fill(A.search);
    await page.waitForTimeout(400);
    result.rowsSearch = await t("knowledge-row").count();
    await t("knowledge-search").fill("");
    await t("knowledge-tag").selectOption(A.tag);
    await page.waitForTimeout(400);
    result.rowsTag = await t("knowledge-row").count();
    await go("/library/knowledge", '[data-testid="knowledge"]');
    await t("knowledge-status-filter").selectOption("proposed");
    await page.waitForTimeout(400);
    result.rowsProposed = await t("knowledge-row").count();
    result.proposedBanner = await t("knowledge-proposed-banner").count();
    await shot("15-library-proposed");
    // open + edit the active doc (new version)
    await go(`/library/knowledge?k=${A.doc}`, '[data-testid="knowledge-detail"]');
    if (!(await t("knowledge-edit").count())) { await t("knowledge-row").filter({ hasText: A.docTitle }).first().click(); await page.waitForSelector('[data-testid="knowledge-edit"]'); }
    await t("knowledge-edit").click();
    await t("knowledge-edit-body").fill(A.newBody);
    await t("knowledge-save").click();
    await page.waitForTimeout(800);
    result.afterEdit = (await t("knowledge-read").innerText()).slice(0, 200);
    await shot("16-library-edited");
    // link to the epic, then unlink later from python's call
    await t("knowledge-link-epic").selectOption(A.epic);
    await t("knowledge-link").click();
    await page.waitForSelector('[data-testid="knowledge-linked"]', { timeout: 15000 });
    result.linked = (await t("knowledge-linked").innerText()).slice(0, 200);
    await shot("17-library-linked");
    // approve one proposal, reject another
    for (const [k, id] of [["approve", A.good], ["reject", A.bad]]) {
      await go(`/library/knowledge?k=${id}`, '[data-testid="knowledge-detail"]');
      if (!(await t(`knowledge-${k}`).count())) { await t("knowledge-status-filter").selectOption("proposed"); await t("knowledge-row").filter({ hasText: k === "approve" ? A.goodTitle : A.badTitle }).first().click(); }
      await page.waitForSelector(`[data-testid="knowledge-${k}"]`, { timeout: 15000 });
      result[`${k}Diff`] = await t("knowledge-diff").count();
      result[`${k}Source`] = (await t("knowledge-source").count()) ? await t("knowledge-source").innerText() : null;
      await shot(`18-library-${k}-before`);
      await t(`knowledge-${k}`).click();
      await page.waitForTimeout(800);
      result[`${k}Status`] = (await t("knowledge-status").count()) ? await t("knowledge-status").first().innerText() : null;
      await shot(`19-library-${k}-after`);
    }
  } else if (mode === "epic-knowledge") {
    await go(`/epic/${A.epic}`, '[data-testid="conversation-composer"]');
    await t("work-work").click();
    await page.waitForSelector('[data-testid="epic-work"]', { timeout: 15000 });
    await page.waitForTimeout(600);
    result.knowledge = (await t("epic-knowledge").count()) ? (await t("epic-knowledge").innerText()).slice(0, 300) : null;
    result.empty = await t("epic-knowledge-empty").count();
    result.sections = await page.evaluate(() => [...document.querySelectorAll("[data-testid]")].map((e) => e.dataset.testid).filter((x, i, a) => a.indexOf(x) === i).slice(0, 60));
    await shot(`20-epic-knowledge-${A.tag}`);
  } else if (mode === "unlink") {
    await go(`/library/knowledge?k=${A.doc}`, '[data-testid="knowledge-detail"]');
    await page.waitForSelector('[data-testid="knowledge-unlink"]', { timeout: 15000 });
    await t("knowledge-unlink").first().click();
    await page.waitForTimeout(800);
    result.linkedLeft = await t("knowledge-unlink").count();
  }
  result.errors = errors;
  console.log(JSON.stringify(result));
} catch (e) {
  await shot(`error-${mode}`).catch(() => {});
  console.log(JSON.stringify({ error: String(e).slice(0, 500), partial: result, errors }));
  process.exitCode = 1;
} finally {
  await browser.close();
}
