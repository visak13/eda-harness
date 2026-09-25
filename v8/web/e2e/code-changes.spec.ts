// C5 change-card smoke (s-ab8e69650e; strategyll-86c5b5068f §4): commits in the EDP chat timeline opening
// VS Code's diff and multi-diff, live on a new commit, and the pinned "Uncommitted changes — all seats"
// card, in a REAL code-server against this file's own e2e board (never :9400/:9410). The workspace is a
// throwaway git repo built here, so every commit, trailer and file status is what git itself records.
// Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox (moz-firefox channel,
// m-5dcb142053). Run one browser at a time.
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
const OWNER_TOKEN = "c5-owner-tok-3c9e1a7d52";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-changes", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-changes", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let repo = "";
let cs: CodeServer | null = null;
let page: Page;
let storyA = "", taskA = "", storyB = "";
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
const asAgent = (id: string) => ({ "X-Participant": id, "X-Token": agentTok(id) });

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
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };
/** C9: stories live in the header's Stories dropdown; open it, then click the story. */
async function openStory(id: string): Promise<void> {
  const c = chat();
  if ((await c.locator("#stories-toggle").getAttribute("aria-expanded")) !== "true") await c.locator("#stories-toggle").click();
  await c.locator(`.story[data-id="${id}"]`).click();
}
const card = (key: string) => chat().locator(`#timeline .commit[data-sha="${sha[key]}"]`);
const activeTab = () => page.locator(".tabs-container .tab.active");

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c5-"));
  const arch = { "X-Participant": "arch" };
  storyA = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Alpha", parent_id: EPIC() }, arch)).id;
  storyB = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Beta", parent_id: EPIC() }, arch)).id;
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: ENG(), id: ENG() });
  taskA = (await call("POST", "/v1/tickets", { kind: "task", work_type: "feature", title: "Alpha task", parent_id: storyA, assignee: ENG() }, arch)).id;
  await call("POST", "/v1/messages", { ticket_id: storyA, kind: "note", text: "Alpha thread message, newer than every fixture commit" }, { "X-Participant": ENG() });
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

test("the epic thread: only epic-named commits, the Stories strip counts, unlinked commits collapsed", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await quickRow(page, "Spike epic").click();
  const c = chat();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  await expect(card("epic")).toBeVisible({ timeout: 20_000 });
  await expect(card("epic").locator(".cm-seat")).toHaveText(`architect.${EPIC()}`);
  // a story's commits never show in the epic thread (m-2e3b14065e): only its strip count
  await expect(card("alpha")).toHaveCount(0);
  await expect(card("task")).toHaveCount(0);
  await expect(c.locator(`.story[data-id="${storyA}"] .st-commits`)).toHaveText("⎇ 2");
  await expect(c.locator(`.story[data-id="${storyB}"] .st-commits`)).toHaveCount(0);
  // C9: Unlinked is a chip, collapsed by default, expanding in place
  await expect(c.locator("#unlinked")).toBeHidden();
  await expect(c.locator("#unlinked-toggle")).toHaveText("Unlinked · 2");
  await expect(c.locator("#unlinked-toggle")).toHaveAttribute("aria-expanded", "false");
  await c.locator("#unlinked-toggle").click();
  await expect(c.locator("#unlinked-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(c.locator(`#unlinked .commit[data-sha="${sha.unlinked}"] .cm-seat`)).toHaveText("unlinked");
  await expect(c.locator(`#unlinked .commit[data-sha="${sha.root}"]`)).toBeVisible();
  await page.screenshot({ path: shot("epic-thread.png") });
  await c.locator("#unlinked-toggle").click();
  await expect(c.locator("#unlinked")).toBeHidden();
});

test("the story thread: trailer and subject-attributed cards with seat, subject, sha7, files ±, in time order", async () => {
  const c = chat();
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
  const a = card("alpha");
  await expect(a).toBeVisible();
  await expect(a.locator(".cm-seat")).toHaveText(ENG());
  await expect(a.locator(".cm-sha")).toHaveText(sha.alpha.slice(0, 7));
  await expect(a.locator(".cm-subject")).toHaveText("feat: alpha work");
  await expect(a.locator(".cf")).toHaveText(["Adocs/alpha.md+2−0", "Msrc/sample.py+1−2"]);
  // the task's commit carries its id in the subject only: seat = the task's assignee, labelled
  await expect(card("task").locator(".cm-seat")).toHaveText(`${ENG()} (assignee)`);
  await expect(c.locator("#unlinked")).toBeHidden();
  // cards interleave with messages by time: both fixture commits are older than the thread message
  const order = await c.locator("#timeline .items > *").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.sha ?? (e as HTMLElement).dataset.id ?? e.className));
  const iMsg = order.findIndex(x => typeof x === "string" && x.startsWith("m-"));
  expect(order.indexOf(sha.alpha)).toBeLessThan(iMsg);
  expect(order.indexOf(sha.task)).toBeGreaterThan(order.indexOf(sha.alpha));
  await page.screenshot({ path: shot("story-thread-cards.png") });
});

test("a file row opens the side-by-side diff (added file against an empty side); the card opens the multi-diff", async () => {
  const c = chat();
  await card("alpha").locator(`.cf[data-path="src/sample.py"]`).click();
  await expect(page.locator(".monaco-diff-editor").first()).toBeVisible({ timeout: 15_000 });
  await expect(activeTab()).toContainText(`src/sample.py (${sha.alpha.slice(0, 7)})`);
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "value_3 = 33" }).first()).toBeVisible();
  await page.screenshot({ path: shot("file-diff-modified.png") });
  await card("alpha").locator(`.cf[data-path="docs/alpha.md"]`).click();
  await expect(activeTab()).toContainText(`docs/alpha.md (${sha.alpha.slice(0, 7)})`, { timeout: 15_000 });
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "new doc" }).first()).toBeVisible();
  await expect(page.locator(".notifications-toasts .notification-toast", { hasText: /Unable to resolve|FileNotFound|nonexistent/i })).toHaveCount(0);
  await page.screenshot({ path: shot("file-diff-added.png") });
  await card("alpha").locator(".cm-head").click();
  await expect(activeTab()).toContainText(`${sha.alpha.slice(0, 7)} feat: alpha work`, { timeout: 15_000 });
  await expect(page.locator(".view-line", { hasText: "value_3 = 33" }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".view-line", { hasText: "new doc" }).first()).toBeVisible();
  await page.screenshot({ path: shot("card-multi-diff.png") });
});

test("the epic's rename + delete commit opens without errors (old path on the left, deleted side empty)", async () => {
  const c = chat();
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await c.locator("#unlinked-toggle").click();
  const u = c.locator(`#unlinked .commit[data-sha="${sha.unlinked}"]`);
  await expect(u.locator(".cf")).toHaveText(["Ddocs/gone.md+0−1", "Rsrc/old_name.py → src/new_name.py+0−0"]);
  await u.locator(".cm-head").click();
  await expect(activeTab()).toContainText(`${sha.unlinked.slice(0, 7)} chore: rename and delete, no ticket`, { timeout: 15_000 });
  await u.locator(`.cf[data-path="docs/gone.md"]`).click();
  await expect(activeTab()).toContainText(`docs/gone.md (${sha.unlinked.slice(0, 7)})`, { timeout: 15_000 });
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "to be deleted" }).first()).toBeVisible();
  await expect(page.locator(".notifications-toasts .notification-toast", { hasText: /Unable to resolve|FileNotFound|nonexistent/i })).toHaveCount(0);
  await c.locator("#unlinked-toggle").click();
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
});

test("a new commit naming the open story appears as a card within 10 s, no reload; the strip count follows", async () => {
  const c = chat();
  write("src/live.py", "live = 1\n");
  g(["add", "src/live.py"]);
  const t0 = Date.now();
  commit("live", "feat: live commit", `EDP-Ticket: ${storyA}\nEDP-Seat: ${ENG()}`, Math.floor(Date.now() / 1000));
  await expect(card("live")).toBeVisible({ timeout: 10_000 });
  timing.commit_to_card_ms = Date.now() - t0;
  await expect(card("live").locator(".cf")).toHaveText(["Asrc/live.py+1−0"]);
  await expect(c.locator(`.story[data-id="${storyA}"] .st-commits`)).toHaveText("⎇ 3");
  // appended at the bottom: newer than the thread message
  const last = await c.locator("#timeline .items > *").last().getAttribute("data-sha");
  expect(last).toBe(sha.live);
  await page.screenshot({ path: shot("live-commit-card.png") });
});

test("the Uncommitted chip: collapsed, clean, then scoped to this epic's files with a show-all toggle; opens diffs; names no seat; the fold survives a reload", async () => {
  const c = chat();
  await expect(c.locator("#uncommitted-toggle")).toHaveText("Uncommitted · clean", { timeout: 15_000 });
  await expect(c.locator("#uncommitted")).toBeHidden();
  await c.locator("#uncommitted-toggle").click();
  await expect(c.locator("#uncommitted-open")).toContainText("clean");
  const t0 = Date.now();
  write("src/sample.py", fs.readFileSync(path.join(repo, "src/sample.py"), "utf8") + "value_99 = 99\n");
  write("notes/untracked.md", "scratch\n");
  await expect(c.locator(`#uncommitted .cf[data-path="src/sample.py"]`)).toBeVisible({ timeout: 5_000 });
  timing.save_to_uncommitted_ms = Date.now() - t0;
  // option (a): src/sample.py is in a commit of this epic's story, notes/untracked.md in none: behind "show all seats"
  await expect(c.locator("#uncommitted-toggle")).toHaveText("Uncommitted · 1/2", { timeout: 5_000 });
  await expect(c.locator(`#uncommitted .cf[data-path="notes/untracked.md"]`)).toHaveCount(0);
  await expect(c.locator("#uncommitted-open")).toContainText("this epic");
  await expect(c.locator("#uncommitted-open")).toContainText("1 file");
  await page.screenshot({ path: shot("uncommitted-epic-only.png") });
  await c.locator("#uncommitted-open").click();
  await expect(activeTab()).toContainText("Uncommitted changes — this epic", { timeout: 15_000 });
  await expect(c.locator("#uncommitted-all")).toHaveText("show all seats (1 more)");
  await c.locator("#uncommitted-all").click();
  await expect(c.locator(`#uncommitted .cf[data-path="notes/untracked.md"]`)).toBeVisible({ timeout: 5_000 });
  await expect(c.locator("#uncommitted-open")).toContainText("2 files");
  // the fold state is the viewer's own (webview state): hiding the side bar disposes the webview, showing it re-resolves it
  await runCommand("View: Toggle Secondary Side Bar Visibility");
  await expect(page.locator(".part.auxiliarybar")).toBeHidden({ timeout: 10_000 });
  await runCommand("View: Toggle Secondary Side Bar Visibility");
  await expect(page.locator(".part.auxiliarybar")).toBeVisible({ timeout: 10_000 });
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 20_000 });
  await expect(c.locator("#uncommitted-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(c.locator("#uncommitted-all")).toHaveAttribute("aria-pressed", "true");
  await expect(c.locator(`#uncommitted .cf[data-path="notes/untracked.md"]`)).toBeVisible({ timeout: 5_000 });
  await expect(c.locator("#uncommitted .cm-seat")).toHaveCount(0);
  await expect(c.locator("#uncommitted")).not.toContainText(ENG());
  await page.screenshot({ path: shot("uncommitted-card.png") });
  await c.locator(`#uncommitted .cf[data-path="src/sample.py"]`).click();
  await expect(activeTab()).toContainText("src/sample.py (uncommitted)", { timeout: 15_000 });
  await expect(page.locator(".monaco-diff-editor .view-line", { hasText: "value_99 = 99" }).first()).toBeVisible();
  await c.locator("#uncommitted-open").click();
  await expect(activeTab()).toContainText("Uncommitted changes — all seats", { timeout: 15_000 });
  await expect(page.locator(".view-line", { hasText: "scratch" }).first()).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: shot("uncommitted-multi-diff.png") });
  // committing it empties the card again
  g(["add", "-A"]);
  commit("wip", "chore: wip, no ticket", undefined, Math.floor(Date.now() / 1000));
  await expect(c.locator("#uncommitted-open")).toContainText("clean", { timeout: 10_000 });
});

test("the webview never gets git or board access: no fetch or X-Token in the bundle", async () => {
  const js = fs.readFileSync(path.join(path.dirname(VSIX), "dist", "webview.js"), "utf8");
  expect(js).not.toMatch(/X-Token|EDP8_TOKEN|fetch\(|XMLHttpRequest|WebSocket/);
});
