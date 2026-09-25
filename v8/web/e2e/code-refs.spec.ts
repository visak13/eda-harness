// C24 smoke in the VS Code chat (s-5d1b171d57; owner m-0f727b0c57): `$` in the chat composer and in a quote note
// opens the board-object picker (this epic's tickets, docs and live decisions first); '$5' and '$env:X' open none;
// Enter picks and inserts `$<id> (<title>) `; Esc closes and keeps the text. The sent text and note carry the ids;
// in the panel each `$<id>` is a chip: a doc opens the EDP reader, a decision focuses its row in the Decisions tab,
// a ticket opens its board page. REAL code-server, this file's own e2e board (never :9400), temp user-data and
// extensions dirs (never :9410 or v8/.data/code); teardown kills only the code-server this file spawned.
// Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox (moz-firefox). One at a time.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c24-owner-tok-7d2e91b0c4";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-refs", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-refs", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let cs: CodeServer | null = null;
let page: Page;
let story = "", other = "", design = "", decision = "", ask = "";

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const arch = { "X-Participant": "arch" };

const quick = (p: Page) => p.locator(".quick-input-widget");
const quickRow = (p: Page, text: string | RegExp) => quick(p).locator(".monaco-list-row", { hasText: text }).first();
async function runCommand(title: string): Promise<void> {
  await expect(async () => {
    if (!(await quick(page).isVisible())) await page.keyboard.press("F1");
    await expect(quick(page)).toBeVisible({ timeout: 1_500 });
  }).toPass({ timeout: 15_000 });
  await quick(page).locator("input").fill(`>${title}`);
  await quickRow(page, title).click();
}
async function typeInput(value: string, title: string): Promise<void> {
  await expect(quick(page).locator(".quick-input-title")).toContainText(title);
  const input = quick(page).locator("input");
  await input.fill("");
  await input.pressSequentially(value);
  await page.keyboard.press("Enter");
}
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
const composer = () => chat().locator("#composer");

async function selectIn(root: FrameLocator, sel: string, phrase: string): Promise<void> {
  await root.locator(sel).first().evaluate((el, ph) => {
    const d = el.ownerDocument, walk = d.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const i = (n.textContent ?? "").indexOf(ph);
      if (i < 0) continue;
      const r = d.createRange();
      r.setStart(n, i); r.setEnd(n, i + ph.length);
      const s = d.getSelection()!;
      s.removeAllRanges(); s.addRange(r);
      return;
    }
    throw new Error(`not found: ${ph}`);
  }, phrase);
}

/** Arrow down the open $ list `list` until `id` is the active row, then Enter. */
async function pick(list: string, id: string): Promise<void> {
  const l = chat().locator(list);
  await expect(l.locator(`[data-ref="${id}"]`)).toBeVisible({ timeout: 10_000 });
  for (let i = 0; i < 12; i++) {
    if ((await l.locator('[aria-selected="true"]').getAttribute("data-ref")) === id) { await page.keyboard.press("Enter"); return; }
    await page.keyboard.press("ArrowDown");
  }
  throw new Error(`${id} never became the active row`);
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c24-"));
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Refs story", parent_id: EPIC() }, arch)).id;
  other = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "C2 smoke target", parent_id: EPIC() }, arch)).id;
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "C2 smoke design", body_md: "# C2 smoke design\n\nDollar references point at board objects.\n", scope: EPIC() }, arch)).id;
  await call("PATCH", `/v1/tickets/${story}`, { design_ref: design }, arch);
  decision = (await call("POST", "/v1/decisions", { scope: story, text: "C2 smoke ruling: $ references board objects" }, arch)).id;
  ask = (await call("POST", "/v1/messages", { ticket_id: story, kind: "question", to: "owner", text: "Which ruling covers the dollar picker?" }, arch)).id;
  const repo = path.join(tmp, "fixture-repo");
  fs.mkdirSync(repo, { recursive: true });
  fs.writeFileSync(path.join(repo, "README.md"), "fixture\n");
  const g = (a: string[]) => execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", ...a], { cwd: repo, encoding: "utf8" });
  g(["init", "-q", "-b", "main"]); g(["add", "README.md"]); g(["commit", "-q", "-m", "fixture"]);
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  await call("GET", "/v1/participants/owner", undefined, asOwner); // token mode is live
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE() });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Open chat");
  await chat().locator("#pick").click({ timeout: 20_000 });
  await expect(quickRow(page, "Refs story")).toBeVisible({ timeout: 15_000 });
  await quickRow(page, "Refs story").click();
  await expect(chat().locator("#crumb-current")).toHaveText("Refs story", { timeout: 20_000 });
  await expect(chat().locator(`.msg[data-id="${ask}"]`)).toBeVisible({ timeout: 20_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C24_KEEP_TMP) {
    try { fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 }); }
    catch (e) { console.warn(`left ${tmp}: ${(e as Error).message}`); }
  }
});

test("'$5' and '$env:X' open no picker", async () => {
  await composer().click();
  await composer().pressSequentially("costs $5 and $env:X ");
  await page.waitForTimeout(800);
  await expect(chat().locator("#refs")).toBeHidden();
  await page.screenshot({ path: shot("01-no-picker-for-dollar5-env.png") });
  await composer().fill("");
});

test("the composer: '$C2' lists this epic's story, doc and decision; Enter picks; Esc keeps the text", async () => {
  const c = chat();
  await composer().click();
  await composer().pressSequentially("see $C2");
  await expect(c.locator("#refs")).toBeVisible({ timeout: 10_000 });
  for (const id of [other, design, decision]) await expect(c.locator(`#refs [data-ref="${id}"]`)).toHaveAttribute("data-group", "scope");
  await expect(c.locator(`#refs [data-ref="${other}"]`)).toContainText(`story $${other}`);
  await expect(composer()).toHaveAttribute("aria-controls", "refs");
  await page.screenshot({ path: shot("02-composer-picker.png") });
  await pick("#refs", other);
  await expect(c.locator("#refs")).toBeHidden();
  await composer().pressSequentially("and $C2");
  await pick("#refs", design);
  await composer().pressSequentially("per $C2");
  await expect(c.locator("#refs")).toBeVisible({ timeout: 10_000 });
  await composer().press("Escape");
  await expect(c.locator("#refs")).toBeHidden();
  await expect(composer()).toHaveValue(/per \$C2$/);
  await composer().press("Backspace"); await composer().press("Backspace");
  await composer().pressSequentially("C2");
  await pick("#refs", decision);
  await expect(composer()).toHaveValue(`see $${other} (C2 smoke target) and $${design} (C2 smoke design) per $${decision} (C2 smoke ruling: $ references board objects) `);
});

test("a quote note: '$C2' in the popover note picks a decision, a story and a doc; the send carries the ids", async () => {
  const c = chat();
  await selectIn(c, `.msg[data-id="${ask}"] > .body`, "covers the dollar picker");
  await expect(c.locator("#quote-selection")).toBeVisible({ timeout: 5_000 });
  await c.locator("#quote-selection").click();
  await expect(c.locator("#quote-pop-note")).toBeFocused();
  await page.keyboard.type("ruled in $C2");
  await expect(c.locator("#qn-refs")).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: shot("03-note-picker.png") });
  await pick("#qn-refs", decision);
  await expect(c.locator("#quote-pop")).toBeVisible(); // Enter picked; it did not add the quote
  await page.keyboard.type("for $C2");
  await pick("#qn-refs", other);
  await page.keyboard.type("see $C2");
  await pick("#qn-refs", design);
  await expect(c.locator("#quote-pop-note")).toHaveValue(`ruled in $${decision} (C2 smoke ruling: $ references board objects) for $${other} (C2 smoke target) see $${design} (C2 smoke design) `);
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#quote-pop")).toBeHidden();
  await expect(c.locator("#quote-chips > li.qchip")).toHaveCount(1, { timeout: 10_000 });
  await composer().click();
  await composer().press("Control+Enter");
  await expect(composer()).toHaveValue("", { timeout: 10_000 });
  let sent: any;
  await expect.poll(async () => {
    sent = (await call("GET", `/v1/messages?ticket_id=${story}`, undefined, asOwner)).find((m: any) => m.text.startsWith("see $"));
    return !!sent;
  }, { timeout: 20_000 }).toBe(true);
  for (const id of [other, design, decision]) expect(sent.text).toContain(`$${id} (`);
  for (const id of [other, design, decision]) expect(sent.quotes[0].note).toContain(`$${id} (`);
  fs.writeFileSync(shot("sent-message.json"), JSON.stringify({ id: sent.id, text: sent.text, note: sent.quotes[0].note }, null, 1));
});

test("chips: the doc opens the reader, the decision its Decisions row, the story its board page", async () => {
  const c = chat();
  const msg = c.locator(".msg", { hasText: "see" }).last();
  await expect(msg.locator("button.ref-chip")).toHaveCount(6, { timeout: 15_000 });
  await expect(msg.locator(`button.ref-chip[data-ref="${other}"]`).first()).toContainText("C2 smoke target");
  await msg.scrollIntoViewIfNeeded();
  await page.screenshot({ path: shot("04-chips.png") });
  // doc -> the EDP reader
  await msg.locator(`button.ref-chip[data-ref="${design}"]`).first().click();
  await expect.poll(async () => {
    for (const f of page.frames()) if ((await f.title().catch(() => "")) === `EDP ${design} v1`) return true;
    return false;
  }, { timeout: 30_000, intervals: [500] }).toBe(true);
  await page.screenshot({ path: shot("05-doc-chip-opens-reader.png") });
  // decision (the quote card's note) -> its row in the Decisions tab
  await msg.locator(`.qc-note button.ref-chip[data-ref="${decision}"]`).click();
  const row = c.locator(`#panel-decisions [data-id="${decision}"]`);
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row).toBeFocused();
  await page.screenshot({ path: shot("06-decision-chip-focuses-row.png") });
  // story -> its board page (openExternal: a new tab, or VS Code's "open external website" prompt first)
  await c.locator("#tab-chat").first().click().catch(() => undefined);
  const popup = page.context().waitForEvent("page", { timeout: 20_000 });
  await c.locator(".msg", { hasText: "see" }).last().locator(`button.ref-chip[data-ref="${other}"]`).first().click();
  const open = page.locator(".monaco-dialog-box button", { hasText: /^Open$/ });
  if (await open.isVisible({ timeout: 3_000 }).catch(() => false)) { await page.screenshot({ path: shot("07a-open-external-prompt.png") }); await open.click(); }
  const tab = await popup;
  await expect(tab).toHaveURL(new RegExp(`/ui/ticket/${other}`), { timeout: 15_000 });
  await tab.screenshot({ path: shot("07-story-chip-opens-board-page.png") });
  await tab.close();
});
