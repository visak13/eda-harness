// S5 smoke (s-4741ac0557, strategyll-5ec6802121 §2): the EDP extension in a REAL code-server tags a line
// selection to a human and to a live agent seat, and the board stores the right code_context.
// Isolation: the per-file e2e board (fixtures.ts, temp DB, never :9400) switched to token mode by a
// tokens.json in its temp home; a throwaway code-server on a spare loopback port with temp user-data
// and extensions dirs (never :9410 or v8/.data/code); a fixture git repo in a temp dir. Teardown kills
// only the code-server pid this file spawned (and its tree).
// Before S3's /ui/code lands the smoke drives code-server directly (steer m-ac01681629).
import { execFileSync, spawn, spawnSync, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { createServer } from "node:net";
import os from "node:os";
import path from "node:path";
import type { Page } from "@playwright/test";
import { ADMIN, REPO_DIR } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const OWNER_TOKEN = "s5-owner-tok-7c1f0e2a9b";
const AGENT = "engineer.s5-e2e";
const EXT_DIR = path.join(REPO_DIR, "vscode-ext", "edp-code");
const VSIX = path.join(EXT_DIR, "edp-code.vsix");
const EVIDENCE = path.join(REPO_DIR, "web", "e2e", "evidence", "code-tag");

const lock = JSON.parse(fs.readFileSync(path.join(REPO_DIR, "vscode-ext", "code-server.lock.json"), "utf8"));
const SERVER_DIR = path.join(REPO_DIR, ".tools", "code-server", lock.version, lock.server_dir);
const NODE = path.join(SERVER_DIR, lock.node);

let tmp = "";
let repo = "";
let userDir = "";
let extDir = "";
let csPort = 0;
let cs: ChildProcess | null = null;
let head = "";
let story = "";

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const a = srv.address();
      const port = typeof a === "object" && a ? a.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

/** code-server's env: no seat/board secrets (every EDP_ and EDP8_ variable removed), no gallery. */
function csEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(process.env)) if (!/^EDP8?_/i.test(k)) env[k] = v;
  env.EXTENSIONS_GALLERY = "{}";
  return env;
}

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, {
    method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const asArch = { "X-Participant": "arch" };

function git(args: string[]): string {
  return execFileSync("git", args, { cwd: repo, encoding: "utf8" }).trim();
}

/** Fixture repo: branch main, one commit of src/sample.py (25 lines), plus an untracked notes.txt so
 *  the guarded checkout has a porcelain path to list. */
function makeRepo(): void {
  repo = path.join(tmp, "fixture-repo");
  fs.mkdirSync(path.join(repo, "src"), { recursive: true });
  const lines = Array.from({ length: 25 }, (_, i) => `value_${i + 1} = ${i + 1}  # line ${i + 1}`);
  fs.writeFileSync(path.join(repo, "src", "sample.py"), lines.join("\r\n") + "\r\n");
  git(["init", "-q", "-b", "main"]);
  git(["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "add", "src/sample.py"]);
  git(["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "commit", "-q", "-m", "fixture"]);
  git(["branch", "feature-x"]);
  fs.writeFileSync(path.join(repo, "notes.txt"), "untracked\n");
  head = git(["rev-parse", "HEAD"]);
}

/** A throwaway code-server with the freshly built vsix installed into its OWN extensions dir. */
async function startCodeServer(): Promise<void> {
  userDir = path.join(tmp, "user-data");
  extDir = path.join(tmp, "extensions");
  fs.mkdirSync(path.join(userDir, "User"), { recursive: true });
  fs.mkdirSync(extDir, { recursive: true });
  const settings = JSON.stringify({
    "edp.boardUrl": BASE(),
    "edp.sharedTreePaths": [repo],
    "edp.externalTerminal": { kind: "pwsh", exe: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" },
    "security.workspace.trust.enabled": false,
    "workbench.startupEditor": "none",
    "workbench.tips.enabled": false,
    "telemetry.telemetryLevel": "off",
    "extensions.autoUpdate": false,
    "git.openRepositoryInParentFolders": "never",
  }, null, 1);
  // edp.* settings are machine-scoped: a remote (code-server) window reads them from Machine/settings.json,
  // and a machine setting in User/settings.json is not applied reliably there
  fs.mkdirSync(path.join(userDir, "Machine"), { recursive: true });
  fs.writeFileSync(path.join(userDir, "User", "settings.json"), settings);
  fs.writeFileSync(path.join(userDir, "Machine", "settings.json"), settings);
  const inst = spawnSync(NODE, [SERVER_DIR, "--user-data-dir", userDir, "--extensions-dir", extDir, "--install-extension", VSIX, "--force"],
    { env: csEnv(), encoding: "utf8", timeout: 120_000 });
  if (inst.status !== 0) throw new Error(`vsix install failed (${inst.status}): ${inst.stdout}\n${inst.stderr}`);
  csPort = await freePort();
  cs = spawn(NODE, [SERVER_DIR, "--bind-addr", `127.0.0.1:${csPort}`, "--auth", "none", "--disable-telemetry",
    "--disable-update-check", "--disable-proxy", "--disable-workspace-trust", "--user-data-dir", userDir, "--extensions-dir", extDir],
    { env: csEnv(), stdio: "ignore", windowsHide: true });
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (cs.exitCode !== null) throw new Error(`code-server exited early (${cs.exitCode})`);
    try { if ((await fetch(`http://127.0.0.1:${csPort}/healthz`)).ok) return; } catch { /* not up */ }
    await new Promise(r => setTimeout(r, 300));
  }
  throw new Error("code-server did not answer /healthz within 60 s");
}

function stopCodeServer(): void {
  // our own direct child only; /T takes its extension host, pty host and watcher with it
  if (cs?.pid && cs.exitCode === null) spawnSync("taskkill", ["/PID", String(cs.pid), "/T", "/F"], { stdio: "ignore" });
  cs = null;
}

// -- driving the workbench (selectors from code-server's own e2e model, CodeServer.ts) --------------
const quick = (p: Page) => p.locator(".quick-input-widget");
const quickRow = (p: Page, text: string | RegExp) => quick(p).locator(".monaco-list-row", { hasText: text }).first();

async function runCommand(page: Page, title: string): Promise<void> {
  await page.keyboard.press("F1");
  await expect(quick(page)).toBeVisible();
  await quick(page).locator("input").fill(`>${title}`);
  await quickRow(page, title).click();
}

async function pickQuick(page: Page, text: string | RegExp): Promise<void> {
  await expect(quickRow(page, text)).toBeVisible({ timeout: 15_000 });
  await quickRow(page, text).click();
}

/** Fill the quick input once the box titled `title` is up (the next box reuses the widget, so waiting on
 *  the title keeps a fill from landing in the box that is closing). */
async function typeInput(page: Page, value: string, title?: string | RegExp): Promise<void> {
  if (title) await expect(quick(page).locator(".quick-input-title")).toContainText(title);
  const input = quick(page).locator("input");
  await expect(input).toBeVisible();
  await input.fill("");
  await input.pressSequentially(value); // real key events: the widget's model sees every character
  await expect(input).toHaveValue(value);
  await page.keyboard.press("Enter");
}

async function openFile(page: Page, name: string): Promise<void> {
  await runCommand(page, "Go to File...");
  await quick(page).locator("input").fill(name);
  await pickQuick(page, name);
  await expect(page.locator(".monaco-editor .view-lines").first()).toBeVisible();
}

/** Select whole lines from..to with the keyboard; the selection ends mid-line (Shift+End), not at
 *  column 0 of the next line. */
async function selectLines(page: Page, from: number, to: number): Promise<void> {
  await runCommand(page, "Go to Line/Column...");
  await quick(page).locator("input").fill(`:${from}`);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Home");
  for (let i = from; i < to; i++) await page.keyboard.press("Shift+ArrowDown");
  await page.keyboard.press("Shift+End");
}

const badge = (p: Page) => p.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first();

/** Tag the current selection with the shipped keybinding; returns the board's newest message to `to`. */
async function tag(page: Page, person: string, note: string, kind: string, to: string): Promise<any> {
  await page.keyboard.press("Control+Alt+M");
  await pickQuick(page, person);
  await pickQuick(page, story);
  await typeInput(page, note, "EDP: note to");
  await pickQuick(page, kind);
  let msg: any;
  await expect.poll(async () => {
    const rows = await call("GET", `/v1/messages?ticket_id=${story}&to=${encodeURIComponent(to)}`, undefined, asOwner);
    msg = rows.find((m: any) => m.text.startsWith(note));
    return msg?.code_context ?? null;
  }, { timeout: 20_000 }).not.toBeNull();
  return msg;
}

function shot(name: string): string {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  return path.join(EVIDENCE, name);
}

test.describe.configure({ mode: "serial" });
test.use({ boardFile: "code-tag", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ timeout: 240_000 });

let page: Page;

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-s5-"));
  // seed while the board is still in trusted mode, then switch it to token mode
  await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: AGENT, id: AGENT });
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "S5 e2e story", parent_id: EPIC(), assignee: AGENT }, asArch)).id;
  await call("PUT", `/v1/sessions/sess-s5-${Date.now()}`, { participant_id: AGENT, ticket_id: story, pool_id: "e2e", state: "alive" });
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  await call("GET", "/v1/participants/owner", undefined, asOwner); // token mode is live
  makeRepo();
  await startCodeServer();
  page = await browser.newPage();
  const folder = "/" + repo.replace(/\\/g, "/").replace(/^([A-Z]):/, (_, d: string) => d.toLowerCase() + ":"); // /c:/… (les-ca6209874d)
  await page.goto(`http://127.0.0.1:${csPort}/?folder=${encodeURI(folder)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(badge(page)).toBeVisible({ timeout: 60_000 }); // the extension activated (onStartupFinished)
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  stopCodeServer();
  if (tmp && !process.env.S5_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
  else if (tmp) console.log(`[code-tag] kept ${tmp}`);
});

test("sign in through `EDP: Sign in to board` (token into SecretStorage only)", async () => {
  await runCommand(page, "EDP: Sign in to board");
  await typeInput(page, "owner", "EDP: board participant id");
  await typeInput(page, OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  // the badge now counts from the board: 1 live agent seat (the seeded session)
  await expect(badge(page)).toContainText("main · 1 seats live", { timeout: 20_000 });
});

test("tag lines 10-20 to a human: code_context path, lines, HEAD sha, dirty=false", async () => {
  await openFile(page, "sample.py");
  await selectLines(page, 10, 20);
  const m = await tag(page, "owner", "why is this here?", "question", "owner");
  expect(m.kind).toBe("question");
  expect(m.code_context).toMatchObject({ path: "src/sample.py", line_start: 10, line_end: 20, commit: head, dirty: false });
  expect(m.code_context.repo_root.toLowerCase()).toBe(repo.toLowerCase());
  const want = Array.from({ length: 11 }, (_, i) => `value_${i + 10} = ${i + 10}  # line ${i + 10}`).join("\n");
  expect(m.code_context.snippet).toBe(want); // CRLF file -> LF snippet, full lines
  expect(m.code_context.snippet_sha).toBe(createHash("sha256").update(want, "utf8").digest("hex"));
  expect(m.text).toBe(`why is this here?\n\n\`src/sample.py:L10-20 @${head.slice(0, 7)}\``);
  await page.screenshot({ path: shot("tag-sent-human.png") });
});

test("tag lines 10-20 to an agent seat after an unsaved edit: dirty=true", async () => {
  await runCommand(page, "Go to Line/Column...");
  await quick(page).locator("input").fill(":1");
  await page.keyboard.press("Enter");
  await page.keyboard.press("End");
  await page.keyboard.type("  # unsaved edit");
  await selectLines(page, 10, 20);
  const m = await tag(page, AGENT, "please check this block", "question", AGENT);
  expect(m.to).toBe(AGENT);
  expect(m.code_context).toMatchObject({ path: "src/sample.py", line_start: 10, line_end: 20, commit: head, dirty: true });
  expect(m.text).toContain(`src/sample.py:L10-20 @${head.slice(0, 7)}[dirty]`);
  // the agent's view: the board's inbox for the seat carries it
  const rows = await call("GET", `/v1/messages?to=${encodeURIComponent(AGENT)}`, undefined, asOwner);
  expect(rows.some((r: any) => r.id === m.id)).toBe(true);
});

test("badge: `⎇ main · N seats live` with N = the board's alive agent sessions; click lists the seats", async () => {
  const sessions = await call("GET", "/v1/sessions?state=alive", undefined, asOwner);
  const ps = await call("GET", "/v1/participants", undefined, asOwner);
  const agents = new Set(sessions.filter((s: any) => ps.find((p: any) => p.id === s.participant_id)?.type !== "human").map((s: any) => s.participant_id));
  await expect(badge(page)).toContainText(`main · ${agents.size} seats live`);
  await badge(page).screenshot({ path: shot("badge.png") });
  await page.screenshot({ path: shot("badge-workbench.png") });
  await badge(page).click();
  await expect(quickRow(page, AGENT)).toBeVisible();
  await page.screenshot({ path: shot("badge-seats-list.png") });
  await page.keyboard.press("Escape");
});

test("guarded checkout: the modal lists live seats and porcelain paths before acting; cancel changes nothing", async () => {
  await runCommand(page, "EDP: Checkout… (guarded)");
  await pickQuick(page, "feature-x");
  const dialog = page.locator(".monaco-dialog-box");
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(dialog).toContainText("git checkout feature-x");
  await expect(dialog).toContainText(AGENT);
  await expect(dialog).toContainText("?? notes.txt");
  await expect(dialog).toContainText("built-in Source Control view is not guarded");
  await page.screenshot({ path: shot("guarded-checkout-modal.png") });
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(git(["rev-parse", "--abbrev-ref", "HEAD"])).toBe("main");
});

test("`EDP: Open external terminal here` launches the configured shell detached in the folder", async () => {
  const exe = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";
  const bare = (p: { cmd: string }) => p.cmd.replace(/"/g, "").trim().toLowerCase() === exe.toLowerCase();
  const before = new Set(psList().map(p => p.pid));
  await runCommand(page, "EDP: Open external terminal here");
  let launched: PsRow | undefined;
  await expect.poll(() => {
    launched = psList().find(p => !before.has(p.pid) && bare(p)); // the configured exe with no args, never our probes
    return !!launched;
  }, { timeout: 15_000 }).toBe(true);
  expect(["cmd.exe", ""]).toContain(launched!.parent); // started by `cmd /c start` (which exits at once)
  await new Promise(r => setTimeout(r, 2000));
  fs.writeFileSync(shot("external-terminal-process.json"), JSON.stringify({ ...launched, requested_folder: repo, cwd_checked: false, alive_after_ms: 2000 }, null, 1));
  // it outlived the command (a shell with NUL stdin would already be gone), then close only the shell we opened
  expect(psList().some(p => p.pid === launched!.pid)).toBe(true);
  spawnSync("taskkill", ["/PID", String(launched!.pid), "/T", "/F"], { stdio: "ignore" });
});

test("no token string in the vsix, the user-data (incl. the EDP output channel log) or the extensions dir", async () => {
  const hits: string[] = [];
  const logs: string[] = [];
  const scan = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) scan(p);
      else {
        const buf = fs.readFileSync(p);
        if (buf.includes(OWNER_TOKEN) || buf.includes(Buffer.from(OWNER_TOKEN, "utf16le"))) hits.push(p);
        if (/EDP\.log$/i.test(e.name)) logs.push(p);
      }
    }
  };
  expect(fs.readFileSync(VSIX).includes(OWNER_TOKEN)).toBe(false);
  scan(userDir);
  scan(extDir);
  expect(hits).toEqual([]);
  // the scan covered the channel: it logged the POSTs (method path -> status only)
  const text = logs.map(l => fs.readFileSync(l, "utf8")).join("\n");
  expect(text).toMatch(/POST \/v1\/messages -> 200/);
  fs.writeFileSync(shot("output-channel.log"), text);
});

type PsRow = { pid: number; ppid: number; parent: string; cmd: string };
const HERE = path.join(REPO_DIR, "web", "e2e");
const runPs = (script: string, args: string[] = []) => spawnSync("powershell.exe",
  ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(HERE, script), ...args], { encoding: "utf8" }).stdout ?? "";

/** powershell.exe processes with their parent image (code-tag.pslist.ps1). */
function psList(): PsRow[] {
  return runPs("code-tag.pslist.ps1").split(/\r?\n/).filter(Boolean).map(l => {
    const [pid, ppid, parent, ...c] = l.split("\t");
    return { pid: Number(pid), ppid: Number(ppid), parent, cmd: c.join("\t") };
  });
}

