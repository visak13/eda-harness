// C16 Docs tab + EDP reader smoke (s-579fa02cca; design-10b21760d9 §14.2/§14.4/§14.7): the picked scope's linked docs
// in the chat's fifth tab; a doc opens in the EDP reader editor tab (rendered markdown, outline, version picker, full
// screen); Compare opens vscode.diff over two versions' markdown; the design under an open design_signoff shows
// Approve / Request changes in the editor title only when the board says can_approve, and ONE real request-changes and
// ONE real approve are asserted on the board; a proposed strategy_ll shows Approve / Reject with its diff against the
// active doc, and one real approve lands; the version's comments list under the doc. Runs in a REAL code-server against
// this file's own e2e board (never :9400/:9410). Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed
// Firefox. One browser at a time.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Frame, FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c16-owner-tok-3f1a9d2c7b";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-docs", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-docs", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let cs: CodeServer | null = null;
let page: Page;
let design = "", activeLl = "", proposal = "", report = "", story = "";
const DESIGN_V1 = "# Spike design\n\n## 1. Words\n\n> a chat panel beside the editor\n\n## 2. Plan\n\n- one tab\n- one reader\n";
const DESIGN_V2 = "# Spike design\n\n## 1. Words\n\n> a chat panel beside the editor\n\n## 2. Plan\n\n- five tabs\n- one reader, full screen\n\n## 3. Risks\n\nFirefox webviews.\n";

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
/** The reader's inner frame: the webview document that holds #rd-title for this doc. */
async function reader(docId: string, version: number): Promise<Frame> {
  let found: Frame | undefined;
  await expect.poll(async () => {
    for (const f of page.frames()) {
      const t = await f.locator("#rd-title").count().catch(() => 0);
      if (!t) continue;
      const title = await f.title().catch(() => "");
      if (title === `EDP ${docId} v${version}`) { found = f; return true; }
    }
    return false;
  }, { timeout: 30_000, intervals: [500] }).toBe(true);
  return found!;
}
/** An editor-title action of the active editor group (the reader's Approve, Request changes, Compare, …). */
const titleAction = (label: RegExp) => page.locator(".editor-group-container.active .editor-actions").getByRole("button", { name: label });
const activeTab = () => page.locator(".tabs-container .tab.active");
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
const tab = async (id: string) => { await chat().locator(`#tab-${id}`).click(); await expect(chat().locator(`#tab-${id}`)).toHaveAttribute("aria-selected", "true"); };
const docRows = () => chat().locator("#panel-docs .dc-row").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.id));

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c16-"));
  await call("POST", "/v1/participants", { type: "agent", role: "sme", handle: "sme", id: "sme" });
  // the epic's design, at two versions, under an open design_signoff (the epic is owner-created: the owner reviews it)
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "Spike design", body_md: DESIGN_V1, scope: EPIC() }, arch)).id;
  await call("PATCH", `/v1/docs/${design}`, { body_md: DESIGN_V2 }, arch);
  await call("POST", "/v1/criteria", { ticket_id: EPIC(), text: "The reader opens the design", check: "look" }, arch);
  await call("PATCH", `/v1/tickets/${EPIC()}`, { design_ref: design }, arch);
  await call("POST", `/v1/gates/${EPIC()}/design_signoff/open`, { note: "design v2 is ready" }, arch);
  // a strategy_ll the epic uses, and a proposal that revises it (linked too, so the Docs tab lists it)
  activeLl = (await call("POST", "/v1/docs", { doc_type: "strategy_ll", title: "ll-craft reader", body_md: "# ll\n\n- inline the bundle\n", scope: EPIC() }, as("sme"))).id;
  proposal = (await call("POST", "/v1/docs", { doc_type: "strategy_ll", title: "ll-craft reader", body_md: "# ll\n\n- inline the bundle\n- nonce per resolve\n", scope: EPIC(), status: "proposed", proposes: activeLl }, as("sme"))).id;
  await call("POST", "/v1/links", { from_id: EPIC(), to_id: activeLl, relation: "uses_strategy" }, arch);
  await call("POST", "/v1/links", { from_id: EPIC(), to_id: proposal, relation: "uses_strategy" }, arch);
  // a story with a report as its criterion's evidence (a story scope lists only its own docs)
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Reader", parent_id: EPIC() }, arch)).id;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: `engineer.${story}`, id: `engineer.${story}` });
  report = (await call("POST", "/v1/docs", { doc_type: "report", title: "Reader report", body_md: "# Reader report\n\nWorks.\n", scope: EPIC() }, as(`engineer.${story}`))).id;
  const crit = await call("POST", "/v1/criteria", { ticket_id: story, text: "report exists", check: "look" }, arch);
  await call("PATCH", `/v1/criteria/${crit.id}`, { evidence_ref: report }, as(`engineer.${story}`));
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
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
  if (tmp && !process.env.C16_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("the Docs tab: the fifth tab lists the epic's design, strategy and proposal; a story lists only its own", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await quickRow(page, "Spike epic").click();
  const c = chat();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  await expect(c.locator("[role=tablist] [role=tab]")).toHaveText([/^Chat/, /^Changes/, /^Commits/, /^Inbox/, /^Docs/]);
  await tab("docs");
  // the epic scope covers its stories too: the story's evidence report is listed
  await expect.poll(async () => (await docRows()).slice().sort(), { timeout: 20_000 }).toEqual([design, activeLl, proposal, report].sort());
  expect((await docRows())[0]).toBe(design); // the design first, then the strategy layers, then reports
  expect((await docRows())[3]).toBe(report);
  const row = (id: string) => c.locator(`#panel-docs .dc-row[data-id="${id}"]`);
  await expect(row(design).locator(".dc-type")).toHaveText("design");
  await expect(row(design).locator(".dc-version")).toHaveText("v2");
  await expect(row(proposal).locator(".dc-status")).toHaveText("proposed");
  await expect(c.locator("#tab-docs .tab-badge")).toHaveText("1");
  await page.screenshot({ path: shot("docs-epic.png") });
  await c.locator("#stories-toggle").click();
  await c.locator(`.story[data-id="${story}"]`).click();
  await expect(c.locator("#crumb-current")).toHaveText("Story Reader", { timeout: 15_000 });
  await expect.poll(docRows, { timeout: 15_000 }).toEqual([report]);
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await expect.poll(docRows, { timeout: 15_000 }).toContain(design);
});

test("the reader: the design opens in an editor tab, rendered, with an outline and a version picker; full screen; the source is one click away", async () => {
  const c = chat();
  await c.locator(`#panel-docs .dc-row[data-id="${design}"] .dc-open`).click();
  await expect(activeTab()).toContainText("Spike design · v2", { timeout: 20_000 });
  const r = await reader(design, 2);
  await expect(r.locator("#rd-title")).toHaveText("Spike design");
  await expect(r.locator("#doc h2")).toHaveText(["1. Words", "2. Plan", "3. Risks"]);
  await expect(r.locator(".rd-toc a")).toHaveText(["Spike design", "1. Words", "2. Plan", "3. Risks"]);
  await expect(r.locator("#rd-version option")).toHaveText(["v2 (current)", "v1"]);
  await expect(r.locator("#doc li").first()).toHaveAttribute("data-ls", "9"); // "- five tabs" is line 9 of v2
  // the review is open for the owner on the current version: the editor title carries both actions
  await expect(titleAction(/^Approve design/)).toBeVisible({ timeout: 15_000 });
  await expect(titleAction(/^Request changes on the design/)).toBeVisible();
  await expect(r.locator("#rd-review #rd-approve")).toHaveText("Approve v2");
  await page.screenshot({ path: shot("reader-design.png") });
  // full screen: the side bars (Explorer and the chat) give the reader the whole window; again restores them
  const sidebar = page.locator(".part.sidebar");
  await expect(sidebar).toBeVisible();
  await titleAction(/^Full screen/).click();
  await expect(sidebar).toBeHidden({ timeout: 10_000 });
  await expect(page.locator(".part.auxiliarybar")).toBeHidden();
  await page.screenshot({ path: shot("reader-design-fullscreen.png") });
  await titleAction(/^Full screen/).click();
  await expect(sidebar).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".part.auxiliarybar")).toBeVisible();
  // an older version: no review actions (the board says can_approve only on the current one)
  await r.locator("#rd-version").selectOption("1");
  await expect(activeTab()).toContainText("Spike design · v1", { timeout: 20_000 });
  const r1 = await reader(design, 1);
  await expect(r1.locator("#rd-review .rd-note")).toHaveText("You are reading v1; the design is now v2. Review v2.", { timeout: 15_000 });
  await expect(titleAction(/^Approve design/)).toHaveCount(0);
  await titleAction(/^Open markdown source/).click();
  await expect(activeTab()).toContainText("v1.md", { timeout: 15_000 });
});

test("compare: two versions of the design in the diff editor, the older on the left", async () => {
  const c = chat();
  await tab("docs");
  await c.locator(`#panel-docs .dc-row[data-id="${design}"] .act`, { hasText: "Compare" }).click();
  await quickRow(page, /^v2/).click();
  await quickRow(page, /^v1/).click();
  await expect(activeTab()).toContainText(`${design} v1 ↔ v2`, { timeout: 15_000 });
  const diff = page.locator(".editor-group-container.active .monaco-diff-editor");
  await expect(diff.locator(".modified .view-lines")).toContainText("five tabs", { timeout: 15_000 });
  await expect(diff.locator(".original .view-lines")).toContainText("one tab");
  await page.screenshot({ path: shot("compare-v1-v2.png") });
});

test("the design review, opened from the Inbox's design_signoff row: Request changes (title-bar feedback) then Approve, each a real write on the board", async () => {
  const c = chat();
  await tab("inbox");
  await c.locator(`#panel-inbox .ib-row[data-key="g:${EPIC()}:design_signoff"] button`, { hasText: "Review design" }).click();
  await expect(activeTab()).toContainText("Spike design · v2", { timeout: 20_000 });
  const r = await reader(design, 2);
  await expect(titleAction(/^Request changes on the design/)).toBeVisible({ timeout: 15_000 });
  await titleAction(/^Request changes on the design/).click();
  await typeInput("Split §2 into two stories.", "EDP: Request changes on");
  await expect(r.locator("#rd-status")).toHaveText(/Requested changes on .* v2/, { timeout: 15_000 });
  const thread = await call("GET", `/v1/tickets/${EPIC()}/thread`, undefined, asOwner);
  const steer = thread.thread.find((m: any) => /Split §2 into two stories\./.test(m.text ?? m.preview ?? ""));
  expect(steer).toBeTruthy();
  const full = await call("GET", `/v1/messages/${steer.id}`, undefined, asOwner);
  expect(full).toMatchObject({ kind: "steer", to: "architect", created_by: "owner", document_context: { design_ref: design, reviewed_version: 2 } });
  // the request lists as a comment on v2
  await expect(r.locator("#rd-comments .rd-comment")).toHaveCount(1, { timeout: 15_000 });
  await expect(r.locator("#rd-comments .rd-comment-body")).toContainText("Split §2 into two stories.");
  expect((await call("GET", `/v1/gates/${EPIC()}`, undefined, asOwner)).map((g: any) => g.gate)).toContain("design_signoff");
  await page.screenshot({ path: shot("reader-request-changes.png") });
  await titleAction(/^Approve design/).click();
  await expect(r.locator("#rd-status")).toHaveText(`Approved ${design} v2.`, { timeout: 15_000 });
  expect((await call("GET", `/v1/gates/${EPIC()}`, undefined, asOwner)).map((g: any) => g.gate)).not.toContain("design_signoff");
  const after = await call("GET", `/v1/tickets/${EPIC()}/thread`, undefined, asOwner);
  expect(after.thread.some((m: any) => new RegExp(`Approved ${design} v2`).test(m.text ?? m.preview ?? ""))).toBe(true);
  // the gate closed: the actions leave the title bar
  await expect(titleAction(/^Approve design/)).toHaveCount(0, { timeout: 15_000 });
  await expect(r.locator("#rd-review .rd-note")).toHaveText("No design review is open on this design.");
});

test("a proposed strategy_ll: Approve / Reject with its diff against the active doc; Approve makes the active doc v2", async () => {
  const c = chat();
  await tab("docs");
  await c.locator(`#panel-docs .dc-row[data-id="${proposal}"] .dc-open`).click();
  const r = await reader(proposal, 1);
  await expect(r.locator("#rd-proposal .rd-h")).toHaveText(`Proposed revision of ${activeLl} v1 (active)`);
  await expect(r.locator("#rd-diff .dl-add")).toHaveText(["- nonce per resolve"].map(x => `+${x}\n`));
  await expect(titleAction(/^Approve proposed doc/)).toBeVisible({ timeout: 15_000 });
  await expect(titleAction(/^Reject proposed doc/)).toBeVisible();
  await page.screenshot({ path: shot("reader-proposal.png") });
  await titleAction(/^Approve proposed doc/).click();
  await expect(r.locator("#rd-status")).toHaveText(`Approved: ${activeLl} is now v2.`, { timeout: 15_000 });
  const ll = await call("GET", `/v1/docs/${activeLl}`, undefined, asOwner);
  expect(ll).toMatchObject({ version: 2, status: "active" });
  expect(ll.body_md).toContain("nonce per resolve");
  expect((await call("GET", `/v1/docs/${proposal}`, undefined, asOwner)).status).toBe("retired");
  await expect(titleAction(/^Approve proposed doc/)).toHaveCount(0, { timeout: 15_000 });
});

test("the webview bundles never get board access: no fetch or X-Token", async () => {
  for (const f of ["reader.js", "webview.js"]) {
    const js = fs.readFileSync(path.join(path.dirname(VSIX), "dist", f), "utf8");
    expect(js).not.toMatch(/X-Token|EDP8_TOKEN|fetch\(|XMLHttpRequest|WebSocket/);
  }
});
