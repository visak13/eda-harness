// C17 Decisions tab smoke (s-5e83f9d0af; design-10b21760d9 §14.2/§14.4): the chat's sixth tab lists the picked scope's
// decision records from GET /v1/decisions?scope= (an epic: its own and its stories'; live binding first, then newest;
// withdrawn dimmed with the reason), badge = live count. A row's source opens that message in Chat: its story's thread
// opens, older pages load until the message is there, and it is scrolled to and marked. As the owner, Withdraw (the
// reason asked in an input box) and Binding on/off are real writes asserted on the board. As an engineer seat the
// actions are hidden; as a seat of another epic the tab says it cannot read the list (a 403), without signing out.
// Runs in a REAL code-server against this file's own e2e board (never :9400/:9410). Browser: Chromium by default;
// CHAT_BROWSER=stockff runs the installed Firefox. One browser at a time.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c17-owner-tok-8d2e4a61c0";
const SEAT_TOKEN = "c17-seat-tok-51b7f0e3aa";
const STRANGER_TOKEN = "c17-stranger-tok-0c9a2f4d17";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-decisions", STOCK_FF ? "stockff" : "chromium");
const FILLER = 110; // more than one thread page (100): the source message is only reachable by loading older pages

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-decisions", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let cs: CodeServer | null = null;
let page: Page;
let story = "", seat = "", other = "", stranger = "", source = "";
let dBind = "", dStory = "", dNew = "", dGone = "";

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
const decision = async (id: string) => (await call("GET", `/v1/decisions?scope=${EPIC()}`, undefined, asOwner)).decisions.find((d: any) => d.id === id);

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
  if (value) await input.pressSequentially(value);
  await page.keyboard.press("Enter");
}
async function signIn(id: string, token: string): Promise<void> {
  await runCommand("EDP: Sign in to board");
  await typeInput(id, "EDP: board participant id");
  await typeInput(token, `EDP: token for ${id}`);
  await expect(page.locator(".notifications-toasts", { hasText: `signed in as ${id}` }).last()).toBeVisible({ timeout: 15_000 });
}
async function openThread(title: string): Promise<void> {
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await quickRow(page, title).click();
  await expect(chat().locator("#crumb-current")).toHaveText(title, { timeout: 20_000 });
}
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
const tab = async (id: string) => { await chat().locator(`#tab-${id}`).click(); await expect(chat().locator(`#tab-${id}`)).toHaveAttribute("aria-selected", "true"); };
const rows = () => chat().locator("#panel-decisions .de-row").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.id));
const row = (id: string) => chat().locator(`#panel-decisions .de-row[data-id="${id}"]`);

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c17-"));
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Rules", parent_id: EPIC() }, arch)).id;
  seat = `engineer.${story}`;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: seat, id: seat });
  // a seat of ANOTHER epic: the list is refused to it
  other = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Other epic" }, as("owner"))).id;
  const otherStory = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Other story", parent_id: other }, arch)).id;
  stranger = `engineer.${otherStory}`;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: stranger, id: stranger });
  // the source message, then more than a page of later messages on the story's thread
  source = (await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "Source: we pick CSS grid for the ship sheet." }, as(seat))).id;
  for (let i = 0; i < FILLER; i++) await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: `progress note ${i + 1}` }, as(seat));
  // decisions: a binding one on the epic (oldest), the story's (from the source message), a newer epic one, one withdrawn
  dBind = (await call("POST", "/v1/decisions", { scope: EPIC(), text: "Every tab is scoped to the picker.", binding: true }, arch)).id;
  dStory = (await call("POST", "/v1/decisions", { scope: story, text: "The ship sheet uses CSS grid.", detail: "Two columns collapse to one below 600 px.", source }, arch)).id;
  dNew = (await call("POST", "/v1/decisions", { scope: EPIC(), text: "Docs open in an editor tab." }, arch)).id;
  dGone = (await call("POST", "/v1/decisions", { scope: EPIC(), text: "A Decisions section inside Docs." }, arch)).id;
  await call("POST", `/v1/decisions/${dGone}/withdraw`, { reason: "the owner chose a sixth tab" }, arch);
  await call("POST", "/v1/decisions", { scope: other, text: "Another epic's rule." }, as("owner"));
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"),
    JSON.stringify({ owner: OWNER_TOKEN, agents: { [seat]: SEAT_TOKEN, [stranger]: STRANGER_TOKEN } }));
  await call("GET", "/v1/participants/owner", undefined, asOwner);
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE() });
  page = await browser.newPage();
  fs.mkdirSync(path.join(tmp, "ws"), { recursive: true });
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(path.join(tmp, "ws"))}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C17_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("the sixth tab lists the epic's and its story's decisions, binding first then newest; badge = live count", async () => {
  await signIn("owner", OWNER_TOKEN);
  await openThread("Spike epic");
  const c = chat();
  await expect(c.locator("[role=tablist] [role=tab]")).toHaveText([/^Chat/, /^Changes/, /^Commits/, /^Inbox/, /^Docs/, /^Decisions/]);
  await expect(c.locator("#tab-decisions .tab-badge")).toHaveText("3", { timeout: 20_000 });
  await tab("decisions");
  await expect.poll(rows, { timeout: 20_000 }).toEqual([dBind, dGone, dNew, dStory]);
  await expect(c.locator("#decisions-summary")).toHaveText("3 live, 1 withdrawn in this epic");
  await expect(row(dBind).locator(".de-flag-binding")).toHaveText("binding");
  await expect(row(dGone)).toHaveClass(/de-withdrawn/);
  await expect(row(dGone).locator(".de-reason")).toHaveText("Withdrawn: the owner chose a sixth tab");
  await expect(row(dStory).locator(".de-detail")).toHaveText("Two columns collapse to one below 600 px.");
  await expect(row(dStory).locator(".de-scope")).toHaveText("on Story Rules");
  // the owner manages: live rows carry Withdraw and Binding, the withdrawn one does not
  await expect(row(dNew).locator(`#de-withdraw-${dNew}`)).toBeVisible();
  await expect(row(dBind).locator(`#de-binding-${dBind}`)).toHaveText("Unbind");
  await expect(row(dGone).locator(".act", { hasText: /Withdraw|binding|Unbind/ })).toHaveCount(0);
  await page.screenshot({ path: shot("decisions-epic.png") });
});

test("a row's source opens in Chat: the story's thread, older pages loaded, the message scrolled to and marked", async () => {
  const c = chat();
  await row(dStory).locator(`#de-open-${dStory}`).click();
  await expect(c.locator("#crumb-current")).toHaveText("Story Rules", { timeout: 20_000 });
  await expect(c.locator("#tab-chat")).toHaveAttribute("aria-selected", "true");
  const msg = c.locator(`.msg[data-id="${source}"]`);
  await expect(msg).toHaveClass(/focus-source/, { timeout: 20_000 });
  await expect(msg).toBeInViewport();
  await expect(msg.locator(".body")).toContainText("we pick CSS grid");
  expect(await c.locator(".msg").count()).toBeGreaterThan(100); // an older page was loaded to reach it
  await page.screenshot({ path: shot("source-in-chat.png") });
  // the story scope lists only its own decision
  await tab("decisions");
  await expect.poll(rows, { timeout: 15_000 }).toEqual([dStory]);
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
});

test("Withdraw asks the reason and lands on the board; Binding off and on are real writes", async () => {
  const c = chat();
  await tab("decisions");
  await expect.poll(rows, { timeout: 15_000 }).toContain(dNew);
  await row(dNew).locator(`#de-withdraw-${dNew}`).click();
  await typeInput("superseded by design v12 §14.4", `EDP: Withdraw ${dNew}`);
  await expect(row(dNew)).toHaveClass(/de-withdrawn/, { timeout: 15_000 });
  await expect(row(dNew).locator(".de-reason")).toHaveText("Withdrawn: superseded by design v12 §14.4");
  expect(await decision(dNew)).toMatchObject({ status: "withdrawn", withdrawn_reason: "superseded by design v12 §14.4" });
  await expect(c.locator("#tab-decisions .tab-badge")).toHaveText("2");
  // Binding off (reason optional: an empty box is accepted), then on again
  await row(dBind).locator(`#de-binding-${dBind}`).click();
  await typeInput("", `EDP: Stop making ${dBind} binding`);
  await expect(row(dBind).locator(".de-flag-binding")).toHaveCount(0, { timeout: 15_000 });
  expect((await decision(dBind)).binding).toBe(false);
  await expect(row(dBind).locator(`#de-binding-${dBind}`)).toHaveText("Make binding");
  await row(dBind).locator(`#de-binding-${dBind}`).click();
  await typeInput("the owner's ruling m-db09472a68", `EDP: Make ${dBind} binding`);
  await expect(row(dBind).locator(".de-flag-binding")).toHaveText("binding", { timeout: 15_000 });
  expect((await decision(dBind)).binding).toBe(true);
  await expect.poll(rows).toEqual([dBind, dGone, dNew, dStory]); // binding first again, then newest (withdrawn rows keep their date place)
  await page.screenshot({ path: shot("decisions-after-writes.png") });
});

test("as an engineer seat of the story: the list shows, the actions are hidden", async () => {
  await signIn(seat, SEAT_TOKEN);
  await openThread("Story Rules");
  const c = chat();
  await tab("decisions");
  await expect.poll(rows, { timeout: 20_000 }).toEqual([dStory]);
  await expect(c.locator("#panel-decisions [id^=de-withdraw-], #panel-decisions [id^=de-binding-]")).toHaveCount(0);
  await expect(row(dStory).locator(`#de-open-${dStory}`)).toBeVisible();
  await page.screenshot({ path: shot("decisions-seat-readonly.png") });
});

test("as a seat of another epic: the tab says it cannot read the list, and the panel stays signed in", async () => {
  await signIn(stranger, STRANGER_TOKEN);
  await openThread("Story Rules");
  const c = chat();
  // C26 rule 1: a composer draft typed before the 403 stays, and the feed stays live
  await expect(c.locator("#feed-status")).toHaveText("live", { timeout: 20_000 });
  await tab("chat");
  await c.locator("#composer").fill("a draft typed before the Decisions tab");
  await tab("decisions");
  await expect(c.locator("#decisions-error")).toContainText("You cannot read this epic's decisions", { timeout: 20_000 });
  await expect(c.locator("#decisions-error")).toContainText("is not a participant of");
  await expect(c.locator("#panel-decisions .de-row")).toHaveCount(0);
  await tab("chat");
  await expect(c.locator(".msg").first()).toBeVisible(); // still reading the thread: a 403 on the list is not a sign-out
  await expect(c.locator("#composer")).toHaveValue("a draft typed before the Decisions tab");
  await expect(c.locator("#feed-status")).toHaveText("live");
  await expect(c.locator("#notice")).toBeHidden();
  await page.screenshot({ path: shot("decisions-stranger-403.png") });
});

test("the webview bundle never gets board access: no fetch or X-Token", async () => {
  const js = fs.readFileSync(path.join(path.dirname(VSIX), "dist", "webview.js"), "utf8");
  expect(js).not.toMatch(/X-Token|EDP8_TOKEN|fetch\(|XMLHttpRequest|WebSocket/);
});
