// C3 chat smoke (s-b00dbbcdea; strategyll-86c5b5068f §4): the EDP chat view in a REAL code-server,
// against this file's own e2e board (never :9400) through a loopback TCP proxy the spec can cut to drop
// the feed. Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox through
// Playwright's moz-firefox channel (never Playwright's patched firefox: it false-fails webviews,
// m-5dcb142053). Run one browser at a time.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { freePort, folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c3-owner-tok-5b1d9e7a44";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-chat", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-chat", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let repo = "";
let cs: CodeServer | null = null;
let page: Page;
let storyA = "", storyB = "", otherEpic = "";
const ARCH = () => `architect.${EPIC()}`;
const ENG = () => `engineer.${storyA}`;
const ARCH2 = () => `architect.${otherEpic}`;

// -- board ----------------------------------------------------------------------------------------
async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const agentTok = (id: string) => `c3-agent-${id.replace(/\W/g, "")}`;
const asAgent = (id: string) => ({ "X-Participant": id, "X-Token": agentTok(id) });
const say = (ticket: string, text: string, by: Record<string, string>, extra: Record<string, unknown> = {}) =>
  call("POST", "/v1/messages", { ticket_id: ticket, kind: "note", text, ...extra }, by);

// -- the proxy the extension talks to (edp.boardUrl): cut() drops every connection and refuses new ones
let proxy: net.Server | null = null;
let proxyPort = 0;
const socks = new Set<net.Socket>();
function listen(): Promise<void> {
  const target = Number(new URL(BASE()).port);
  proxy = net.createServer(c => {
    const up = net.connect(target, "127.0.0.1");
    socks.add(c); socks.add(up);
    const drop = () => { c.destroy(); up.destroy(); socks.delete(c); socks.delete(up); };
    c.on("error", drop); up.on("error", drop); c.on("close", drop); up.on("close", drop);
    c.pipe(up); up.pipe(c);
  });
  return new Promise(r => proxy!.listen(proxyPort, "127.0.0.1", () => r()));
}
async function cut(): Promise<void> {
  // server.close() waits for open connections: stop accepting, destroy them, then await the close
  const closing = new Promise<void>(r => (proxy ? proxy.close(() => r()) : r()));
  proxy = null;
  for (const s of socks) s.destroy();
  socks.clear();
  await closing;
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
/** The chat webview's document: two iframes deep. The workbench overlays webview iframes outside the
 *  part that hosts them; ours is the only webview this window opens. */
const chat = (): FrameLocator => page.locator("iframe.webview").first().contentFrame().locator("#active-frame").contentFrame();
/** C9: stories live in the header's Stories dropdown; open it, then click the story. */
async function openStory(id: string): Promise<void> {
  const c = chat();
  if ((await c.locator("#stories-toggle").getAttribute("aria-expanded")) !== "true") await c.locator("#stories-toggle").click();
  await c.locator(`.story[data-id="${id}"]`).click();
}
const shot = (name: string) => { fs.mkdirSync(EVIDENCE, { recursive: true }); return path.join(EVIDENCE, name); };

function makeRepo(): void {
  repo = path.join(tmp, "fixture-repo");
  fs.mkdirSync(path.join(repo, "src"), { recursive: true });
  fs.writeFileSync(path.join(repo, "src", "sample.py"), Array.from({ length: 25 }, (_, i) => `value_${i + 1} = ${i + 1}  # line ${i + 1}`).join("\n") + "\n");
  const g = (a: string[]) => execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", ...a], { cwd: repo });
  g(["init", "-q", "-b", "main"]); g(["add", "src/sample.py"]); g(["commit", "-q", "-m", "fixture"]);
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c3-"));
  // seed while the board is still trusted, then switch it to token mode
  const arch = { "X-Participant": "arch" };
  storyA = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Alpha", parent_id: EPIC() }, arch)).id;
  storyB = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Story Beta", parent_id: EPIC() }, arch)).id;
  otherEpic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Other epic" }, { "X-Participant": "owner" })).id;
  for (const [id, role, t] of [[ARCH(), "architect", EPIC()], [ENG(), "engineer", storyA], [ARCH2(), "architect", otherEpic]]) {
    await call("POST", "/v1/participants", { type: "agent", role, handle: id, id });
    await call("PUT", `/v1/sessions/sess-${id.replace(/\W/g, "-")}`, { participant_id: id, ticket_id: t, pool_id: "e2e", state: "alive" });
  }
  await say(EPIC(), "Epic kickoff: welcome to the epic thread", asAgent(ARCH()));
  const snippet = ["value_3 = 3  # line 3", "value_4 = 4  # line 4", "value_5 = 5  # line 5"].join("\n");
  const { createHash } = await import("node:crypto");
  makeRepo();
  const head = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
  await say(EPIC(), "look at these lines", asAgent(ARCH()), { code_context: {
    repo_root: repo.replace(/^([a-z]):/, (_, d: string) => d.toUpperCase() + ":"), path: "src/sample.py", line_start: 3, line_end: 5,
    commit: head, dirty: false, snippet, snippet_sha: createHash("sha256").update(snippet, "utf8").digest("hex") } });
  await say(EPIC(), "hostile <img src=x onerror=\"document.title='pwned'\"> and <script>document.title='pwned2'</script> end", asAgent(ARCH()));
  await say(storyA, "Alpha story only message", asAgent(ENG()));
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN, [ARCH()]: agentTok(ARCH()), [ENG()]: agentTok(ENG()), [ARCH2()]: agentTok(ARCH2()) }));
  await call("GET", "/v1/participants/owner", undefined, asOwner);
  proxyPort = await freePort();
  await listen();
  cs = await startCodeServer(tmp, { "edp.boardUrl": `http://127.0.0.1:${proxyPort}`, "edp.sharedTreePaths": [repo] });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first()).toBeVisible({ timeout: 60_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  await cut();
  if (tmp && !process.env.C3_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("sign in, open the chat in the right column, pick the epic: its own thread, one-line header with the Stories dropdown, architect", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await expect(quickRow(page, "Spike epic")).toBeVisible({ timeout: 15_000 });
  await quickRow(page, "Spike epic").click();
  const c = chat();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 20_000 });
  await expect(c.locator("#architect")).toHaveText(`@${ARCH()}`);
  await expect(c.locator("#architect")).toHaveAttribute("title", `Architect: @${ARCH()}`);
  await expect(c.locator("#ticket-status")).toHaveText("drafted");
  await expect(c.locator("#feed-status")).toHaveText("live", { timeout: 15_000 });
  await expect(c.locator(".msg .body", { hasText: "Epic kickoff" })).toBeVisible();
  await expect(c.locator(".story")).toHaveCount(2);
  await expect(c.locator(`.story[data-id="${storyA}"]`)).toContainText("Story Alpha");
  await expect(c.locator(`.story[data-id="${storyA}"]`)).toContainText("drafted");
  await expect(c.locator(`.story[data-id="${storyA}"] .st-unread`)).toHaveText("1"); // never viewed: its one message
  await expect(c.locator(`.story[data-id="${storyB}"] .st-unread`)).toHaveCount(0);
  await expect(c.locator(".msg .body", { hasText: "Alpha story only" })).toHaveCount(0); // never merged
  // C9: the header is one line; the stories fold into a dropdown that reaches every story
  const hb = await c.locator("header.hdr").boundingBox();
  const pb = await c.locator("#pick").boundingBox();
  expect(hb!.height).toBeLessThan(pb!.height * 1.6);
  for (const id of ["#crumb-current", "#ticket-status", "#architect", "#stories-toggle", "#feed-status"]) {
    const b = await c.locator(id).boundingBox();
    if (!b) continue; // a narrow panel folds status and architect into the picker's tooltip (checked below)
    expect(Math.abs(b.y + b.height / 2 - (pb!.y + pb!.height / 2)), id).toBeLessThan(4);
  }
  await expect(c.locator("#pick")).toHaveAttribute("title", new RegExp(`drafted · architect @${ARCH().replace(/[.]/g, "\.")}`));
  await expect(c.locator("#stories")).toBeHidden();
  await expect(c.locator("#stories-toggle .st-unread")).toHaveText("1");
  // C13: the chips gave way to a tab bar under the header; Chat is the default tab
  await expect(c.locator("[role=tablist] [role=tab]")).toHaveText([/^Chat/, /^Changes/, /^Commits/]);
  await expect(c.locator("#tab-chat")).toHaveAttribute("aria-selected", "true");
  await expect(c.locator("#uncommitted-toggle")).toHaveCount(0);
  await c.locator("#stories-toggle").click();
  await expect(c.locator("#stories .story")).toHaveCount(2);
  await expect(c.locator("#stories .story").nth(0)).toBeVisible();
  await expect(c.locator("#stories .story").nth(1)).toBeVisible();
  await page.screenshot({ path: shot("stories-dropdown.png") });
  await page.keyboard.press("Escape");
  await expect(c.locator("#stories")).toBeHidden();
  // keyboard: Enter on the toggle opens it on the first story, arrows move, Tab out closes it
  await c.locator("#stories-toggle").focus();
  await page.keyboard.press("Enter");
  await expect(c.locator("#stories .story").nth(0)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(c.locator("#stories .story").nth(1)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(c.locator("#stories")).toBeHidden();
  // right-hand column: the auxiliary bar sits right of the editor
  const aux = await page.locator(".part.auxiliarybar").boundingBox();
  const ed = await page.locator(".part.editor").boundingBox();
  expect(aux!.x).toBeGreaterThanOrEqual(ed!.x + ed!.width - 2);
  await page.screenshot({ path: shot("epic-thread.png") });
});

test("a message posted from outside the panel appears within 5 s; a story message only bumps its strip count", async () => {
  const c = chat();
  const t0 = Date.now();
  await say(EPIC(), "live from REST at the epic", asAgent(ARCH()));
  await expect(c.locator(".msg .body", { hasText: "live from REST at the epic" })).toBeVisible({ timeout: 5_000 });
  const ms = Date.now() - t0;
  await say(storyA, "second alpha message", asAgent(ENG()));
  await expect(c.locator(`.story[data-id="${storyA}"] .st-unread`)).toHaveText("2", { timeout: 5_000 });
  await expect(c.locator(".msg .body", { hasText: "second alpha message" })).toHaveCount(0);
  fs.writeFileSync(shot("live-latency.json"), JSON.stringify({ rest_post_to_visible_ms: ms }, null, 1));
});

test("clicking a story opens its separate thread; the breadcrumb returns to the epic", async () => {
  const c = chat();
  await openStory(storyA);
  await expect(c.locator("#crumb-current")).toHaveText("Story Alpha", { timeout: 15_000 });
  await expect(c.locator("#crumb-epic")).toHaveText("Spike epic");
  await expect(c.locator("#stories")).toBeHidden(); // picking closes the dropdown
  await expect(c.locator(".msg .body", { hasText: "Alpha story only message" })).toBeVisible();
  await expect(c.locator(".msg .body", { hasText: "Epic kickoff" })).toHaveCount(0);
  await expect(c.locator(`.story[data-id="${storyA}"] .st-unread`)).toHaveCount(0);
  await page.screenshot({ path: shot("story-thread.png") });
  await c.locator("#crumb-epic").click();
  await expect(c.locator("#crumb-current")).toHaveText("Spike epic", { timeout: 15_000 });
  await expect(c.locator(".msg .body", { hasText: "Epic kickoff" })).toBeVisible();
  await expect(c.locator(".msg .body", { hasText: "Alpha story only message" })).toHaveCount(0);
});

test("a message with <img onerror> and <script> renders as inert text", async () => {
  const c = chat();
  const body = c.locator(".msg .body", { hasText: "hostile" });
  await expect(body).toBeVisible();
  await expect(body).toContainText("<img src=x onerror=");
  await expect(body).toContainText("<script>document.title='pwned2'</script>");
  await expect(c.locator(".msg img, .msg script")).toHaveCount(0);
  await expect(c.locator("title")).not.toHaveText(/pwned/);
});

test("clicking a code card opens the file at line_start..line_end", async () => {
  const c = chat();
  const card = c.locator(".code-card", { hasText: "src/sample.py:L3-5" });
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.locator(".tab.active", { hasText: "sample.py" })).toBeVisible({ timeout: 15_000 });
  // the selection runs from line 3 col 1 to the end of line 5: the cursor sits on line 5 with 3 lines selected
  await expect(page.locator(".statusbar-item", { hasText: /Ln 5, Col \d+ \(\d+ selected\)/ })).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".monaco-editor .view-line", { hasText: "value_3 = 3" }).first()).toBeVisible();
  await page.screenshot({ path: shot("code-card-opened.png") });
});

test("the composer starts at 2 lines, grows with its text to 8, then scrolls; kind and To sit in its toolbar", async () => {
  const c = chat();
  const ta = c.locator("#composer");
  const lineH = await ta.evaluate(e => parseFloat(getComputedStyle(e).lineHeight));
  const pad = await ta.evaluate(e => parseFloat(getComputedStyle(e).paddingTop) + parseFloat(getComputedStyle(e).paddingBottom));
  const h = async () => (await ta.boundingBox())!.height;
  expect(Math.abs(await h() - (2 * lineH + pad))).toBeLessThan(3);
  // kind and To are in the composer's toolbar, on the Send button's line
  const send = (await c.locator("#send").boundingBox())!;
  for (const id of ["#kind", "#to"]) {
    const b = (await c.locator(id).boundingBox())!;
    expect(Math.abs(b.y + b.height / 2 - (send.y + send.height / 2)), id).toBeLessThan(4);
  }
  await expect(c.locator(".ctools #composer-tools")).toHaveCount(1); // the C11/C12 slot
  await ta.click();
  for (let i = 1; i <= 5; i++) { await ta.pressSequentially(`line ${i}`); await page.keyboard.press("Shift+Enter"); }
  await ta.pressSequentially("line 6");
  expect(Math.abs(await h() - (6 * lineH + pad))).toBeLessThan(3);
  for (let i = 7; i <= 12; i++) { await page.keyboard.press("Shift+Enter"); await ta.pressSequentially(`line ${i}`); }
  expect(Math.abs(await h() - (8 * lineH + pad))).toBeLessThan(3);
  expect(await ta.evaluate(e => getComputedStyle(e).overflowY)).toBe("auto");
  await page.screenshot({ path: shot("composer-8-lines.png") });
  await ta.fill("");
  await ta.press("a");
  await ta.press("Backspace");
  expect(Math.abs(await h() - (2 * lineH + pad))).toBeLessThan(3);
});

test("@-autocomplete shows role · ticket · title, ranks this epic first; two chosen mentions land in the event", async () => {
  const c = chat();
  const ta = c.locator("#composer");
  await ta.click();
  await ta.pressSequentially("please check @architect");
  const opts = c.locator("#people [role=option]");
  await expect(opts.first()).toBeVisible();
  await expect(opts).toHaveCount(2);
  await expect(opts.nth(0)).toContainText(`@${ARCH()}`);
  await expect(opts.nth(0)).toContainText(`architect · ${EPIC()} · Spike epic`);
  await expect(opts.nth(1)).toContainText(`architect · ${otherEpic} · Other epic`);
  await expect(ta).toHaveAttribute("aria-activedescendant", "p-0");
  await page.screenshot({ path: shot("autocomplete-architect.png") });
  await page.keyboard.press("Enter"); // accepts, does not send
  await ta.pressSequentially("and @");
  await expect(opts.first()).toBeVisible();
  // this epic's seats (epic + its stories) rank before humans and other seats
  await expect(opts.nth(0)).toContainText(`@${ARCH()}`);
  await expect(opts.nth(1)).toContainText(`@${ENG()}`);
  await expect(opts.nth(2)).toContainText("human"); // then humans (the viewer, owner, is not listed)
  await ta.pressSequentially("eng");
  await expect(opts.nth(0)).toContainText(`@${ENG()}`);
  await expect(opts.nth(0)).toContainText(`engineer · ${storyA} · Story Alpha`);
  await page.keyboard.press("Tab");
  await ta.pressSequentially("thanks");
  await expect(ta).toHaveValue(`please check @${ARCH()} and @${ENG()} thanks`);
  // C14 (owner m-db09472a68): the board UI's chord. The hint names it; a plain Enter is a newline, never a send
  await expect(ta).toHaveAttribute("placeholder", /· Ctrl\+Enter to send$/);
  await page.keyboard.press("Enter");
  await expect(ta).toHaveValue(`please check @${ARCH()} and @${ENG()} thanks\n`);
  await ta.pressSequentially("second line");
  await expect(ta).toHaveValue(`please check @${ARCH()} and @${ENG()} thanks\nsecond line`);
  await page.waitForTimeout(1_000);
  expect((await call("GET", `/v1/tickets/${EPIC()}/thread`, undefined, asOwner)).thread.some((m: any) => m.text.startsWith("please check"))).toBe(false);
  await page.keyboard.press("Control+Enter");
  await expect(ta).toHaveValue("", { timeout: 10_000 });
  let msg: any;
  await expect.poll(async () => {
    const rows = (await call("GET", `/v1/tickets/${EPIC()}/thread`, undefined, asOwner)).thread;
    msg = rows.find((m: any) => m.text === `please check @${ARCH()} and @${ENG()} thanks\nsecond line`);
    return !!msg;
  }, { timeout: 10_000 }).toBe(true);
  expect(msg.by).toBe("owner");
  const evs = await call("GET", `/v1/events?subject_id=${EPIC()}&limit=500`, undefined, asOwner);
  const ev = evs.find((e: any) => e.kind === "message_sent" && e.data?.message === msg.id);
  expect(ev.data.mentions).toEqual(expect.arrayContaining([ARCH(), ENG()]));
  await expect(c.locator(".msg .body", { hasText: "thanks" })).toHaveCount(1); // echoed once, feed dedupes
  fs.writeFileSync(shot("mention-event.json"), JSON.stringify({ message: msg.id, mentions: ev.data.mentions }, null, 1));
});

test("after the feed drops and returns, the missed messages appear once, no duplicates", async () => {
  const c = chat();
  await cut();
  await expect(c.locator("#feed-status")).not.toHaveText("live", { timeout: 60_000 });
  await say(EPIC(), "missed while down 1", asAgent(ARCH()));
  await say(EPIC(), "missed while down 2", asAgent(ARCH()));
  await listen();
  await expect(c.locator(".msg .body", { hasText: "missed while down 2" })).toBeVisible({ timeout: 60_000 });
  await expect(c.locator(".msg .body", { hasText: "missed while down 1" })).toHaveCount(1);
  await expect(c.locator(".msg .body", { hasText: "missed while down 2" })).toHaveCount(1);
  await say(EPIC(), "after recovery", asAgent(ARCH()));
  await expect(c.locator(".msg .body", { hasText: "after recovery" })).toBeVisible({ timeout: 35_000 });
  const ids = await c.locator(".msg").evaluateAll(els => els.map(e => (e as HTMLElement).dataset.id));
  expect(new Set(ids).size).toBe(ids.length);
  await page.screenshot({ path: shot("after-feed-drop.png") });
});

test("a failed send keeps the draft", async () => {
  const c = chat();
  const ta = c.locator("#composer");
  await cut(); // the board is unreachable: the POST fails
  await ta.click();
  await ta.pressSequentially("this must survive a failed send");
  await page.keyboard.press("Control+Enter");
  await expect(c.locator("#send-error")).toContainText("Not sent", { timeout: 20_000 });
  await expect(ta).toHaveValue("this must survive a failed send");
  await page.screenshot({ path: shot("send-failed-draft-kept.png") });
  await listen();
});
