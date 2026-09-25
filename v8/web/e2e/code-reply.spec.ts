// C22 smoke (s-3b86872bf0; owner m-eb27c76d48): Reply in the VS Code chat, as the board UI does it, and the reader's
// one-line reason when a design shows no Approve. From the keyboard: Reply on a message shows the "Replying to" bar,
// Escape cancels it; Reply again and Ctrl+Enter sends reply_to=<parent> and to=<parent author> (asserted on the
// board); the reply renders its parent's excerpt, and clicking it scrolls to the parent, loading older pages when
// the parent is more than a page back; a reply with a code chip sends both. The reader on the epic's design in three
// states: no sign-off open (the reason, no Approve), sign-off open on a newer version (the reason and "open it"), and
// open on this version for the owner (Approve / Request changes in the title bar, no reason). REAL code-server
// against this file's own e2e board (never :9400/:9410). Browser: Chromium by default; CHAT_BROWSER=stockff runs the
// installed Firefox. One browser at a time.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Frame, FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c22-owner-tok-5d0e2a8b41";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-reply", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-reply", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "", repo = "", head = "";
let cs: CodeServer | null = null;
let page: Page;
let story = "", design = "", oldParent = "", oldReply = "", ask = "";
const FILLER = 105; // more than one thread page (100): the old parent is not loaded at first

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const arch = { "X-Participant": "arch" };

// -- workbench ------------------------------------------------------------------------------------
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
async function openFile(name: string): Promise<void> {
  await runCommand("Go to File...");
  await quick(page).locator("input").fill(name);
  await expect(quickRow(page, name)).toBeVisible({ timeout: 15_000 });
  await quickRow(page, name).click();
  await expect(page.locator(".monaco-editor .view-lines").first()).toBeVisible();
}
/** Whole lines from..to by dragging the line-number gutter (the selection ends at column 0 of the next line, which
 *  the anchor excludes). Not the keyboard: once the chat webview had been clicked, Playwright's Firefox kept sending
 *  page.keyboard to the webview frame although the editor held the caret (Go to Line moved it only by its preview). */
async function selectLines(from: number, to: number): Promise<void> {
  const num = (n: number) => page.locator(".monaco-editor .margin-view-overlays .line-numbers", { hasText: new RegExp(`^${n}$`) }).first();
  const a = (await num(from).boundingBox())!, b = (await num(to).boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 5 });
  await page.mouse.up();
  await expect(page.locator(".statusbar-item", { hasText: `(${to - from + 1} lines selected)` }).first()).toBeVisible({ timeout: 5_000 }).catch(() => {});
}
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
async function reader(docId: string, version: number): Promise<Frame> {
  let found: Frame | undefined;
  await expect.poll(async () => {
    for (const f of page.frames()) {
      if (!(await f.locator("#rd-title").count().catch(() => 0))) continue;
      if ((await f.title().catch(() => "")) === `EDP ${docId} v${version}`) { found = f; return true; }
    }
    return false;
  }, { timeout: 30_000, intervals: [500] }).toBe(true);
  return found!;
}
const titleAction = (label: RegExp) => page.locator(".editor-group-container.active .editor-actions").getByRole("button", { name: label });
const activeTab = () => page.locator(".tabs-container .tab.active");
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
const msgEl = (id: string) => chat().locator(`.msg[data-id="${id}"]`);
const lineText = (n: number) => `value_${n} = ${n}  # line ${n}`;

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
/** The element is inside the chat timeline's visible box. */
const inView = (id: string) => msgEl(id).evaluate(e => {
  const t = e.closest(".timeline")!.getBoundingClientRect(), r = e.getBoundingClientRect();
  return r.bottom > t.top && r.top < t.bottom;
});

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c22-"));
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Reply story", parent_id: EPIC() }, arch)).id;
  // an old parent more than a page back, a reply to it (seeded), filler, then a recent question to reply to from the panel
  oldParent = (await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "The old parent: pick the cache policy before C23." }, arch)).id;
  for (let i = 1; i <= FILLER; i++) await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: `filler ${i}` }, arch);
  oldReply = (await call("POST", "/v1/messages", { ticket_id: story, kind: "answer", text: "LRU, as the old parent asked.", reply_to: oldParent, to: "arch" }, arch)).id;
  ask = (await call("POST", "/v1/messages", { ticket_id: story, kind: "question", to: "owner",
    text: "Which way for the reply bar:\nabove the composer or below it? It carries the parent's excerpt." }, arch)).id;
  // the epic's design at v1 and v2, NO sign-off open yet (state a)
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "Reply design", body_md: "# Reply design\n\n## 1. Words\n\n> reply like the web\n", scope: EPIC() }, arch)).id;
  await call("PATCH", `/v1/docs/${design}`, { body_md: "# Reply design\n\n## 1. Words\n\n> reply like the web\n\n## 2. Plan\n\n- a Reply on every message\n" }, arch);
  await call("PATCH", `/v1/tickets/${EPIC()}`, { design_ref: design }, arch);
  // a git repo for the code chip
  repo = path.join(tmp, "fixture-repo");
  fs.mkdirSync(path.join(repo, "src"), { recursive: true });
  fs.writeFileSync(path.join(repo, "src", "sample.py"), Array.from({ length: 25 }, (_, i) => lineText(i + 1)).join("\n") + "\n");
  const g = (a: string[]) => execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", ...a], { cwd: repo, encoding: "utf8" });
  g(["init", "-q", "-b", "main"]); g(["add", "src/sample.py"]); g(["commit", "-q", "-m", "fixture"]);
  head = g(["rev-parse", "HEAD"]).trim();
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  await call("GET", "/v1/participants/owner", undefined, asOwner); // token mode is live
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE() });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C22_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("sign in and open the story thread", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Open chat");
  const c = chat();
  await c.locator("#pick").click({ timeout: 20_000 });
  await expect(quickRow(page, "Reply story")).toBeVisible({ timeout: 15_000 });
  await quickRow(page, "Reply story").click();
  await expect(c.locator("#crumb-current")).toHaveText("Reply story", { timeout: 20_000 });
  await expect(msgEl(ask)).toBeVisible({ timeout: 20_000 });
});

test("a reply with a code chip sends both", async () => {
  const c = chat();
  await openFile("sample.py");
  await selectLines(4, 6);
  await page.keyboard.press("Control+Alt+M");
  await expect(c.locator("#code-chip-label")).toHaveText(`src/sample.py:L4-6 @${head.slice(0, 7)}`, { timeout: 15_000 });
  const reply = msgEl(ask).locator(".reply");
  await reply.focus();
  await page.keyboard.press("Enter");
  await expect(c.locator("#reply-bar")).toBeVisible();
  await expect(c.locator("#code-chip")).toBeVisible();
  await page.keyboard.type("These lines hold the bar.");
  await page.screenshot({ path: shot("5-reply-with-chip.png") });
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#reply-bar")).toBeHidden({ timeout: 10_000 });
  await expect(c.locator("#code-chip")).toBeHidden();
  const m = await sentMessage("These lines hold the bar.");
  expect(m.reply_to).toBe(ask);
  expect(m.to).toBe("arch");
  expect(m.code_context).toMatchObject({ path: "src/sample.py", line_start: 4, line_end: 6, commit: head });
  await expect(msgEl(m.id).locator(".reply-quote")).toBeVisible({ timeout: 10_000 });
  await expect(msgEl(m.id).locator(".code-card")).toBeVisible();
  await page.screenshot({ path: shot("6-reply-with-chip-sent.png") });
  fs.writeFileSync(shot("reply-chip-message.json"), JSON.stringify({ id: m.id, reply_to: m.reply_to, to: m.to, code_context: m.code_context }, null, 1));
});

test("keyboard: Reply shows the bar, Escape cancels; Reply again + Ctrl+Enter sends reply_to and to=<author>", async () => {
  const c = chat();
  const reply = msgEl(ask).locator(".reply");
  await expect(reply).toHaveCSS("opacity", "0"); // hidden until hover or focus, but in the tab order
  await reply.focus();
  await expect(reply).toHaveCSS("opacity", "1");
  await page.keyboard.press("Enter");
  await expect(c.locator("#reply-bar")).toBeVisible();
  await expect(c.locator("#reply-bar .rb-who")).toHaveText("Replying to @arch:");
  await expect(c.locator("#reply-bar .rb-text")).toHaveText("Which way for the reply bar: above the composer or below it? It carries the parent's excerpt.");
  await expect(c.locator("#composer")).toBeFocused();
  await expect(c.locator("#to")).toHaveValue("arch");
  await page.screenshot({ path: shot("1-reply-bar.png") });
  await page.keyboard.press("Escape");
  await expect(c.locator("#reply-bar")).toBeHidden();
  await expect(c.locator("#to")).toHaveValue("");
  await expect(c.locator("#composer")).toBeFocused();
  await page.screenshot({ path: shot("2-reply-cancelled.png") });
  // Reply again from the keyboard (Space on the focused button), type, Enter is a newline, Ctrl+Enter sends
  await reply.focus();
  await page.keyboard.press("Space");
  await expect(c.locator("#reply-bar")).toBeVisible();
  await expect(c.locator("#composer")).toBeFocused();
  await page.keyboard.type("Above the composer.");
  await page.keyboard.press("Enter");
  await page.keyboard.type("Like the web.");
  await expect(c.locator("#composer")).toHaveValue("Above the composer.\nLike the web.");
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#reply-bar")).toBeHidden({ timeout: 10_000 });
  await expect(c.locator("#composer")).toHaveValue("");
  const m = await sentMessage("Above the composer.");
  expect(m.reply_to).toBe(ask);
  expect(m.to).toBe("arch");
  expect(m.created_by).toBe("owner");
  fs.writeFileSync(shot("reply-message.json"), JSON.stringify({ id: m.id, reply_to: m.reply_to, to: m.to, kind: m.kind, text: m.text }, null, 1));
  // the reply renders with its parent's excerpt; clicking it scrolls to the parent and marks it
  const line = msgEl(m.id).locator(".reply-quote");
  await expect(line).toBeVisible({ timeout: 10_000 });
  await expect(line.locator(".rq-who")).toHaveText("↳ replying to @arch:");
  await expect(line.locator(".rq-text")).toContainText("Which way for the reply bar");
  await chat().locator(".timeline").evaluate(t => { t.scrollTop = 0; }); // the parent out of view
  await line.scrollIntoViewIfNeeded();
  await line.click();
  await expect(msgEl(ask)).toHaveClass(/focus-source/);
  expect(await inView(ask)).toBe(true);
  await page.screenshot({ path: shot("3-reply-sent-parent-focused.png") });
});

test("a reply whose parent is more than a page back: the excerpt loads older messages and scrolls to it", async () => {
  const line = msgEl(oldReply).locator(".reply-quote");
  await expect(line).toBeVisible();
  await expect(msgEl(oldParent)).toHaveCount(0);
  await expect(line.locator(".rq-who")).toHaveText("↳ replying to an earlier message");
  await line.scrollIntoViewIfNeeded();
  await line.click();
  await expect(msgEl(oldParent)).toHaveClass(/focus-source/, { timeout: 20_000 });
  expect(await inView(oldParent)).toBe(true);
  // the reply's own line now shows the parent's excerpt
  await expect(line.locator(".rq-who")).toHaveText("↳ replying to @arch:");
  await expect(line.locator(".rq-text")).toHaveText("The old parent: pick the cache policy before C23.");
  await page.screenshot({ path: shot("4-older-parent-loaded.png") });
});

test("reader (a): no sign-off open: the header says why, no Approve", async () => {
  const c = chat();
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  await c.locator("#tab-docs").click();
  await c.locator(`#panel-docs .dc-row[data-id="${design}"] .dc-open`).click({ timeout: 30_000 });
  await expect(activeTab()).toContainText("Reply design · v2", { timeout: 20_000 });
  const r = await reader(design, 2);
  await expect(r.locator("#rd-signoff .rd-signoff-text")).toHaveText(`No sign-off open on v2 (${EPIC()})`, { timeout: 15_000 });
  await expect(r.locator("#rd-signoff")).toHaveAttribute("title", /no Reject: Request changes/);
  await expect(r.locator("#rd-signoff-open")).toHaveCount(0);
  await expect(titleAction(/^Approve design/)).toHaveCount(0);
  await page.screenshot({ path: shot("7-reader-a-no-signoff.png") });
});

test("reader (b): sign-off open on a newer version: the header names it and opens it", async () => {
  await call("POST", `/v1/gates/${EPIC()}/design_signoff/open`, { note: "design v2 is ready" }, arch);
  // read v1 (the version picker opens it in its own tab, read fresh)
  const r2 = await reader(design, 2);
  await r2.locator("#rd-version").selectOption("1");
  await expect(activeTab()).toContainText("Reply design · v1", { timeout: 20_000 });
  const r1 = await reader(design, 1);
  await expect(r1.locator("#rd-signoff .rd-signoff-text")).toHaveText(`Sign-off is open on v2 (${EPIC()})`, { timeout: 15_000 });
  await expect(r1.locator("#rd-signoff-open")).toHaveText("open it");
  await expect(titleAction(/^Approve design/)).toHaveCount(0);
  await page.screenshot({ path: shot("8-reader-b-open-on-newer.png") });
  await r1.locator("#rd-signoff-open").click();
  await expect(activeTab()).toContainText("Reply design · v2", { timeout: 20_000 });
});

test("reader (c): sign-off open on this version for the owner: Approve and Request changes as before, no reason", async () => {
  const r = await reader(design, 2);
  // the v2 tab was read before the gate opened: refresh it
  await runCommand("EDP: Refresh doc");
  await expect(titleAction(/^Approve design/)).toBeVisible({ timeout: 15_000 });
  await expect(titleAction(/^Request changes on the design/)).toBeVisible();
  await expect(r.locator("#rd-signoff")).toHaveCount(0);
  await expect(r.locator("#rd-approve")).toBeVisible();
  await page.screenshot({ path: shot("9-reader-c-approve.png") });
});
