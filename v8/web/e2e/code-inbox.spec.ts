// C15 Inbox tab smoke (s-e14d316891; design-10b21760d9 §14.2/§14.4): the owner's questions, sign-offs and
// gates in the EDP chat's fourth tab, scoped to the picked epic/story, each answered in place with ONE real
// write per row type, asserted on the board: a question answer (to the asker, reply_to), a sign-off verdict
// with the evidence version shown (and the board's stale-version refusal shown verbatim), a scope-gate
// ruling. Runs in a REAL code-server against this file's own e2e board (never :9400/:9410).
// Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox. One browser at a time.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c15-owner-tok-7e2b91c4d0";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-inbox", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-inbox", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let cs: CodeServer | null = null;
let page: Page;
let storyA = "", storyB = "", taskA = "";
let qA = "", qB = "", qTask = "", critA = "", critStale = "", docA = "", docStale = "";
const ENG = () => `engineer.${storyA}`;
const ENG_B = () => `engineer.${storyB}`;

// -- board ----------------------------------------------------------------------------------------
async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const arch = { "X-Participant": "arch" };
const as = (id: string) => ({ "X-Participant": id });

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
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
async function openStory(id: string): Promise<void> {
  const c = chat();
  if ((await c.locator("#stories-toggle").getAttribute("aria-expanded")) !== "true") await c.locator("#stories-toggle").click();
  await c.locator(`.story[data-id="${id}"]`).click();
}
const tab = async (id: string) => { await chat().locator(`#tab-${id}`).click(); await expect(chat().locator(`#tab-${id}`)).toHaveAttribute("aria-selected", "true"); };
const row = (key: string) => chat().locator(`#panel-inbox .ib-row[data-key="${key}"]`);
const keys = () => chat().locator("#panel-inbox .ib-row").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.key));
const activeTab = () => page.locator(".tabs-container .tab.active");
/** The host's Inbox re-reads have stopped: the panel's read counter holds still for 2 s. */
async function settled(): Promise<void> {
  const reads = () => chat().locator("#panel-inbox").getAttribute("data-reads");
  let last = await reads(), since = Date.now();
  await expect.poll(async () => {
    const now = await reads();
    if (now !== last) { last = now; since = Date.now(); }
    return Date.now() - since >= 2_000;
  }, { timeout: 20_000, intervals: [250] }).toBe(true);
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c15-"));
  storyA = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Alpha", parent_id: EPIC() }, arch)).id;
  storyB = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Beta", parent_id: EPIC() }, arch)).id;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: ENG(), id: ENG() });
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: ENG_B(), id: ENG_B() });
  await call("PATCH", `/v1/tickets/${storyA}`, { assignee: ENG() }, arch).catch(() => undefined);
  taskA = (await call("POST", "/v1/tickets", { kind: "task", work_type: "feature", title: "Alpha task", parent_id: storyA, assignee: ENG() }, arch)).id;
  // questions to the owner: one per story, one on the story's task (a story scope includes its tasks)
  qA = (await call("POST", "/v1/messages", { ticket_id: storyA, kind: "question", to: "owner", text: "Alpha: **which** header layout do you want?" }, as(ENG()))).id;
  qTask = (await call("POST", "/v1/messages", { ticket_id: taskA, kind: "question", to: "owner", text: "Task: keep the old flag?" }, as(ENG()))).id;
  qB = (await call("POST", "/v1/messages", { ticket_id: storyB, kind: "question", to: "owner", text: "Beta: ship behind a flag?" }, as(ENG_B()))).id;
  // two owner sign-offs on Story Alpha, each with a report as evidence
  docA = (await call("POST", "/v1/docs", { doc_type: "report", title: "Alpha report", body_md: "# Alpha report\n\nThe header works in both browsers.\n", scope: storyA }, as(ENG()))).id;
  docStale = (await call("POST", "/v1/docs", { doc_type: "report", title: "Alpha perf report", body_md: "# Perf\n\nv1 numbers.\n", scope: storyA }, as(ENG()))).id;
  // tokens: the owner signs in with one; seeding the owner's own criteria needs it from here on
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  await call("GET", "/v1/participants/owner", undefined, asOwner);
  const crit = (text: string) => call("POST", "/v1/criteria", { ticket_id: storyA, text, check: "look", checked_by: "owner", override_reason: "C15 smoke: an owner sign-off row" }, asOwner);
  critA = (await crit("The Alpha report says the header works")).id;
  critStale = (await crit("The perf report has the numbers")).id;
  await call("PATCH", `/v1/criteria/${critA}`, { evidence_ref: docA }, as(ENG()));
  await call("PATCH", `/v1/criteria/${critStale}`, { evidence_ref: docStale }, as(ENG()));
  // gates on the epic: a scope gate (a ruling box) and the design review (a link to the board)
  await call("POST", `/v1/gates/${EPIC()}/scope/open`, { note: "raise the story cap to 9" }, arch);
  await call("POST", `/v1/gates/${EPIC()}/design_signoff/open`, { note: "design v3 is ready" }, arch);
  const home = await call("GET", "/v1/me/decisions", undefined, asOwner);
  expect(home.counts).toEqual({ signoffs: 2, questions: 3, gates: 2 });
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE() });
  page = await browser.newPage();
  fs.mkdirSync(path.join(tmp, "ws"), { recursive: true });
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(path.join(tmp, "ws"))}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first()).toBeVisible({ timeout: 60_000 }).catch(() => undefined);
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C15_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("the epic scope: Inbox is the fourth tab, badged; sign-offs, gates and questions of this epic only", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await quickRow(page, "Spike epic").click();
  const c = chat();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  await expect(c.locator("[role=tablist] [role=tab]")).toHaveText([/^Chat/, /^Changes/, /^Commits/, /^Inbox/]);
  await expect(c.locator("#tab-inbox .tab-badge")).toHaveText("7", { timeout: 15_000 });
  await expect(c.locator("#tab-inbox")).toHaveAttribute("aria-label", "Inbox, 7 items waiting on you");
  await tab("inbox");
  expect(await keys()).toEqual([`c:${critA}`, `c:${critStale}`, `g:${EPIC()}:scope`, `g:${EPIC()}:design_signoff`, `q:${qA}`, `q:${qTask}`, `q:${qB}`]);
  await expect(row(`c:${critA}`).locator(".ib-ev-what")).toHaveText("Alpha report · report v1");
  await expect(row(`c:${critA}`).locator(".ib-pass")).toHaveText("Pass v1");
  await expect(row(`g:${EPIC()}:design_signoff`).locator("textarea")).toHaveCount(0);
  await expect(row(`g:${EPIC()}:design_signoff`).locator("button")).toHaveText("Review design");
  await expect(row(`q:${qA}`).locator(".ib-body strong")).toHaveText("which");
  await expect(row(`q:${qA}`).locator(".ib-why")).toHaveText("Why you see it: addressed to you (@owner)");
  await page.screenshot({ path: shot("inbox-epic.png") });
});

test("the scope picker drives the list: a story shows its own rows and its tasks', nothing of the epic or the other story", async () => {
  const c = chat();
  await openStory(storyB);
  await expect(c.locator("#crumb-current")).toHaveText("Story Beta", { timeout: 15_000 });
  await expect(c.locator("#tab-inbox")).toHaveAttribute("aria-selected", "true");
  await expect.poll(keys, { timeout: 15_000 }).toEqual([`q:${qB}`]);
  await expect(c.locator("#tab-inbox .tab-badge")).toHaveText("1");
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
  await expect.poll(keys, { timeout: 15_000 }).toEqual([`c:${critA}`, `c:${critStale}`, `q:${qA}`, `q:${qTask}`]);
  await page.screenshot({ path: shot("inbox-story-alpha.png") });
});

test("a question: Enter is a newline, Ctrl+Enter answers the asker threaded under the question; the row leaves", async () => {
  const c = chat();
  const ta = row(`q:${qA}`).locator("textarea");
  await ta.click();
  await ta.pressSequentially("The compact one.");
  await page.keyboard.press("Enter");
  await ta.pressSequentially("One line, please.");
  await expect(ta).toHaveValue("The compact one.\nOne line, please.");
  await page.keyboard.press(process.platform === "darwin" ? "Meta+Enter" : "Control+Enter");
  await expect(row(`q:${qA}`)).toHaveCount(0, { timeout: 15_000 });
  const thread = await call("GET", `/v1/tickets/${storyA}/thread`, undefined, asOwner);
  const ans = thread.thread.find((m: any) => m.reply_to === qA);
  expect(ans).toBeTruthy();
  const full = await call("GET", `/v1/messages/${ans.id}`, undefined, asOwner);
  expect(full).toMatchObject({ kind: "answer", to: ENG(), reply_to: qA, text: "The compact one.\nOne line, please.", created_by: "owner" });
  const home = await call("GET", "/v1/me/decisions", undefined, asOwner);
  expect(home.questions.map((q: any) => q.id)).not.toContain(qA);
  await expect(c.locator("#tab-inbox .tab-badge")).toHaveText("3");
});

test("a sign-off: the evidence opens in an editor tab at the version shown; Fail needs a note; Pass records that version", async () => {
  const r = row(`c:${critA}`);
  await r.locator(".ib-evidence").click();
  await expect(activeTab()).toContainText("v1", { timeout: 15_000 });
  await page.screenshot({ path: shot("inbox-evidence-open.png") });
  await r.locator(".ib-fail").click();
  await expect(r.locator(".ib-error")).toHaveText("Say what needs work: a Fail needs a note.");
  await r.locator("textarea").fill("Header verified in both browsers.");
  await r.locator(".ib-pass").click();
  await expect(row(`c:${critA}`)).toHaveCount(0, { timeout: 15_000 });
  const cr = (await call("GET", `/v1/criteria?ticket_id=${storyA}`, undefined, asOwner)).find((x: any) => x.id === critA);
  expect(cr).toMatchObject({ verdict: "pass", evidence_version: 1 });
});

test("a stale version: the doc moved after the viewer read it; the board's refusal shows on the row (still, once the row says v2, until v2 is read), then the version read rules", async () => {
  // the last write's re-read (debounced) must land BEFORE the doc moves, or the row already shows v2
  await settled();
  const r = row(`c:${critStale}`);
  await r.locator(".ib-evidence").click(); // the viewer reads v1
  await expect(activeTab()).toContainText("v1", { timeout: 15_000 });
  await call("PATCH", `/v1/docs/${docStale}`, { body_md: "# Perf\n\nv2 numbers, re-measured.\n" }, as(ENG()));
  await expect(r.locator(".ib-pass")).toHaveText("Pass v1"); // no event in scope moved the doc: the row still shows v1
  await r.locator(".ib-pass").click();
  await expect(r.locator(".ib-error")).toContainText("you are ruling version 1 but the doc is now v2", { timeout: 15_000 });
  await page.screenshot({ path: shot("inbox-stale-refusal.png") });
  await expect(r.locator(".ib-fail")).toHaveText("Fail v2", { timeout: 15_000 }); // the host read the list again
  await expect(r.locator(".ib-error")).toContainText("the doc is now v2"); // the refusal stays until the next try
  await r.locator("textarea").fill("v2 numbers miss the p95 target.");
  // the row now says v2, but this viewer read v1: the verdict carries v1 and the board refuses it again
  await r.locator(".ib-fail").click();
  await expect(r.locator(".ib-error")).toContainText("you are ruling version 1 but the doc is now v2", { timeout: 15_000 });
  await expect(r).toHaveCount(1);
  await r.locator(".ib-evidence").click(); // read v2, then rule on it
  await expect(activeTab()).toContainText("v2", { timeout: 15_000 });
  await r.locator(".ib-fail").click();
  await expect(row(`c:${critStale}`)).toHaveCount(0, { timeout: 15_000 });
  const cr = (await call("GET", `/v1/criteria?ticket_id=${storyA}`, undefined, asOwner)).find((x: any) => x.id === critStale);
  expect(cr).toMatchObject({ verdict: "fail", evidence_version: 2 });
  const thread = await call("GET", `/v1/tickets/${storyA}/thread`, undefined, asOwner);
  expect(thread.thread.some((m: any) => /\[sign-off fail\] v2 numbers miss the p95 target\./.test(m.text ?? m.preview ?? ""))).toBe(true);
});

test("a scope gate: a text ruling answers it; the design review links out; the badge counts the rest", async () => {
  const c = chat();
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await expect.poll(keys, { timeout: 15_000 }).toEqual([`g:${EPIC()}:scope`, `g:${EPIC()}:design_signoff`, `q:${qTask}`, `q:${qB}`]);
  const r = row(`g:${EPIC()}:scope`);
  await r.locator("textarea").fill("Approved: the cap goes to 9 for C15-C20.");
  await r.locator(".ib-send").click();
  await expect(row(`g:${EPIC()}:scope`)).toHaveCount(0, { timeout: 15_000 });
  const open = await call("GET", `/v1/gates/${EPIC()}`, undefined, asOwner);
  expect(open.map((g: any) => g.gate)).toEqual(["design_signoff"]);
  const thread = await call("GET", `/v1/tickets/${EPIC()}/thread`, undefined, asOwner);
  expect(thread.thread.some((m: any) => /\[scope\] Approved: the cap goes to 9/.test(m.text ?? m.preview ?? ""))).toBe(true);
  await expect(c.locator("#tab-inbox .tab-badge")).toHaveText("3");
  await page.screenshot({ path: shot("inbox-after-writes.png") });
  // the design review links out to the board's epic page (C16 brings the editor reader)
  const popup = page.context().waitForEvent("page", { timeout: 15_000 });
  await row(`g:${EPIC()}:design_signoff`).locator("button", { hasText: "Review design" }).click();
  const confirm = page.locator(".monaco-dialog-box .monaco-button", { hasText: /^Open$/ });
  if (await confirm.isVisible({ timeout: 3_000 }).catch(() => false)) await confirm.click();
  const board = await popup;
  await expect.poll(() => board.url(), { timeout: 15_000 }).toContain(`/ui/epic/${EPIC()}`);
  await board.close();
  await expect(row(`g:${EPIC()}:design_signoff`)).toHaveCount(1); // opening is not answering
});

test("the webview never gets board access: no fetch or X-Token in the bundle", async () => {
  const js = fs.readFileSync(path.join(path.dirname(VSIX), "dist", "webview.js"), "utf8");
  expect(js).not.toMatch(/X-Token|EDP8_TOKEN|fetch\(|XMLHttpRequest|WebSocket/);
});
