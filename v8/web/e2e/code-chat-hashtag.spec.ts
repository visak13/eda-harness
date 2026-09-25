// C11 smoke (s-35ccc6d35f; design-10b21760d9 §13): `#` in the chat composer opens a picker over the
// workspace's files AND folders (gitignored and files.exclude'd paths left out, capped at 50); a pick
// inserts a backticked repo-relative path (a folder ends with `/`); several tags per message; no picker
// after a word character or inside a code span. The sent message is plain text on the board; in the
// panel a tagged file opens in the editor, a tagged folder reveals in the Explorer, and a path missing
// from this workspace stays plain text. REAL code-server, this file's own e2e board (never :9400), temp
// user-data/extensions dirs (never :9410 or v8/.data/code); teardown kills only the code-server this file
// spawned. Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox (moz-firefox).
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
const OWNER_TOKEN = "c11-owner-tok-5b0e2c94a1";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-chat-hashtag", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-chat-hashtag", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let repo = "";
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
/** The chat webview's document: two iframes deep (the only webview this window opens). */
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
const options = () => chat().locator("#paths [role=option]");
const composer = () => chat().locator("#composer");

async function sentMessage(start: string): Promise<any> {
  let msg: any;
  await expect.poll(async () => {
    const rows = await call("GET", `/v1/messages?ticket_id=${story}`, undefined, asOwner);
    msg = rows.find((m: any) => m.text.startsWith(start));
    return !!msg;
  }, { timeout: 20_000 }).toBe(true);
  return msg;
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c11-"));
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Hash story", parent_id: EPIC() }, { "X-Participant": "arch" })).id;
  repo = path.join(tmp, "fixture-repo");
  const put = (rel: string, text = `${rel}\n`) => { fs.mkdirSync(path.dirname(path.join(repo, rel)), { recursive: true }); fs.writeFileSync(path.join(repo, rel), text); };
  put("src/sample.py");
  put("src/util/helpers.ts", "export const helper = 1;\n");
  put("docs/guide.md");
  put(".gitignore", "build/\n");
  put("build/out.js");                          // gitignored: never in the picker
  put("secret-excluded/hidden.txt");             // files.exclude: never in the picker
  for (let i = 0; i < 80; i++) put(`gen/f${String(i).padStart(2, "0")}.txt`); // more than the cap
  put("untracked-note.md");                      // untracked but not ignored: listed
  const g = (a: string[]) => execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", ...a], { cwd: repo, encoding: "utf8" });
  g(["init", "-q", "-b", "main"]); g(["add", "src", "docs", ".gitignore", "gen"]); g(["commit", "-q", "-m", "fixture"]);
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  await call("GET", "/v1/participants/owner", undefined, asOwner); // token mode is live
  // C13: the last test opens a subfolder of the repo, as the live Code tab opens v8 inside eda-base3
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE(), "edp.sharedTreePaths": [repo], "files.exclude": { "**/secret-excluded": true },
    "git.openRepositoryInParentFolders": "always" });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first()).toBeVisible({ timeout: 60_000 });
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Open chat");
  await expect(chat().locator("#pick")).toBeVisible({ timeout: 20_000 });
  await chat().locator("#pick").click();
  await expect(quickRow(page, "Hash story")).toBeVisible({ timeout: 15_000 });
  await quickRow(page, "Hash story").click();
  await expect(chat().locator("#crumb-current")).toHaveText("Hash story", { timeout: 20_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  // the killed code-server can hold files for a few seconds (measured: EPERM right after stop); a leftover
  // temp dir is harmless, a failed teardown would mark the last test failed
  if (tmp && !process.env.C11_KEEP_TMP) {
    try { fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 }); }
    catch (e) { console.warn(`left ${tmp}: ${(e as Error).message}`); }
  }
});

test("# opens a picker over files AND folders; gitignored and files.exclude'd paths are left out; capped at 50", async () => {
  const c = chat();
  await expect(c.locator("#composer-tools #tag-path")).toBeVisible();
  await composer().click();
  await composer().pressSequentially("#");
  await expect(c.locator("#paths")).toBeVisible({ timeout: 10_000 });
  await expect(composer()).toHaveAttribute("aria-controls", "paths");
  // an empty query lists the top level: folders first
  await expect(options().first()).toHaveAttribute("data-kind", "folder");
  const top = await options().evaluateAll(els => els.map(e => (e as HTMLElement).dataset.path));
  expect(top).toEqual(expect.arrayContaining(["src", "docs", "gen", "untracked-note.md", ".gitignore"]));
  expect(top).not.toContain("build");
  expect(top).not.toContain("secret-excluded");
  await page.screenshot({ path: shot("picker-top-level.png") });
  await composer().pressSequentially("helpers");
  await expect(options().first()).toHaveAttribute("data-path", "src/util/helpers.ts");
  await composer().fill("");
  await composer().pressSequentially("#out.js");
  await page.waitForTimeout(800);
  await expect(c.locator("#paths")).toBeHidden();               // gitignored: no row
  await composer().fill("");
  await composer().pressSequentially("#hidden");
  await page.waitForTimeout(800);
  await expect(c.locator("#paths")).toBeHidden();               // files.exclude: no row
  await composer().fill("");
  await composer().pressSequentially("#gen/f");
  await expect(options()).toHaveCount(50, { timeout: 10_000 });  // 80 matches, capped
  await composer().press("Escape");
  await expect(c.locator("#paths")).toBeHidden();
  await composer().fill("");
});

test("no picker after a word character or inside a code span", async () => {
  const c = chat();
  await composer().click();
  await composer().pressSequentially("C#");
  await page.waitForTimeout(600);
  await expect(c.locator("#paths")).toBeHidden();
  await composer().fill("");
  await composer().pressSequentially("run `x #");
  await page.waitForTimeout(600);
  await expect(c.locator("#paths")).toBeHidden();
  await composer().fill("");
});

test("keyboard picks: a file tag and a folder tag in one message; Enter picks, never sends, while the list is open", async () => {
  await composer().click();
  await composer().pressSequentially("compare #helpers");
  await expect(options().first()).toHaveAttribute("data-path", "src/util/helpers.ts", { timeout: 10_000 });
  await composer().press("Enter");
  await expect(composer()).toHaveValue("compare `src/util/helpers.ts` ");
  await composer().pressSequentially("with #util");
  await expect(options().first()).toHaveAttribute("data-path", "src/util", { timeout: 10_000 });
  await expect(options().first()).toHaveAttribute("data-kind", "folder");
  // ArrowDown then ArrowUp returns to the folder row (the @ popup's keys)
  await composer().press("ArrowDown");
  await composer().press("ArrowUp");
  await expect(composer()).toHaveAttribute("aria-activedescendant", "path-0");
  await composer().press("Enter"); // C13: Enter inserts a folder; Tab/→ open it (shell completion)
  await expect(composer()).toHaveValue("compare `src/util/helpers.ts` with `src/util/` ");
  await composer().pressSequentially("and `src/missing.ts` too");
  await page.screenshot({ path: shot("two-tags-in-composer.png") });
  expect((await call("GET", `/v1/messages?ticket_id=${story}`, undefined, asOwner)).length).toBe(0); // nothing sent yet
  await composer().press("Control+Enter");
  await expect(composer()).toHaveValue("", { timeout: 10_000 });
  const m = await sentMessage("compare ");
  expect(m.text).toBe("compare `src/util/helpers.ts` with `src/util/` and `src/missing.ts` too");
  expect(m.code_context ?? null).toBeNull();
  fs.writeFileSync(shot("sent-message.json"), JSON.stringify({ id: m.id, text: m.text, code_context: m.code_context ?? null }, null, 1));
});

test("in the panel: the file tag opens in the editor, the folder tag reveals in the Explorer, a missing path is plain text", async () => {
  const c = chat();
  const msg = c.locator(".msg", { hasText: "compare" }).last();
  const file = msg.locator("button.path-link.file", { hasText: "src/util/helpers.ts" });
  const folder = msg.locator("button.path-link.folder", { hasText: "src/util/" });
  await expect(file).toBeVisible({ timeout: 10_000 });
  await expect(folder).toBeVisible();
  await expect(msg.locator("code", { hasText: "src/missing.ts" })).toBeVisible();
  await expect(msg.locator("button.path-link", { hasText: "src/missing.ts" })).toHaveCount(0);
  await page.screenshot({ path: shot("path-links-in-thread.png") });
  await file.click();
  await expect(page.locator(".tabs-container .tab.active", { hasText: "helpers.ts" })).toBeVisible({ timeout: 10_000 });
  await folder.click();
  const row = page.locator(".explorer-folders-view .monaco-list-row.selected, .explorer-folders-view .monaco-list-row.focused", { hasText: "util" });
  await expect(row.first()).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: shot("folder-revealed-in-explorer.png") });
  // a message from the board (not typed here) links the same way
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "see `docs/guide.md` and `docs/` and `nope/x.md`" }, asOwner);
  const board = c.locator(".msg", { hasText: "see docs/guide.md" }).last();
  await expect(board.locator("button.path-link.file", { hasText: "docs/guide.md" })).toBeVisible({ timeout: 10_000 });
  await expect(board.locator("button.path-link.folder", { hasText: "docs/" })).toBeVisible();
  await expect(board.locator("button.path-link", { hasText: "nope/x.md" })).toHaveCount(0);
});

test("C13 shell completion: Tab/→ open a folder, Backspace at / and ← go up, Enter inserts (owner m-28122bc446)", async () => {
  const c = chat();
  await composer().fill("");
  await composer().click();
  await composer().pressSequentially("#");
  await expect(options().first()).toHaveAttribute("data-path", "docs", { timeout: 10_000 });
  await composer().press("Tab");
  await expect(composer()).toHaveValue("#docs/");
  await expect(options().first()).toHaveAttribute("data-path", "docs/guide.md", { timeout: 10_000 });
  await page.screenshot({ path: shot("shell-tab-into-docs.png") });
  await composer().press("Backspace");
  await expect(composer()).toHaveValue("#");
  await expect(options().first()).toHaveAttribute("data-path", "docs", { timeout: 10_000 });
  // typing filters the level; → opens the highlighted folder
  await composer().pressSequentially("sr");
  await expect(options().first()).toHaveAttribute("data-path", "src", { timeout: 10_000 });
  await composer().press("ArrowRight");
  await expect(composer()).toHaveValue("#src/");
  await expect(options().first()).toHaveAttribute("data-path", "src/util", { timeout: 10_000 });
  await composer().press("ArrowRight");
  await expect(composer()).toHaveValue("#src/util/");
  await expect(options().first()).toHaveAttribute("data-path", "src/util/helpers.ts", { timeout: 10_000 });
  await page.screenshot({ path: shot("shell-arrow-into-src-util.png") });
  await composer().press("ArrowLeft");
  await expect(composer()).toHaveValue("#src/");
  await expect(options().first()).toHaveAttribute("data-path", "src/util", { timeout: 10_000 });
  await composer().press("Enter");
  await expect(composer()).toHaveValue("`src/util/` ");
  await expect(c.locator("#paths")).toBeHidden();
  await composer().fill("");
});

test("the # button in the tool slot opens the picker at the caret", async () => {
  const c = chat();
  await composer().fill("");
  await composer().click();
  await composer().pressSequentially("look at");
  await c.locator("#tag-path").click();
  await expect(composer()).toHaveValue("look at #");
  await expect(c.locator("#paths")).toBeVisible({ timeout: 10_000 });
  await composer().pressSequentially("guide");
  await expect(options().first()).toHaveAttribute("data-path", "docs/guide.md", { timeout: 10_000 });
  await composer().press("Enter");
  await expect(composer()).toHaveValue("look at `docs/guide.md` ");
  await page.screenshot({ path: shot("hash-button.png") });
  await composer().fill("");
});

test("C13 #../ from a workspace folder inside the repo: # opens at the folder, ../ lists the git root, a sibling is picked root-relative", async () => {
  // the live Code tab opens v8 inside the eda-base3 repo; here the workspace is the fixture repo's src/
  await page.goto(`http://127.0.0.1:${cs!.port}/?folder=${folderParam(path.join(repo, "src"))}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await runCommand("EDP: Open chat");
  await expect(chat().locator("#pick")).toBeVisible({ timeout: 20_000 });
  await chat().locator("#pick").click();
  await expect(quickRow(page, "Hash story")).toBeVisible({ timeout: 15_000 });
  await quickRow(page, "Hash story").click();
  await expect(chat().locator("#crumb-current")).toHaveText("Hash story", { timeout: 20_000 });
  await composer().click();
  await composer().pressSequentially("#");
  // home: the open folder's children, their paths still repo-relative
  await expect(options().first()).toHaveAttribute("data-path", "src/util", { timeout: 15_000 });
  await expect(options()).toHaveCount(2);
  await page.screenshot({ path: shot("home-level-src.png") });
  await composer().pressSequentially("../");
  await expect(options().first()).toHaveAttribute("data-path", "docs", { timeout: 10_000 });
  const root = await options().evaluateAll(els => els.map(e => (e as HTMLElement).dataset.path));
  expect(root).toEqual(expect.arrayContaining(["docs", "gen", "src", "untracked-note.md"]));
  await page.screenshot({ path: shot("dotdot-git-root.png") });
  // ../../ stops at the git root
  await composer().pressSequentially("../");
  await expect(composer()).toHaveValue("#../../");
  await expect(options().first()).toHaveAttribute("data-path", "docs", { timeout: 10_000 });
  // typing after ../ filters the root; Enter picks a root-relative token (never ..)
  await composer().fill("");
  await composer().pressSequentially("#../do");
  await expect(options().first()).toHaveAttribute("data-path", "docs", { timeout: 10_000 });
  await composer().press("Enter");
  await expect(composer()).toHaveValue("`docs/` ");
  await composer().fill("");
});
