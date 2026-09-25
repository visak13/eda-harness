// C20 smoke (s-29f052c40e; design-10b21760d9 v12 §14.5/§14.7): quote + note in the VS Code extension, sent as ONE
// message with quotes[] (C18). With the story thread open: a chat message passage is quoted from the message's own
// popover; then, with the chat side bar HIDDEN, a design passage from the EDP reader (its popover) and a code range
// from the editor (Ctrl+Alt+Q opens the inline comment box, Add to chat) join the draft while the status bar says
// "EDP draft: N → <thread>" and the chat stays hidden; the reader marks its drafted block. The status bar item
// reveals the chat: the chips are in order, one is moved, an extra one removed, a Reply is picked, and Ctrl+Enter
// sends one message carrying reply_to and three quotes (asserted on the board), which renders as three quote cards.
// REAL code-server against this file's own e2e board (never :9400/:9410). Browser: Chromium by default;
// CHAT_BROWSER=stockff runs the installed Firefox. One browser at a time.
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
const OWNER_TOKEN = "c20-owner-tok-7b1e4c9d25";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-quotes", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-quotes", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "", repo = "", head = "";
let cs: CodeServer | null = null;
let page: Page;
let story = "", design = "", ask = "", who = ""; // who: the handle picked from the @ list
const typedLost: string[] = []; // Firefox: comment-box notes the harness could not type (entered on the chip)
const DESIGN_MD = "# Quote design\n\n## 14.5 Quote + note\n\nEvery quote carries **its note** and a locator the board verifies.\n\n## 14.7 Tray\n\nThe tray keeps its order until the send.\n";

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
/** Whole lines from..to by dragging the line-number gutter (see code-reply.spec.ts: the keyboard is unreliable
 *  in Firefox once a webview had focus). */
async function selectLines(from: number, to: number): Promise<void> {
  const num = (n: number) => page.locator(".monaco-editor .margin-view-overlays .line-numbers", { hasText: new RegExp(`^${n}$`) }).first();
  const a = (await num(from).boundingBox())!, b = (await num(to).boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 5 });
  await page.mouse.up();
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
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
const msgEl = (id: string) => chat().locator(`.msg[data-id="${id}"]`);
const lineText = (n: number) => `value_${n} = ${n}  # line ${n}`;
const aux = () => page.locator(".part.auxiliarybar");
const draftItem = () => page.locator(".statusbar-item", { hasText: "EDP draft:" });
const chips = () => chat().locator("#quote-chips > li.qchip");

/** Select `phrase` inside the first element matching `sel` of a document (the chat or the reader frame); the
 *  phrase may span inline markup (several text nodes). */
async function selectIn(root: { locator: (s: string) => ReturnType<Page["locator"]> }, sel: string, phrase: string): Promise<void> {
  await root.locator(sel).first().evaluate((el, ph) => {
    const d = el.ownerDocument, walk = d.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes: { n: Node; at: number }[] = [];
    let all = "";
    for (let n = walk.nextNode(); n; n = walk.nextNode()) { nodes.push({ n, at: all.length }); all += n.textContent ?? ""; }
    const i = all.indexOf(ph);
    if (i < 0) throw new Error(`not found: ${ph}`);
    const pos = (k: number, end: boolean) => { const x = [...nodes].reverse().find(t => (end ? t.at < k : t.at <= k))!; return [x.n, k - x.at] as const; };
    const r = d.createRange();
    r.setStart(...pos(i, false)); r.setEnd(...pos(i + ph.length, true));
    const s = d.getSelection()!;
    s.removeAllRanges(); s.addRange(r);
  }, phrase);
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c20-"));
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Quote story", parent_id: EPIC() }, arch)).id;
  ask = (await call("POST", "/v1/messages", { ticket_id: story, kind: "question", to: "owner",
    text: "Before C21: should the tray keep **its order** across a reload, or sort by source?" }, arch)).id;
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "Quote design", body_md: DESIGN_MD, scope: EPIC() }, arch)).id;
  await call("PATCH", `/v1/tickets/${story}`, { design_ref: design }, arch); // the story's Docs tab lists it
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
  if (tmp && !process.env.C20_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("sign in and open the story thread", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Open chat");
  const c = chat();
  await c.locator("#pick").click({ timeout: 20_000 });
  await expect(quickRow(page, "Quote story")).toBeVisible({ timeout: 15_000 });
  await quickRow(page, "Quote story").click();
  await expect(c.locator("#crumb-current")).toHaveText("Quote story", { timeout: 20_000 });
  await expect(msgEl(ask)).toBeVisible({ timeout: 20_000 });
});

test("a chat message passage: select it, Quote, a note, Add to chat -> a chip", async () => {
  const c = chat();
  await selectIn(c, `.msg[data-id="${ask}"] > .body`, "keep its order across a reload");
  await expect(c.locator("#quote-selection")).toBeVisible({ timeout: 5_000 });
  await c.locator("#quote-selection").click();
  await expect(c.locator("#quote-pop")).toBeVisible();
  await expect(c.locator("#quote-pop-note")).toBeFocused();
  // the note box has the composer's @ list (owner m-5a9111ce12)
  await page.keyboard.type("Yes, keep it. @");
  await expect(c.locator("#qn-people")).toBeVisible({ timeout: 5_000 });
  who = (await c.locator("#qn-people li").first().getAttribute("data-handle"))!;
  await page.screenshot({ path: shot("1a-message-note-at-list.png") });
  await page.keyboard.press("Enter");
  await expect(c.locator("#quote-pop-note")).toHaveValue(`Yes, keep it. @${who} `);
  await page.screenshot({ path: shot("1-message-popover.png") });
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#quote-pop")).toBeHidden();
  await expect(chips()).toHaveCount(1, { timeout: 10_000 });
  await expect(chips().nth(0)).toHaveAttribute("data-source", "message");
  await expect(chips().nth(0).locator(".qchip-note")).toHaveValue(`Yes, keep it. @${who} `);
  // open the design from the Docs tab while the chat is still shown
  await c.locator("#tab-docs").click();
  await c.locator(`#panel-docs .dc-row[data-id="${design}"] .dc-open`).click({ timeout: 30_000 });
  await reader(design, 1);
});

test("chat hidden: a reader passage joins the draft, the status bar counts it, the block is marked", async () => {
  await runCommand("View: Toggle Secondary Side Bar Visibility");
  await expect(aux()).toBeHidden({ timeout: 10_000 });
  await expect(draftItem()).toContainText("EDP draft: 1 → Quote story", { timeout: 10_000 });
  const r = await reader(design, 1);
  await selectIn(r, "#doc", "carries its note");
  await expect(r.locator("#rd-quote-sel")).toBeVisible({ timeout: 5_000 });
  await r.locator("#rd-quote-sel").click();
  await expect(r.locator("#rd-quote-pop")).toBeVisible();
  // and the composer's # path list: the host answers from the workspace
  await r.locator("#rd-quote-note").pressSequentially("Is the locator per line? #sample");
  await expect(r.locator("#rdn-paths")).toBeVisible({ timeout: 10_000 });
  await expect(r.locator("#rdn-paths li").first()).toContainText("sample.py");
  await page.screenshot({ path: shot("2a-reader-note-hash-list.png") });
  await r.locator("#rd-quote-note").press("Enter");
  await expect(r.locator("#rd-quote-note")).toHaveValue("Is the locator per line? `src/sample.py` ");
  await page.screenshot({ path: shot("2-reader-popover-chat-hidden.png") });
  await r.locator("#rd-quote-add").click();
  await expect(r.locator("#rd-status")).toContainText("Added", { timeout: 10_000 });
  await expect(r.locator("#doc")).toHaveAttribute("data-marks", "1", { timeout: 10_000 });
  await expect(r.locator("#doc .rd-drafted")).toHaveCount(1);
  await expect(draftItem()).toContainText("EDP draft: 2 → Quote story", { timeout: 10_000 });
  await expect(aux()).toBeHidden();
});

test("chat hidden: Ctrl+Alt+Q on a code range opens the inline comment box; Add to chat drafts it", async () => {
  await openFile("sample.py");
  for (const [a, b, note] of [[4, 6, "These lines pick the order."], [10, 11, "extra, removed before sending"]] as const) {
    // Firefox keeps key focus in the reader's webview frame (code-changes.spec.ts): a workbench click takes it back
    await page.locator(".tabs-container .tab.active").click();
    await selectLines(a, b);
    await page.keyboard.press("Control+Alt+Q");
    const box = page.locator(".review-widget").last();
    await expect(box).toBeVisible({ timeout: 10_000 });
    await page.keyboard.type(note);
    if (a === 4 && !STOCK_FF) { // the comment box's @ completion (the `comment`-scheme provider)
      await page.keyboard.type(` @${who.slice(0, 3)}`);
      await expect(page.locator(".suggest-widget .monaco-list-row", { hasText: `@${who}` }).first()).toBeVisible({ timeout: 10_000 });
      await page.screenshot({ path: shot("3a-comment-box-at-completion.png") });
      await page.keyboard.press("Enter");
      await expect(box.locator(".comment-form .monaco-editor .view-lines").first()).toContainText(`@${who}`);
    }
    // Playwright's Firefox routes typed text to the webview frame that last had focus: measured here, text typed
    // into the main editor was dropped too, while chords (Ctrl+Alt+Q) still reach the workbench. There the note is
    // entered on the draft's chip in the chat instead (the tray's note field), below.
    if (!(await box.locator(".comment-form .monaco-editor .view-lines").first().innerText()).replace(/\s+/g, " ").includes(note.slice(0, 8))) typedLost.push(note);
    if (a === 4) await page.screenshot({ path: shot("3-code-comment-box.png") });
    await box.getByRole("button", { name: "Add to chat" }).click();
    await expect(page.locator(".review-widget .comment-form")).toHaveCount(0, { timeout: 10_000 });
  }
  await expect(draftItem()).toContainText("EDP draft: 4 → Quote story", { timeout: 10_000 });
  await expect(aux()).toBeHidden();
  await page.screenshot({ path: shot("4-status-bar-draft.png") });
});

test("the status bar reveals the chat; reorder, remove, Reply, Ctrl+Enter sends one message with three quotes", async () => {
  const c = chat();
  await draftItem().click();
  await expect(aux()).toBeVisible({ timeout: 10_000 });
  await c.locator("#tab-chat").click().catch(() => {});
  await expect(chips()).toHaveCount(4, { timeout: 10_000 });
  await expect(chips().locator(".qchip-src")).toHaveText(["message", "doc", "code", "code"]);
  await chips().nth(3).locator(".qchip-remove").click();
  await expect(chips()).toHaveCount(3);
  await chips().nth(2).locator(".qchip-up").click(); // code before doc
  await expect(chips().locator(".qchip-src")).toHaveText(["message", "code", "doc"]);
  if (typedLost.includes("These lines pick the order.")) {
    await expect(chips().nth(1).locator(".qchip-note")).toHaveValue("");
    await chips().nth(1).locator(".qchip-note").pressSequentially("These lines pick the order.");
  } else await expect(chips().nth(1).locator(".qchip-note")).toHaveValue(new RegExp(`^These lines pick the order\. @${who}`));
  await msgEl(ask).locator(".reply").click();
  await expect(c.locator("#reply-bar")).toBeVisible();
  await c.locator("#composer").click();
  await page.keyboard.type("Three quotes, one message.");
  await page.screenshot({ path: shot("5-composer-chips-reply.png") });
  await page.keyboard.press("Control+Enter");
  await expect(chips()).toHaveCount(0, { timeout: 15_000 });
  await expect(c.locator("#reply-bar")).toBeHidden();
  await expect(draftItem()).toHaveCount(0);
  let m: any;
  await expect.poll(async () => {
    const rows = await call("GET", `/v1/messages?ticket_id=${story}`, undefined, asOwner);
    m = rows.find((x: any) => x.text === "Three quotes, one message.");
    return !!m;
  }, { timeout: 20_000 }).toBe(true);
  const full = await call("GET", `/v1/tickets/${story}/thread`, undefined, asOwner);
  const row = full.thread.find((x: any) => x.id === m.id);
  const q = row.quotes as any[];
  expect(m.reply_to).toBe(ask);
  expect(q.map(x => x.source)).toEqual(["message", "code", "doc"]);
  expect(q[0]).toMatchObject({ id: ask, text: expect.stringContaining("its order"), note: `Yes, keep it. @${who} ` });
  expect(q[1].code).toMatchObject({ path: "src/sample.py", line_start: 4, line_end: 6, commit: head });
  expect(q[1].note).toMatch(STOCK_FF ? /^These lines pick the order\.$/ : new RegExp(`^These lines pick the order\. @${who}`));
  expect(q[2]).toMatchObject({ id: design, version: 1, note: "Is the locator per line? `src/sample.py` ", text: expect.stringContaining("carries") });
  // C23 (s-93ddb7fd1a): the text names nobody; the @ picked in a NOTE wakes that person (event mentions)
  expect(m.text).not.toContain("@");
  const ev = (await call("GET", `/v1/events?subject_id=${story}`, undefined, asOwner))
    .find((e: any) => e.kind === "message_sent" && e.data.message === m.id);
  expect(ev.data.mentions).toContain(who);
  fs.writeFileSync(shot("quotes-message.json"), JSON.stringify({ id: m.id, reply_to: m.reply_to, quotes: q, mentions: ev.data.mentions }, null, 1));
  const cards = msgEl(m.id).locator(".quote-card");
  await expect(cards).toHaveCount(3, { timeout: 10_000 });
  await msgEl(m.id).scrollIntoViewIfNeeded();
  await page.screenshot({ path: shot("6-sent-three-cards.png") });
  // the doc card opens the reader on its lines
  await cards.nth(2).locator(".qc-source").click();
  const r = await reader(design, 1);
  await expect(r.locator("#doc")).toHaveAttribute("data-revealed", /\d+-\d+/, { timeout: 10_000 });
  await expect(r.locator("#doc")).toHaveAttribute("data-marks", "0");
});
