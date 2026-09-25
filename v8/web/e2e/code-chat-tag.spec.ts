// C4 smoke (s-a34658f02f; design-10b21760d9 §4.1): Tag selection with the chat view open puts a removable
// code chip in the composer (no palette pop-ups) and the sent message carries code_context; with the chat
// view never opened, the S5 palette chain still comes up. REAL code-server, this file's own e2e board
// (never :9400), temp user-data/extensions dirs (never :9410 or v8/.data/code); teardown kills only the
// code-server this file spawned. Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed
// Firefox through the moz-firefox channel. Run one browser at a time.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c4-owner-tok-3e9a61d0b7";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-chat-tag", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-chat-tag", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let repo = "";
let head = "";
let cs: CodeServer | null = null;
let page: Page;
let story = "";

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };

// -- workbench ------------------------------------------------------------------------------------
const quick = (p: Page) => p.locator(".quick-input-widget");
const quickRow = (p: Page, text: string | RegExp) => quick(p).locator(".monaco-list-row", { hasText: text }).first();
async function runCommand(title: string): Promise<void> {
  await page.keyboard.press("F1");
  await expect(quick(page)).toBeVisible();
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
async function openFile(name: string): Promise<void> {
  await runCommand("Go to File...");
  await quick(page).locator("input").fill(name);
  await expect(quickRow(page, name)).toBeVisible({ timeout: 15_000 });
  await quickRow(page, name).click();
  await expect(page.locator(".monaco-editor .view-lines").first()).toBeVisible();
}
/** Whole lines from..to with the keyboard; the selection ends mid-line (Shift+End). */
async function selectLines(from: number, to: number): Promise<void> {
  await runCommand("Go to Line/Column...");
  await quick(page).locator("input").fill(`:${from}`);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Home");
  for (let i = from; i < to; i++) await page.keyboard.press("Shift+ArrowDown");
  await page.keyboard.press("Shift+End");
}
/** The chat webview's document: two iframes deep (the only webview this window opens). */
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };

const lineText = (n: number) => `value_${n} = ${n}  # line ${n}`;
const snippetOf = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => lineText(a + i)).join("\n");
const sha = (s: string) => createHash("sha256").update(s, "utf8").digest("hex");

/** The newest board message on the story whose text starts with `note`. */
async function sentMessage(note: string): Promise<any> {
  let msg: any;
  await expect.poll(async () => {
    const rows = await call("GET", `/v1/messages?ticket_id=${story}`, undefined, asOwner);
    msg = rows.find((m: any) => m.text.startsWith(note));
    return !!msg;
  }, { timeout: 20_000 }).toBe(true);
  return msg;
}

/** No palette step of the S5 chain is up (person, ticket, note or kind), and none comes up within 1.5 s. */
async function expectNoPalette(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await expect(quick(page)).toBeHidden();
    await page.waitForTimeout(500);
  }
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c4-"));
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Chip story", parent_id: EPIC() }, { "X-Participant": "arch" })).id;
  repo = path.join(tmp, "fixture-repo");
  fs.mkdirSync(path.join(repo, "src"), { recursive: true });
  fs.writeFileSync(path.join(repo, "src", "sample.py"), Array.from({ length: 25 }, (_, i) => lineText(i + 1)).join("\n") + "\n");
  const g = (a: string[]) => execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", ...a], { cwd: repo, encoding: "utf8" });
  g(["init", "-q", "-b", "main"]); g(["add", "src/sample.py"]); g(["commit", "-q", "-m", "fixture"]);
  head = g(["rev-parse", "HEAD"]).trim();
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  await call("GET", "/v1/participants/owner", undefined, asOwner); // token mode is live
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE(), "edp.sharedTreePaths": [repo] });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first()).toBeVisible({ timeout: 60_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C4_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("chat view never opened: ctrl+alt+m runs the S5 palette chain (person picker first)", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("iframe.webview")).toHaveCount(0); // the chat view was never resolved
  await openFile("sample.py");
  await selectLines(3, 5);
  await page.keyboard.press("Control+Alt+M");
  await expect(quick(page).locator(".quick-input-title, input").first()).toBeVisible({ timeout: 15_000 });
  await expect(quick(page)).toContainText("EDP: tag src/sample.py:L3-5 to");
  await page.screenshot({ path: shot("palette-when-chat-never-opened.png") });
  await page.keyboard.press("Escape"); // cancelling ends the command, nothing is sent
  await expect(quick(page)).toBeHidden();
  expect((await call("GET", `/v1/messages?ticket_id=${story}`, undefined, asOwner)).length).toBe(0);
});

test("chat view open, no thread yet: the tag opens the thread picker, then the chip lands in that thread", async () => {
  await runCommand("EDP: Open chat");
  const c = chat();
  await expect(c.locator("#pick")).toBeVisible({ timeout: 20_000 });
  await openFile("sample.py");
  await selectLines(3, 5);
  // a cancelled thread picker inserts nothing and sends nothing
  await page.keyboard.press("Control+Alt+M");
  await expect(quickRow(page, "Chip story")).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("Escape");
  await expect(quick(page)).toBeHidden();
  await page.waitForTimeout(1000);
  await expect(c.locator("#code-chip")).toBeHidden();
  await expect(c.locator("#crumb-current")).toBeHidden();
  await openFile("sample.py");
  await selectLines(3, 5);
  await page.keyboard.press("Control+Alt+M");
  await expect(quickRow(page, "Chip story")).toBeVisible({ timeout: 15_000 });
  await expect(quick(page).locator(".quick-input-title")).toContainText("EDP chat: open a thread");
  await quickRow(page, "Chip story").click();
  await expect(c.locator("#crumb-current")).toHaveText("Chip story", { timeout: 20_000 });
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L3-5 @${head.slice(0, 7)}`, { timeout: 10_000 });
  await expect(c.locator("#code-chip .chip-preview")).toHaveText(snippetOf(3, 5));
  await expect(c.locator("#composer")).toBeFocused();
});

test("ctrl+alt+m with the thread open: chip, no palette; the send carries code_context and the anchor line", async () => {
  const c = chat();
  // start clean: remove the chip the previous test left
  await c.locator("#code-chip-remove").click();
  await expect(c.locator("#code-chip")).toBeHidden();
  await openFile("sample.py");
  await selectLines(10, 20);
  await page.keyboard.press("Control+Alt+M");
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L10-20 @${head.slice(0, 7)}`, { timeout: 10_000 });
  await expect(c.locator("#code-chip .chip-meta")).toHaveText("11 lines");
  await expectNoPalette();
  await expect(c.locator("#composer")).toBeFocused();
  await page.screenshot({ path: shot("chip-in-composer.png") });
  await c.locator("#composer").pressSequentially("why is this block here?");
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#code-chip")).toBeHidden({ timeout: 10_000 });
  await expect(c.locator("#composer")).toHaveValue("");
  const m = await sentMessage("why is this block here?");
  const want = snippetOf(10, 20);
  expect(m.by ?? m.created_by).toBe("owner");
  expect(m.code_context).toMatchObject({ path: "src/sample.py", line_start: 10, line_end: 20, commit: head, dirty: false, snippet: want, snippet_sha: sha(want) });
  expect(m.code_context.repo_root.toLowerCase()).toBe(repo.toLowerCase());
  expect(m.text).toBe(`why is this block here?\n\n\`src/sample.py:L10-20 @${head.slice(0, 7)}\``);
  // the panel shows it as a code card
  await expect(c.locator(".msg .code-card", { hasText: "src/sample.py:L10-20" })).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: shot("chip-sent-code-card.png") });
  fs.writeFileSync(shot("sent-message.json"), JSON.stringify({ id: m.id, text: m.text, code_context: m.code_context }, null, 1));
});

test("right-click → Tag selection: chip; a second tag replaces it; removing it sends a plain note", async () => {
  const c = chat();
  await openFile("sample.py");
  await selectLines(6, 7);
  await page.locator(".monaco-editor .view-line", { hasText: lineText(6) }).first().click({ button: "right" });
  const item = page.locator(".monaco-menu .action-label", { hasText: "Tag selection on board…" });
  await expect(item).toBeVisible({ timeout: 10_000 });
  // the workbench menu ignored a synthetic click right after it opened (measured: item highlighted, menu
  // still up); hovering focuses the item and Enter runs it, the way a keyboard user picks it
  await item.hover();
  await page.keyboard.press("Enter");
  await expect(item).toBeHidden();
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L6-7 @${head.slice(0, 7)}`, { timeout: 10_000 });
  await expectNoPalette();
  // one chip per composer: a second tag replaces it
  await openFile("sample.py");
  await selectLines(12, 12);
  await page.keyboard.press("Control+Alt+M");
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L12-12 @${head.slice(0, 7)}`, { timeout: 10_000 });
  await expect(c.locator("#code-chip")).toHaveCount(1);
  await c.locator("#code-chip-remove").click();
  await expect(c.locator("#code-chip")).toBeHidden();
  await c.locator("#composer").pressSequentially("plain note after removing the chip");
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#composer")).toHaveValue("", { timeout: 10_000 });
  const m = await sentMessage("plain note after removing the chip");
  expect(m.code_context ?? null).toBeNull();
  expect(m.text).toBe("plain note after removing the chip");
});

test("with the chat side bar hidden, a tag reveals it and the chip and composer focus arrive", async () => {
  const c = chat();
  await runCommand("View: Toggle Secondary Side Bar Visibility");
  await expect(page.locator(".part.auxiliarybar")).toBeHidden({ timeout: 10_000 });
  await openFile("sample.py");
  await selectLines(8, 9);
  await page.keyboard.press("Control+Alt+M");
  await expect(page.locator(".part.auxiliarybar")).toBeVisible({ timeout: 10_000 });
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L8-9 @${head.slice(0, 7)}`, { timeout: 15_000 });
  await expect(c.locator("#composer")).toBeFocused();
  await expectNoPalette();
  await expect(c.locator("#composer")).toHaveAttribute("aria-describedby", "ac-status code-chip-label");
  // the reloaded view is live again: a board message still arrives
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "after the side bar came back" }, asOwner);
  await expect(c.locator(".msg .body", { hasText: "after the side bar came back" })).toBeVisible({ timeout: 10_000 });
  await c.locator("#code-chip-remove").click();
  await expect(c.locator("#code-chip")).toBeHidden();
});

test("a dirty buffer marks the chip and the sent anchor dirty", async () => {
  const c = chat();
  await openFile("sample.py");
  await runCommand("Go to Line/Column...");
  await quick(page).locator("input").fill(":1");
  await page.keyboard.press("Enter");
  await page.keyboard.press("End");
  await page.keyboard.type("  # unsaved edit");
  await selectLines(2, 3);
  await page.keyboard.press("Control+Alt+M");
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L2-3 @${head.slice(0, 7)}[dirty]`, { timeout: 10_000 });
  await c.locator("#composer").pressSequentially("dirty lines");
  await page.keyboard.press("Control+Enter");
  const m = await sentMessage("dirty lines");
  expect(m.code_context).toMatchObject({ line_start: 2, line_end: 3, dirty: true });
  expect(m.text).toContain(`src/sample.py:L2-3 @${head.slice(0, 7)}[dirty]`);
});
