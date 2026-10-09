// The guide's VS Code shots (s-bcc0c06de7): the same Tidewater thread the web screenshots show, open in the EDP chat
// panel of a REAL code-server beside the code it talks about. Same throwaway pattern as e2e/code-chat.spec.ts: the
// pinned code-server on a spare loopback port with temp user-data and extensions dirs, the freshly built edp-code vsix,
// pointed at this file's own private board; stop() kills only the pid it spawned.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FrameLocator, Page } from "@playwright/test";
import { REPO_DIR } from "../e2e/board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "../e2e/code-server";
import { BASE, expect, test } from "../e2e/fixtures";
import { makeArt } from "./art";
import { MERGE_SNIPPET, seedDemo, type Demo } from "./demo.seed";

const OUT = process.env.GUIDE_OUT ?? path.join(REPO_DIR, "..", "docs", "site", "docs", "assets", "guide");
const MAYA_TOKEN = "guide-maya-tok-0d3c71b2"; // this run's private board only

test.use({ boardFile: "guide-vscode", viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let cs: CodeServer | null = null;
let page: Page;
let demo: Demo;

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
async function shot(name: string): Promise<void> {
  fs.mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

/** A small Tidewater checkout: the file the engineer's quote points at, with the quoted function at line 18. */
function makeRepo(): string {
  const repo = path.join(tmp, "tidewater");
  fs.mkdirSync(path.join(repo, "src", "sync"), { recursive: true });
  const head = [
    "// Paragraph-level merge for offline edits (design §3.1).",
    "",
    "export interface Para {",
    "  id: string;",
    "  text: string;",
    "  deleted?: boolean;",
    "}",
    "",
    "export interface Conflict {",
    "  conflict: true;",
    "  base: Para;",
    "  versions: [Para, Para];",
    "}",
    "",
    "/** Merge one paragraph edited on two devices since `base`. Different edits never overwrite each other:",
    " *  a same-paragraph clash comes back as a Conflict for the writer to pick from. */",
    "",
  ];
  fs.writeFileSync(path.join(repo, "src", "sync", "merge.ts"), [...head, MERGE_SNIPPET, ""].join("\n"));
  return repo;
}

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  demo = await seedDemo(await makeArt());
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "guide-code-"));
  const repo = makeRepo();
  // seeded while the board was trusted; from here on it wants a token, and only maya has one
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ maya: MAYA_TOKEN }));
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE(), "edp.sharedTreePaths": [repo], "workbench.colorTheme": "Default Light Modern" });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(8000); // the extension activates after the workbench
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("the epic thread in VS Code, beside the code", async () => {
  await runCommand("Heronry: Sign in to board");
  await typeInput("maya", "Heronry: board participant id");
  await typeInput(MAYA_TOKEN, "Heronry: token for maya");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as maya" })).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("Control+P");
  await quick(page).locator("input").fill("merge.ts");
  await quickRow(page, "merge.ts").click();
  await expect(page.locator(".editor-instance .view-lines")).toContainText("mergeParagraph", { timeout: 15_000 });
  await runCommand("Heronry: Chat: open a ticket or epic thread…");
  await quickRow(page, "Make Tidewater work offline").click();
  const c = chat();
  await expect(c.locator("#crumb-current")).toHaveText("Make Tidewater work offline", { timeout: 20_000 });
  await expect(c.locator("#feed-status")).toHaveText("live", { timeout: 15_000 });
  await expect(c.locator(".msg .body", { hasText: "Go with (b)" })).toBeVisible();
  // room to read: no explorer, no toast, and the chat column dragged wider
  await runCommand("View: Close Primary Side Bar");
  await runCommand("Notifications: Clear All Notifications");
  const aux = (await page.locator(".part.auxiliarybar").boundingBox())!;
  await page.mouse.move(aux.x - 1, aux.y + aux.height / 2);
  await page.mouse.down();
  await page.mouse.move(aux.x - 340, aux.y + aux.height / 2, { steps: 12 });
  await page.mouse.up();
  await shot("vscode-epic");
});

test("a story's thread: the engineer's status quotes the function open in the editor", async () => {
  const c = chat();
  if ((await c.locator("#stories-toggle").getAttribute("aria-expanded")) !== "true") await c.locator("#stories-toggle").click();
  await c.locator(`.story[data-id="${demo.stories.merge}"]`).click();
  await expect(c.locator(".msg .body", { hasText: "S2's merge is in" })).toBeVisible({ timeout: 15_000 });
  await shot("vscode-story");
});
