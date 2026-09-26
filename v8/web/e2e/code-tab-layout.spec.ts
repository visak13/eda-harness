import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { REPO_DIR } from "./board";

// t-93da8bf09d: the Code tab's editor shows the desktop client's chrome (the File/Edit menu, the activity bar with
// Explorer and Extensions, the status bar), a Zen-stuck workbench is reproduced (zenMode.restore=true kept Zen across
// a reload) and the Code tab's Reset layout brings the chrome back, and with the new default a reload leaves Zen.
// A PRIVATE code service on a spare port (start-code.ps1, its own data dir, the spec board's run dir), never :9410:
// the owner's workbench is never touched. Stock Firefox (the automation Firefox renders no webviews). Run it alone:
//   $env:EDP8_BOARD_CMD="<abs>\v8\.venv\Scripts\edp8-board.exe"; npx playwright test e2e/code-tab-layout.spec.ts

const CODE_PORT = process.env.EDP_CODE_LAYOUT_PORT ?? "9471";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "t93-owner-tok-5c0e2a91d4";
const SHOTS = path.join(REPO_DIR, "web", "e2e", "evidence", "code-tab-layout");
const PS = "powershell.exe";
// the spec board and the private code service share this run dir (code.json: the guard's mint key, user_dir). Pinned:
// a seat shell's EDP8_RUN_DIR is the fleet's, and the board would mint with the fleet guard's key.
const RUN = fs.mkdtempSync(path.join(os.tmpdir(), "t93-run-"));

test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX },
  boardFile: "code-tab-layout", boardEnv: { EDP_CODE_PORT: CODE_PORT, EDP8_RUN_DIR: RUN }, viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 300_000 });

let data = "";
let codeEnv: NodeJS.ProcessEnv = {};
let page: Page;
const log: string[] = [];
const note = (s: string) => { log.push(`${new Date().toISOString()} ${s}`); console.log(s); };

function script(name: string, timeout: number) {
  const r = spawnSync(PS, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(REPO_DIR, "scripts", name)],
    { env: codeEnv, encoding: "utf-8", timeout });
  return { code: r.status, out: `${r.stdout ?? ""}${r.stderr ?? ""}` };
}

function userSetting(key: string, value: unknown): void {
  const f = path.join(data, "user", "User", "settings.json");
  const s = JSON.parse(fs.readFileSync(f, "utf-8").replace(/^\uFEFF/, "")) as Record<string, unknown>;
  s[key] = value;
  fs.writeFileSync(f, JSON.stringify(s, null, 2));
}

const wb = (): FrameLocator => page.frameLocator('[data-testid="code-frame"]');

async function chrome(): Promise<{ menu: boolean; activity: boolean; explorer: boolean; extensions: boolean; status: boolean }> {
  const w = wb();
  const vis = async (sel: string) => (await w.locator(sel).count()) > 0 && w.locator(sel).first().isVisible();
  return {
    menu: await vis('.part.titlebar .menubar [role="menuitem"]:has-text("File")'),
    activity: await vis(".part.activitybar"),
    explorer: await vis('.part.activitybar [aria-label^="Explorer"]'),
    extensions: await vis('.part.activitybar [aria-label^="Extensions"]'),
    status: await vis(".part.statusbar"),
  };
}
const ALL = { menu: true, activity: true, explorer: true, extensions: true, status: true };
// measured: with the seeded classic menu bar the File menu stays in the title bar even in Zen (web keeps the title bar),
// so View > Appearance > Zen Mode is one more way out; the owner's compact menu sat in the activity bar and went with it
const ZEN = { menu: true, activity: false, explorer: false, extensions: false, status: false };

async function openCodeTab(): Promise<void> {
  await page.goto(`/ui/code?as=owner&token=${OWNER_TOKEN}`, { waitUntil: "load" });
  try {
    await expect(wb().locator(".monaco-workbench")).toBeVisible({ timeout: 90_000 });
  } catch (e) {
    const f = page.frames().find(x => x !== page.mainFrame());
    note(`no workbench: frame ${f?.url()} :: ${(await f?.locator("body").innerText().catch(() => "?"))?.slice(0, 400)}`);
    await page.screenshot({ path: path.join(SHOTS, "stockff-fail.png") });
    throw e;
  }
  await expect(wb().locator(".part.editor")).toBeVisible({ timeout: 30_000 });
}

async function zenChord(): Promise<void> {
  await wb().locator(".part.editor").click({ position: { x: 200, y: 200 } });
  await page.keyboard.press("Control+K");
  await page.keyboard.press("Z");
  await page.waitForTimeout(2500);
  note(`after Ctrl+K Z: ${JSON.stringify(await chrome())} zen class: ${await wb().locator(".monaco-workbench").first().getAttribute("class")}`);
}

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const home = process.env.EDP8_E2E_HOME!;
  data = fs.mkdtempSync(path.join(os.tmpdir(), "t93-code-"));
  codeEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^EDP8?_/.test(k)));
  Object.assign(codeEnv, { EDP_CODE_PORT: CODE_PORT, EDP8_RUN_DIR: RUN, EDP_CODE_DATA: data });
  fs.writeFileSync(path.join(home, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN }));
  // the fleet's own user settings turn workspace trust off; in Restricted Mode the edp-code extension (and with it
  // Reset layout) does not activate
  fs.mkdirSync(path.join(data, "user", "User"), { recursive: true });
  fs.writeFileSync(path.join(data, "user", "User", "settings.json"), JSON.stringify({ "security.workspace.trust.enabled": false }));
  const started = script("start-code.ps1", 480_000);
  note(`private code service on :${CODE_PORT}, data ${data}: start-code exit ${started.code}`);
  expect(started.code, started.out).toBe(0);
  expect(started.out).toContain("edp-code installing");
});

test.afterAll(async () => {
  if (codeEnv.EDP_CODE_PORT) { const s = script("stop-code.ps1", 120_000); note(`stop-code exit ${s.code}`); }
  fs.writeFileSync(path.join(SHOTS, "stockff.log"), log.join("\n") + "\n");
});

test("the Code tab's editor shows the menu, activity bar and status bar; Reset layout un-sticks a Zen workbench", async ({ browser }) => {
  page = await browser.newPage();
  note(`browser ${browser.browserType().name()} ${browser.version()}`);

  // 1. the seeded chrome, like the desktop client
  await openCodeTab();
  await expect.poll(chrome, { timeout: 60_000 }).toEqual(ALL);
  note("ok   fresh editor: File menu, activity bar (Explorer, Extensions) and status bar visible");
  await page.screenshot({ path: path.join(SHOTS, "stockff-1-chrome.png") });

  // 2. the reported state, reproduced: Zen (Ctrl+K Z, the chord that also sits under the board's Ctrl+K Find) with
  //    VS Code's own default zenMode.restore=true survives a reload
  userSetting("zenMode.restore", true);
  await page.waitForTimeout(1500);
  await zenChord();
  await expect.poll(chrome, { timeout: 15_000 }).toEqual(ZEN);
  await page.waitForTimeout(5000); // the workbench flushes its layout state to IndexedDB
  await openCodeTab();
  await page.waitForTimeout(6000);
  const after = await chrome();
  note(`after reload with zenMode.restore=true: ${JSON.stringify(after)}`);
  // Zen is restored (no activity bar, so no Explorer or Extensions); measured: the restored Zen may bring the status
  // bar back once the workspace's extensions start, so it is logged, not asserted
  expect({ activity: after.activity, explorer: after.explorer, extensions: after.extensions }).toEqual({ activity: false, explorer: false, extensions: false });
  note("ok   reproduced: Zen + zenMode.restore=true stays Zen after a reload (no activity bar: no Explorer, no Extensions)");
  await page.screenshot({ path: path.join(SHOTS, "stockff-2-zen-stuck-after-reload.png") });

  // 3. Code tab → Reset layout: the extension in the frame leaves Zen and resets the views
  await page.getByTestId("code-reset-layout").click();
  await expect(page.getByTestId("code-reset-result")).toContainText("leaves Zen mode");
  await expect.poll(chrome, { timeout: 20_000 }).toEqual(ALL);
  note("ok   Reset layout: menu, activity bar and status bar are back");
  await page.screenshot({ path: path.join(SHOTS, "stockff-3-after-reset-layout.png") });

  // 4. the new default (zenMode.restore=false): a reload always leaves Zen
  userSetting("zenMode.restore", false);
  await page.waitForTimeout(1500);
  await zenChord();
  await expect.poll(chrome, { timeout: 15_000 }).toEqual(ZEN);
  await openCodeTab();
  await expect.poll(chrome, { timeout: 60_000 }).toEqual(ALL);
  note("ok   zenMode.restore=false: Zen, then a reload, and the chrome is back");
  await page.screenshot({ path: path.join(SHOTS, "stockff-4-reload-leaves-zen.png") });
});
