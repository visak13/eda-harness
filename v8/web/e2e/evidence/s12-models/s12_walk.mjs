// S12 t-186b964fb1 walkthrough on a PRIVATE heronry instance (never the fleet). Env: SETUP_URL, BOARD, OUT.
import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";
const require = createRequire("C:/Work/Learning/eda-base3/v8/web/package.json");
const { chromium } = require("@playwright/test");

const { SETUP_URL, BOARD, OUT } = process.env;
fs.mkdirSync(OUT, { recursive: true });
const CHROMIUM = path.join(process.env.LOCALAPPDATA, "ms-playwright", "chromium-1234", "chrome-win64", "chrome.exe");
const log = (...a) => console.log("[walk]", ...a);
const results = {};
let n = 0;
const shot = async (page, name, el) => {
  const f = path.join(OUT, `${String(++n).padStart(2, "0")}-${name}.png`);
  if (el) await el.screenshot({ path: f }); else await page.screenshot({ path: f, fullPage: true });
  log("shot", f);
};
const byId = (page, id) => page.getByTestId(id);
const MODEL = "openrouter/qwen3-coder";

const browser = await chromium.launch({ executablePath: CHROMIUM });
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const a = await ctx.newPage();
  // ---- 0. sign in through the setup wizard; select claude + pi (codex off -> Fable ack)
  await a.goto(SETUP_URL);
  await byId(a, "setup-signed-in").waitFor({ timeout: 20000 });
  await byId(a, "setup-next").click();
  await byId(a, "pick-pi-input").waitFor({ timeout: 20000 });
  await a.waitForFunction(() => document.querySelector("[data-testid=pick-claude-input]")?.checked, null, { timeout: 20000 });
  await a.waitForTimeout(800);
  if (!(await byId(a, "pick-pi-input").isChecked())) await byId(a, "pick-pi-input").check();
  if (await byId(a, "fable-ack").count()) await byId(a, "fable-ack").check();
  await byId(a, "harness-selection-save").click();
  await byId(a, "setup-remote").waitFor({ timeout: 20000 });
  await byId(a, "setup-next").click();
  await byId(a, "setup-teammate-handle").fill("carol");
  await byId(a, "setup-teammate-invite").click();
  await byId(a, "setup-invite-link").waitFor({ timeout: 20000 });
  await byId(a, "setup-next").click();
  await byId(a, "setup-finish").click();
  await a.waitForURL(/\/ui\/epics/, { timeout: 20000 });

  // ---- 1. Admin -> Seats & models: the catalog, filtered to the selected harnesses
  await a.goto(`${BOARD}/ui/admin?tab=models`, { waitUntil: "load" });
  await byId(a, "models-table").waitFor({ timeout: 20000 });
  await a.waitForTimeout(800);
  results.selected_note = await byId(a, "models-editor").locator("p").first().innerText();
  results.rows_before = await a.locator("[data-testid^='model-row-']").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid").slice(10)));
  results.hidden = (await byId(a, "models-hidden").count()) ? await byId(a, "models-hidden").innerText() : null;
  results.warnings = (await byId(a, "models-warnings").count()) ? await byId(a, "models-warnings").innerText() : null;
  await shot(a, "admin-models-overview");

  // ---- 2. add a Pi model with a provider
  await byId(a, "model-add").click();
  await byId(a, "model-form-harness").selectOption("pi");
  await byId(a, "model-form-id").fill(MODEL);
  await byId(a, "model-form-provider").fill("openrouter");
  await byId(a, "model-form-window").fill("262144");
  await byId(a, "model-form-compact").fill("180000");
  await byId(a, "model-form-cap").selectOption("medium");
  await shot(a, "add-pi-model-form", byId(a, "models-editor"));
  await byId(a, "model-form-save").click();
  await byId(a, `model-row-${MODEL}`).waitFor({ timeout: 20000 });
  results.added_row = await byId(a, `model-row-${MODEL}`).innerText();
  results.added_done = await byId(a, "models-saved").innerText();
  await shot(a, "pi-model-added", byId(a, "models-editor"));

  // ---- 3. make it the engineer role's default
  await byId(a, `role-pick-engineer-${MODEL}-input`).check();
  await byId(a, "role-default-engineer").selectOption(MODEL);
  await shot(a, "role-default-staged", byId(a, "role-models"));
  await byId(a, "role-models-save").click();
  await a.waitForFunction((m) => document.querySelector(`[data-testid="model-row-${m}"]`)?.textContent?.includes("engineer (default)"), MODEL, { timeout: 20000 });
  results.role_row = await byId(a, `model-row-${MODEL}`).innerText();
  await shot(a, "role-default-saved");

  // ---- 4. test spawn -> the stub reply
  await byId(a, "test-spawn-model").selectOption(MODEL);
  await byId(a, "test-spawn-role").selectOption("engineer");
  await byId(a, "test-spawn-run").click();
  await byId(a, "test-spawn-reply").waitFor({ timeout: 30000 });
  results.test_spawn = await byId(a, "test-spawn-result").innerText();
  await shot(a, "test-spawn-reply", byId(a, "test-spawn"));

  // ---- 5. New Epic's SeatPicks reflect the edited catalog
  await a.goto(`${BOARD}/ui/epics`, { waitUntil: "load" });
  await byId(a, "new-epic-open").click();
  await byId(a, "new-epic-model-engineer").waitFor({ timeout: 20000 });
  await a.waitForTimeout(600);
  results.new_epic_engineer = await byId(a, "new-epic-model-engineer").inputValue();
  results.new_epic_engineer_options = await byId(a, "new-epic-model-engineer").locator("option").allInnerTexts();
  results.new_epic_engineer_cap = await byId(a, "new-epic-cap-engineer").innerText();
  results.new_epic_effort_disabled = await byId(a, "new-epic-effort-engineer").locator("option[disabled]").allInnerTexts();
  await shot(a, "new-epic-seatpicks", byId(a, "new-epic-dialog"));
  await a.keyboard.press("Escape");

  // ---- 6. a Pi provider without a credential is refused in the board's words
  await a.goto(`${BOARD}/ui/admin?tab=models`, { waitUntil: "load" });
  await byId(a, "models-table").waitFor({ timeout: 20000 });
  await byId(a, "model-add").click();
  await byId(a, "model-form-harness").selectOption("pi");
  await byId(a, "model-form-id").fill("groq/llama-4");
  await byId(a, "model-form-provider").fill("groq");
  await byId(a, "model-form-window").fill("131072");
  await byId(a, "model-form-compact").fill("100000");
  await byId(a, "model-form-save").click();
  await byId(a, "models-save-error").waitFor({ timeout: 20000 });
  results.refusal = await byId(a, "models-save-error").innerText();
  await byId(a, "models-save-error").scrollIntoViewIfNeeded();
  await shot(a, "no-credential-refused", byId(a, "models-editor"));
  await byId(a, "model-form-cancel").click();

  // ---- 7. remove the Pi model: gone from the table, the role and New Epic
  await byId(a, `model-remove-${MODEL}`).click();
  await byId(a, `model-row-${MODEL}`).waitFor({ state: "detached", timeout: 20000 });
  results.removed_done = await byId(a, "models-saved").innerText();
  await shot(a, "pi-model-removed");
  await a.goto(`${BOARD}/ui/epics`, { waitUntil: "load" });
  await byId(a, "new-epic-open").click();
  await byId(a, "new-epic-model-engineer").waitFor({ timeout: 20000 });
  await a.waitForTimeout(600);
  results.new_epic_after_remove = await byId(a, "new-epic-model-engineer").locator("option").allInnerTexts();
  await shot(a, "new-epic-after-remove", byId(a, "new-epic-dialog"));
} catch (e) {
  console.error("[walk] FAILED", e);
  results.error = String(e);
  for (const p of browser.contexts().flatMap((x) => x.pages())) { try { await shot(p, "failure"); } catch {} }
  process.exitCode = 1;
} finally {
  fs.writeFileSync(path.join(OUT, "results.json"), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
  await browser.close();
}
