// C5 change-card smoke (s-ab8e69650e; strategyll-86c5b5068f §4): commits in the EDP chat timeline opening
// VS Code's diff and multi-diff, live on a new commit, and the pinned "Uncommitted changes — all seats"
// card, in a REAL code-server against this file's own e2e board (never :9400/:9410). The workspace is a
// throwaway git repo built here, so every commit, trailer and file status is what git itself records.
// Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox (moz-firefox channel,
// m-5dcb142053). Run one browser at a time.
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
const OWNER_TOKEN = "c5-owner-tok-3c9e1a7d52";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-changes", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-changes", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let repo = "";
let cs: CodeServer | null = null;
let page: Page;
let storyA = "", storyB = "", taskA = "";
const sha: Record<string, string> = {};
const ENG = () => `engineer.${storyA}`;
const timing: Record<string, number> = {};

// -- board ----------------------------------------------------------------------------------------
async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const agentTok = (id: string) => `c5-agent-${id.replace(/\W/g, "")}`;

// -- the fixture repo: real commits, fixed times so cards and messages order deterministically ---------
let tick = Math.floor(Date.now() / 1000) - 3 * 3600;
function g(args: string[], at?: number): string {
  const env = { ...process.env, ...(at ? { GIT_AUTHOR_DATE: `${at} +0000`, GIT_COMMITTER_DATE: `${at} +0000` } : {}) };
  return execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "-c", "core.autocrlf=false", ...args],
    { cwd: repo, encoding: "utf8", env });
}
function commit(key: string, subject: string, body?: string, at = (tick += 600)): string {
  g(["commit", "-q", "-m", subject, ...(body ? ["-m", body] : [])], at);
  return (sha[key] = g(["rev-parse", "HEAD"]).trim());
}
const write = (rel: string, text: string) => { fs.mkdirSync(path.dirname(path.join(repo, rel)), { recursive: true }); fs.writeFileSync(path.join(repo, rel), text); };

function makeRepo(): void {
  repo = path.join(tmp, "fixture-repo");
  fs.mkdirSync(repo, { recursive: true });
  g(["init", "-q", "-b", "main"]);
  write("src/sample.py", Array.from({ length: 12 }, (_, i) => `value_${i + 1} = ${i + 1}`).join("\n") + "\n");
  write("src/old_name.py", "print('rename me')\n");
  write("docs/gone.md", "# to be deleted\n");
  g(["add", "."]); commit("root", "fixture: first files");
  write("src/sample.py", fs.readFileSync(path.join(repo, "src/sample.py"), "utf8").replace("value_3 = 3", "value_3 = 33").replace("value_9 = 9\n", ""));
  write("docs/alpha.md", "# Alpha\nnew doc\n");
  g(["add", "."]);
  commit("alpha", "feat: alpha work", `Alpha changes.\n\nEDP-Ticket: ${storyA}\nEDP-Seat: ${ENG()}`);
  write("src/task.py", "task = 1\n"); g(["add", "."]);
  commit("task", `chore(${taskA}): task work`);
  write("src/epic.py", "epic = 1\n"); g(["add", "."]);
  commit("epic", "chore: epic-level wiring", `EDP-Ticket: ${EPIC()}\nEDP-Seat: architect.${EPIC()}`);
  g(["mv", "src/old_name.py", "src/new_name.py"]); g(["rm", "-q", "docs/gone.md"]);
  commit("unlinked", "chore: rename and delete, no ticket");
}

// -- workbench ------------------------------------------------------------------------------------
const quick = (p: Page) => p.locator(".quick-input-widget");
const quickRow = (p: Page, text: string | RegExp) => quick(p).locator(".monaco-list-row", { hasText: text }).first();
async function runCommand(title: string): Promise<void> {
  // F1 is lost while key focus sits in a webview frame (or moves to an editor just opened): retry it
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
/** C9: stories live in the header's Stories dropdown; open it, then click the story. */
async function openStory(id: string): Promise<void> {
  const c = chat();
  if ((await c.locator("#stories-toggle").getAttribute("aria-expanded")) !== "true") await c.locator("#stories-toggle").click();
  await c.locator(`.story[data-id="${id}"]`).click();
}
// C13: commits are expandable cards in the Commits tab and one-line markers in the Chat timeline
const card = (key: string) => chat().locator(`#panel-commits .commit[data-sha="${sha[key]}"]`);
const marker = (key: string) => chat().locator(`#timeline .cmark[data-sha="${sha[key]}"]`);
const tab = async (id: string) => { await chat().locator(`#tab-${id}`).click(); await expect(chat().locator(`#tab-${id}`)).toHaveAttribute("aria-selected", "true"); };
/** Painted, not merely laid out: a real height, and the point at its middle hits the element (C9's chips
 *  toggled but their box was squeezed to ~0 px by a long thread, and toBeVisible() passed anyway). */
async function painted(l: ReturnType<FrameLocator["locator"]>, minHeight = 12): Promise<void> {
  await expect.poll(() => l.evaluate((e, min) => {
    const r = e.getBoundingClientRect();
    const hit = e.ownerDocument.elementFromPoint(r.x + Math.min(8, r.width / 2), r.y + Math.min(r.height / 2, 8));
    return r.height >= min && !!hit && (e === hit || e.contains(hit));
  }, minHeight), { timeout: 5_000 }).toBe(true);
}
const activeTab = () => page.locator(".tabs-container .tab.active");

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c5-"));
  const arch = { "X-Participant": "arch" };
  storyA = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Alpha", parent_id: EPIC() }, arch)).id;
  storyB = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Beta", parent_id: EPIC() }, arch)).id; // Story Beta: a second story in the strip
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: ENG(), id: ENG() });
  taskA = (await call("POST", "/v1/tickets", { kind: "task", work_type: "feature", title: "Alpha task", parent_id: storyA, assignee: ENG() }, arch)).id;
  await call("POST", "/v1/messages", { ticket_id: storyA, kind: "note", text: "Alpha thread message, newer than every fixture commit" }, { "X-Participant": ENG() });
  // a long epic thread (the owner's: 100+ messages), the case C9's chips failed on
  for (let i = 0; i < 150; i++) await call("POST", "/v1/messages", { ticket_id: EPIC(), kind: "note", text: `epic chatter ${i}: ${"words ".repeat(12)}` }, { "X-Participant": "arch" });
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN, [ENG()]: agentTok(ENG()) }));
  await call("GET", "/v1/participants/owner", undefined, asOwner);
  makeRepo();
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE(), "edp.sharedTreePaths": [repo] });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first()).toBeVisible({ timeout: 60_000 });
});

test.afterAll(async () => {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  fs.writeFileSync(path.join(EVIDENCE, "timing.json"), JSON.stringify(timing, null, 1));
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C5_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("the epic: Chat shows only epic-named commits as markers; Commits aggregates the epic and its stories, labelled; Unlinked collapsed at the bottom", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await quickRow(page, "Spike epic").click();
  const c = chat();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  // one header row, then the tab bar; Chat is the default
  await expect(c.locator("[role=tablist] [role=tab]")).toHaveText([/^Chat/, /^Changes/, /^Commits/]);
  await expect(c.locator("#tab-chat")).toHaveAttribute("aria-selected", "true");
  const hb = await c.locator("header.hdr").boundingBox(), tb = await c.locator(".tabbar").boundingBox();
  expect(tb!.y).toBeGreaterThanOrEqual(hb!.y + hb!.height - 1);
  // the long thread really is long
  expect(await c.locator("#timeline").evaluate(e => e.scrollHeight > 2 * e.clientHeight)).toBe(true);
  await expect(marker("epic")).toHaveCount(1, { timeout: 20_000 });
  await expect(marker("epic")).toContainText(sha.epic.slice(0, 7));
  await expect(marker("alpha")).toHaveCount(0); // m-2e3b14065e: a story's commits never mark the epic chat
  await expect(c.locator("#timeline .commit")).toHaveCount(0); // full cards left the chat
  await expect(c.locator(`.story[data-id="${storyA}"] .st-commits`)).toHaveText("⎇ 2");
  await tab("commits");
  await expect(card("epic")).toBeVisible();
  const shas = await c.locator("#panel-commits .cm-list > .commit").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.sha));
  expect(shas).toEqual([sha.epic, sha.task, sha.alpha]); // newest first
  await expect(card("alpha").locator(".cm-story")).toHaveText("Story Alpha");
  await expect(card("epic").locator(".cm-story")).toHaveText("epic");
  await expect(card("epic").locator(".cm-seat")).toHaveText(`architect.${EPIC()}`);
  await expect(c.locator("#panel-commits > .group").last()).toHaveId("commits-unlinked");
  await expect(c.locator("#commits-unlinked-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(c.locator("#commits-unlinked-toggle")).toContainText("Unlinked2");
  await c.locator("#commits-unlinked-toggle").click();
  await expect(c.locator("#commits-unlinked-toggle")).toHaveAttribute("aria-expanded", "true");
  await painted(c.locator(`#commits-unlinked .commit[data-sha="${sha.unlinked}"]`));
  await expect(c.locator(`#commits-unlinked .commit[data-sha="${sha.unlinked}"] .cm-seat`)).toHaveText("unlinked");
  await page.screenshot({ path: shot("epic-commits-tab.png") });
  // keyboard: Enter on the focused header folds it again
  await c.locator("#commits-unlinked-toggle").focus();
  await page.keyboard.press("Enter");
  await expect(c.locator("#commits-unlinked-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(c.locator("#commits-unlinked .commit")).toHaveCount(0);
});

test("switching threads keeps the tab; a story's Commits: trailer and subject-attributed cards expand by click to files ±", async () => {
  const c = chat();
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
  await expect(c.locator("#tab-commits")).toHaveAttribute("aria-selected", "true");
  const a = card("alpha");
  await expect(a.locator(".cm-seat")).toHaveText(ENG());
  await expect(a.locator(".cm-sha")).toHaveText(sha.alpha.slice(0, 7));
  await expect(a.locator(".cm-subject")).toHaveText("feat: alpha work");
  await expect(a.locator(".cm-story")).toHaveCount(0);
  await expect(a.locator(".cf")).toHaveCount(0); // folded
  await a.locator(".cm-head").click();
  await expect(a.locator(".cm-head")).toHaveAttribute("aria-expanded", "true");
  await expect(a.locator(".cf")).toHaveText(["Adocs/alpha.md+2−0", "Msrc/sample.py+1−2"]);
  await painted(a.locator(".cf").first());
  await expect(card("task").locator(".cm-seat")).toHaveText(`${ENG()} (assignee)`);
  await expect(c.locator("#commits-unlinked")).toHaveCount(0);
  await page.screenshot({ path: shot("story-commits-tab.png") });
  // the Chat: both commits as markers, before the (newer) thread message
  await tab("chat");
  const order = await c.locator("#timeline .items > *").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.sha ?? (e as HTMLElement).dataset.id ?? e.className));
  const iMsg = order.findIndex(x => typeof x === "string" && x.startsWith("m-"));
  expect(order.indexOf(sha.alpha)).toBeGreaterThanOrEqual(0);
  expect(order.indexOf(sha.alpha)).toBeLessThan(iMsg);
  expect(order.indexOf(sha.task)).toBeGreaterThan(order.indexOf(sha.alpha));
  await page.screenshot({ path: shot("story-chat-markers.png") });
});

test("a Chat marker opens its commit in the Commits tab, expanded and focused", async () => {
  const c = chat();
  await marker("task").click();
  await expect(c.locator("#tab-commits")).toHaveAttribute("aria-selected", "true");
  await expect(card("task").locator(".cm-head")).toHaveAttribute("aria-expanded", "true");
  await expect(card("task").locator(".cm-head")).toBeFocused();
  await expect(card("task").locator(".cf")).toHaveText(["Asrc/task.py+1−0"]);
});

test("a file row opens the side-by-side diff (added file against an empty side); Open all opens the multi-diff", async () => {
  const a = card("alpha");
  await a.locator(`.cf[data-path="src/sample.py"]`).click();
  await expect(page.locator(".monaco-diff-editor").first()).toBeVisible({ timeout: 15_000 });
  await expect(activeTab()).toContainText(`src/sample.py (${sha.alpha.slice(0, 7)})`);
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "value_3 = 33" }).first()).toBeVisible();
  await page.screenshot({ path: shot("file-diff-modified.png") });
  await a.locator(`.cf[data-path="docs/alpha.md"]`).click();
  await expect(activeTab()).toContainText(`docs/alpha.md (${sha.alpha.slice(0, 7)})`, { timeout: 15_000 });
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "new doc" }).first()).toBeVisible();
  await expect(page.locator(".notifications-toasts .notification-toast", { hasText: /Unable to resolve|FileNotFound|nonexistent/i })).toHaveCount(0);
  await a.locator(".cm-open").click();
  await expect(activeTab()).toContainText(`${sha.alpha.slice(0, 7)} feat: alpha work`, { timeout: 15_000 });
  await expect(page.locator(".view-line", { hasText: "value_3 = 33" }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".view-line", { hasText: "new doc" }).first()).toBeVisible();
  await page.screenshot({ path: shot("card-multi-diff.png") });
});

test("the epic's unlinked rename + delete commit opens without errors (old path on the left, deleted side empty)", async () => {
  const c = chat();
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await c.locator("#commits-unlinked-toggle").click();
  const u = c.locator(`#commits-unlinked .commit[data-sha="${sha.unlinked}"]`);
  await u.locator(".cm-head").click();
  await expect(u.locator(".cf")).toHaveText(["Ddocs/gone.md+0−1", "Rsrc/old_name.py → src/new_name.py+0−0"]);
  await u.locator(".cm-open").click();
  await expect(activeTab()).toContainText(`${sha.unlinked.slice(0, 7)} chore: rename and delete, no ticket`, { timeout: 15_000 });
  await u.locator(`.cf[data-path="docs/gone.md"]`).click();
  await expect(activeTab()).toContainText(`docs/gone.md (${sha.unlinked.slice(0, 7)})`, { timeout: 15_000 });
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "to be deleted" }).first()).toBeVisible();
  await expect(page.locator(".notifications-toasts .notification-toast", { hasText: /Unable to resolve|FileNotFound|nonexistent/i })).toHaveCount(0);
  await c.locator("#commits-unlinked-toggle").click();
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
});

test("a new commit naming the open story: Commits badge + card while on another tab, a Chat marker within 10 s, no reload; the strip count follows", async () => {
  const c = chat();
  await tab("chat");
  await expect(c.locator("#tab-commits .tab-badge")).toHaveCount(0);
  write("src/live.py", "live = 1\n");
  g(["add", "src/live.py"]);
  const t0 = Date.now();
  commit("live", "feat: live commit", `EDP-Ticket: ${storyA}\nEDP-Seat: ${ENG()}`, Math.floor(Date.now() / 1000));
  await expect(marker("live")).toBeVisible({ timeout: 10_000 });
  timing.commit_to_marker_ms = Date.now() - t0;
  const last = await c.locator("#timeline .items > *").last().getAttribute("data-sha");
  expect(last).toBe(sha.live); // newer than the thread message: at the bottom
  await expect(c.locator("#tab-commits .tab-badge")).toHaveText("1");
  await expect(c.locator("#tab-commits")).toHaveAttribute("aria-label", "Commits, 1 new commit");
  await expect(c.locator(`.story[data-id="${storyA}"] .st-commits`)).toHaveText("⎇ 3");
  await page.screenshot({ path: shot("live-commit-marker-badge.png") });
  await tab("commits");
  await expect(c.locator("#panel-commits .cm-list > .commit").first()).toHaveAttribute("data-sha", sha.live);
  await expect(c.locator("#tab-commits .tab-badge")).toHaveCount(0); // seen
});

test("Changes on the long epic thread: this epic's files open first, all seats folded; every group header expands and collapses by a real click and by keyboard, painted; diffs; state survives a reload", async () => {
  const c = chat();
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await tab("changes");
  await expect(c.locator("#changes-summary")).toHaveText("The shared tree is clean", { timeout: 15_000 });
  await expect(c.locator("#changes-open-all")).toBeDisabled();
  const t0 = Date.now();
  write("src/sample.py", fs.readFileSync(path.join(repo, "src/sample.py"), "utf8") + "value_99 = 99\n");
  write("notes/untracked.md", "scratch\n");
  await expect(c.locator(`#changes-scoped .cf[data-path="src/sample.py"]`)).toBeVisible({ timeout: 5_000 });
  timing.save_to_changes_ms = Date.now() - t0;
  // option (a): src/sample.py is in a commit of this epic's story, notes/untracked.md in none
  await expect(c.locator("#tab-changes .tab-badge")).toHaveText("1");
  await expect(c.locator("#changes-summary")).toHaveText("2 files uncommitted in the shared tree");
  await expect(c.locator("#changes-scoped-toggle")).toHaveAttribute("aria-expanded", "true");
  await painted(c.locator(`#changes-scoped .cf[data-path="src/sample.py"]`));
  await expect(c.locator("#changes-all-toggle")).toContainText("All seats1 more");
  await expect(c.locator("#changes-all-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(c.locator(`.cf[data-path="notes/untracked.md"]`)).toHaveCount(0);
  // the C9 bug (m-53858f39c4): a real click must expand AND paint the group, on a 150-message thread
  await c.locator("#changes-all-toggle").click();
  await expect(c.locator("#changes-all-toggle")).toHaveAttribute("aria-expanded", "true");
  await painted(c.locator(`#changes-all .cf[data-path="notes/untracked.md"]`));
  await page.screenshot({ path: shot("changes-tab-expanded.png") });
  await c.locator("#changes-scoped-toggle").click();
  await expect(c.locator("#changes-scoped-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(c.locator("#changes-scoped .cf")).toHaveCount(0);
  await c.locator("#changes-scoped-toggle").focus();
  await page.keyboard.press("Enter");
  await expect(c.locator("#changes-scoped-toggle")).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Space");
  await expect(c.locator("#changes-scoped-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Space");
  await painted(c.locator(`#changes-scoped .cf[data-path="src/sample.py"]`));
  await expect(c.locator("#panel-changes .cm-seat")).toHaveCount(0); // names no seat
  // scoped multi-diff, then the reload: the webview is disposed and re-resolved
  await c.locator("#changes-open-scoped").click();
  await expect(activeTab()).toContainText("Uncommitted changes — this epic", { timeout: 15_000 });
  await activeTab().click(); // Firefox keeps key focus in the webview frame; F1 must reach the workbench
  await runCommand("View: Toggle Secondary Side Bar Visibility");
  await expect(page.locator(".part.auxiliarybar")).toBeHidden({ timeout: 10_000 });
  await runCommand("View: Toggle Secondary Side Bar Visibility");
  await expect(page.locator(".part.auxiliarybar")).toBeVisible({ timeout: 10_000 });
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  await expect(c.locator("#tab-changes")).toHaveAttribute("aria-selected", "true");
  await expect(c.locator("#changes-all-toggle")).toHaveAttribute("aria-expanded", "true");
  await painted(c.locator(`#changes-all .cf[data-path="notes/untracked.md"]`));
  await page.screenshot({ path: shot("changes-after-reload.png") });
  await c.locator(`#changes-scoped .cf[data-path="src/sample.py"]`).click();
  await expect(activeTab()).toContainText("src/sample.py (uncommitted)", { timeout: 15_000 });
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "value_99 = 99" }).first()).toBeVisible();
  await c.locator("#changes-open-all").click();
  await expect(activeTab()).toContainText("Uncommitted changes — all seats", { timeout: 15_000 });
  await expect(page.locator(".view-line", { hasText: "scratch" }).first()).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: shot("changes-multi-diff.png") });
  // committing it empties the tab again
  g(["add", "-A"]);
  commit("wip", "chore: wip, no ticket", undefined, Math.floor(Date.now() / 1000));
  await expect(c.locator("#changes-summary")).toHaveText("The shared tree is clean", { timeout: 10_000 });
  await expect(c.locator("#tab-changes .tab-badge")).toHaveCount(0);
});

test("C14: the Changes tab follows the scope picker: epic → story → epic changes the first group's title, rows and badge; the epic's other files fold into All seats", async () => {
  const c = chat();
  // an anchor on Story Beta's thread: the epic's file, never Story Alpha's (C14: anchors per thread)
  const snippet = "beta = 1";
  await call("POST", "/v1/messages", { ticket_id: storyB, kind: "note", text: "beta anchor",
    code_context: { repo_root: repo, path: "notes/beta.md", line_start: 1, line_end: 1, commit: null, dirty: true, snippet,
      snippet_sha: createHash("sha256").update(snippet).digest("hex") } }, { "X-Participant": "arch" });
  write("src/sample.py", fs.readFileSync(path.join(repo, "src/sample.py"), "utf8") + "value_c14 = 14\n"); // Story Alpha's commit
  write("src/task.py", "task = 14\n"); // Story Alpha's task's commit
  write("src/epic.py", "epic = 14\n"); // the epic's own commit
  write("notes/beta.md", "beta = 1\n"); // anchored on Story Beta's thread
  write("notes/nobody.md", "nobody\n"); // no ticket touched it
  const scoped = async (title: string, rows: string[], badge: string, more: string) => {
    await expect(c.locator("#changes-scoped-toggle")).toContainText(title, { timeout: 15_000 });
    await expect(c.locator("#changes-scoped .cf")).toHaveCount(rows.length, { timeout: 15_000 });
    expect(await c.locator("#changes-scoped .cf").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.path))).toEqual(rows);
    await expect(c.locator("#tab-changes .tab-badge")).toHaveText(badge);
    await expect(c.locator("#changes-all-toggle")).toContainText(`All seats${more} more`);
    await expect(c.locator("#changes-all-toggle")).toHaveAttribute("aria-expanded", "false");
  };
  // a sibling story's live message event carries no code_context: its anchor is read when a thread of
  // the epic is (re)opened, so start from Story Alpha, then epic → story → epic
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
  // epic: the whole tree
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await tab("changes");
  if ((await c.locator("#changes-all-toggle").getAttribute("aria-expanded")) === "true") await c.locator("#changes-all-toggle").click();
  await scoped("This epic", ["notes/beta.md", "src/epic.py", "src/sample.py", "src/task.py"], "4", "1");
  await page.screenshot({ path: shot("c14-epic-scope.png") });
  // story: only Story Alpha and its task; the epic's and Story Beta's files count in All seats
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
  await expect(c.locator("#tab-changes")).toHaveAttribute("aria-selected", "true");
  await scoped("This story", ["src/sample.py", "src/task.py"], "2", "3");
  await expect(c.locator("#tab-changes")).toHaveAttribute("aria-label", "Changes, 2 files this story touched, 5 files uncommitted across all seats");
  await page.screenshot({ path: shot("c14-story-scope.png") });
  await c.locator("#changes-all-toggle").click();
  await expect(c.locator("#changes-all .cf")).toHaveCount(3);
  expect(await c.locator("#changes-all .cf").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.path))).toEqual(["notes/beta.md", "notes/nobody.md", "src/epic.py"]);
  await c.locator("#changes-all-toggle").click();
  // back to the epic
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await scoped("This epic", ["notes/beta.md", "src/epic.py", "src/sample.py", "src/task.py"], "4", "1");
  await page.screenshot({ path: shot("c14-epic-again.png") });
  g(["add", "-A"]);
  commit("c14", "chore: c14 wip, no ticket", undefined, Math.floor(Date.now() / 1000));
  await expect(c.locator("#changes-summary")).toHaveText("The shared tree is clean", { timeout: 10_000 });
});

test("the webview never gets git or board access: no fetch or X-Token in the bundle", async () => {
  const js = fs.readFileSync(path.join(path.dirname(VSIX), "dist", "webview.js"), "utf8");
  expect(js).not.toMatch(/X-Token|EDP8_TOKEN|fetch\(|XMLHttpRequest|WebSocket/);
});

