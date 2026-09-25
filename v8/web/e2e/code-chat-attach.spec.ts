// C12 attachments smoke (s-85dd35a166; design-10b21760d9 §13 row C12): the EDP chat view in a REAL
// code-server against this file's own e2e board (never :9400). A message carrying a PNG shows a
// host-downscaled data: thumbnail that opens full size in an editor tab; a text file shows name + size and
// opens; clip, drop and paste each upload through /v1/artifacts/upload and send with the artifact ids; an
// over-size and a disallowed file are refused with the board's message and the draft is kept; the webview
// makes no request and its CSP is the C9 one (img-src data: only). Browser: Chromium by default;
// CHAT_BROWSER=stockff runs the installed Firefox (moz-firefox channel). One browser at a time.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import type { FrameLocator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { folderParam, startCodeServer, VSIX, type CodeServer } from "./code-server";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const OWNER_TOKEN = "c12-owner-tok-8a41f0c2d9";
const EVIDENCE = path.join(path.dirname(VSIX), "..", "..", "web", "e2e", "evidence", "code-chat-attach", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "code-chat-attach", trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: "serial", timeout: 240_000 });

let tmp = "";
let cs: CodeServer | null = null;
let page: Page;
const ARCH = () => `architect.${EPIC()}`;
const agentTok = (id: string) => `c12-agent-${id.replace(/\W/g, "")}`;
const asOwner = { "X-Participant": "owner", "X-Token": OWNER_TOKEN };
const asArch = () => ({ "X-Participant": ARCH(), "X-Token": agentTok(ARCH()) });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
async function upload(name: string, bytes: Uint8Array, who: Record<string, string>): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([bytes]), name);
  form.append("ticket_id", EPIC());
  const r = await fetch(`${BASE()}/v1/artifacts/upload`, { method: "POST", headers: who, body: form });
  const j = await r.json();
  if (!j.ok) throw new Error(`upload ${name}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value.id;
}

// -- a real PNG, no image library: a 1600x900 gradient with a dark frame (IHDR + one zlib IDAT) ----------
function crc32(b: Buffer): number {
  let c = ~0;
  for (const x of b) { c ^= x; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); }
  return ~c >>> 0;
}
function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function makePng(w: number, h: number): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2; // 8-bit RGB
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) {
    const o = y * (w * 3 + 1);
    for (let x = 0; x < w; x++) {
      const edge = x < 20 || y < 20 || x >= w - 20 || y >= h - 20;
      raw[o + 1 + x * 3] = edge ? 20 : Math.round((x / w) * 255);
      raw[o + 2 + x * 3] = edge ? 20 : Math.round((y / h) * 255);
      raw[o + 3 + x * 3] = edge ? 20 : 180;
    }
  }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}
const PNG_BIG = makePng(1600, 900);
const PNG_SMALL = makePng(120, 80);

// -- workbench ----------------------------------------------------------------------------------------------
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
const record: Record<string, unknown> = {};
const note = (k: string, v: unknown) => { record[k] = v; fs.mkdirSync(EVIDENCE, { recursive: true }); fs.writeFileSync(path.join(EVIDENCE, "attach-evidence.json"), JSON.stringify(record, null, 1)); };

/** The newest owner message on the epic whose text matches, with its artifacts (GET /v1/messages/{id}). */
async function sentWith(text: string | RegExp): Promise<any> {
  let msg: any;
  await expect.poll(async () => {
    const rows = (await call("GET", `/v1/tickets/${EPIC()}/thread`, undefined, asOwner)).thread;
    msg = [...rows].reverse().find((m: any) => m.by === "owner" && (typeof text === "string" ? m.text === text : text.test(m.text)));
    return !!msg;
  }, { timeout: 15_000 }).toBe(true);
  return call("GET", `/v1/messages/${msg.id}`, undefined, asOwner);
}

let pngId = "", txtId = "";

test.beforeAll(async ({ browser, board: _board }) => {
  test.setTimeout(240_000);
  if (!fs.existsSync(VSIX)) throw new Error(`build the vsix first: cd vscode-ext/edp-code && npm run package (${VSIX} missing)`);
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "edp-c12-"));
  await call("POST", "/v1/participants", { type: "agent", role: "architect", handle: ARCH(), id: ARCH() });
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, "tokens.json"), JSON.stringify({ owner: OWNER_TOKEN, [ARCH()]: agentTok(ARCH()) }));
  // an agent posts a screenshot and a notes file on the epic (the board sniffs both)
  pngId = await upload("screen.png", PNG_BIG, asArch());
  txtId = await upload("notes.md", new TextEncoder().encode("# notes\n\nsome text for the reader\n"), asArch());
  await call("POST", "/v1/messages", { ticket_id: EPIC(), kind: "note", text: "here is the screen and my notes", artifacts: [pngId, txtId] }, asArch());
  await call("GET", "/v1/participants/owner", undefined, asOwner);
  const ws = path.join(tmp, "ws");
  fs.mkdirSync(ws);
  fs.writeFileSync(path.join(ws, "README.md"), "c12 fixture\n");
  const g = (a: string[]) => execFileSync("git", ["-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", ...a], { cwd: ws });
  g(["init", "-q", "-b", "main"]); g(["add", "README.md"]); g(["commit", "-q", "-m", "fixture"]);
  // the seats badge (the readiness signal) shows only for a shared-tree folder
  cs = await startCodeServer(tmp, { "edp.boardUrl": BASE(), "edp.sharedTreePaths": [ws] });
  page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(ws)}`);
  await expect(page.locator("div.monaco-workbench")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".statusbar-item", { hasText: /seats (live|\?)/ }).first()).toBeVisible({ timeout: 60_000 });
});

test.afterAll(async () => {
  await page?.close().catch(() => {});
  cs?.stop();
  if (tmp && !process.env.C12_KEEP_TMP) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});

test("a PNG attachment shows a host-downscaled data: thumbnail; a text file shows name + size", async () => {
  await runCommand("EDP: Sign in to board");
  await typeInput("owner", "EDP: board participant id");
  await typeInput(OWNER_TOKEN, "EDP: token for owner");
  await expect(page.locator(".notifications-toasts", { hasText: "signed in as owner" })).toBeVisible({ timeout: 15_000 });
  await runCommand("EDP: Chat: open a ticket or epic thread…");
  await quickRow(page, "Spike epic").click();
  const c = chat();
  await expect(c.locator(".msg .body", { hasText: "here is the screen" })).toBeVisible({ timeout: 20_000 });
  const img = c.locator(`.att[data-artifact="${pngId}"] img.att-thumb`);
  await expect(img).toBeVisible({ timeout: 20_000 });
  const src = await img.getAttribute("src");
  expect(src!.startsWith("data:image/png;base64,")).toBe(true);
  const dims = await img.evaluate((e: HTMLImageElement) => ({ w: e.naturalWidth, h: e.naturalHeight }));
  expect(dims).toEqual({ w: 480, h: 270 }); // 1600x900 downscaled by the host, long edge 480
  const file = c.locator(`.att[data-artifact="${txtId}"]`);
  await expect(file.locator(".att-name")).toHaveText("notes.md");
  await expect(file.locator(".att-size")).toHaveText("34 B");
  note("thumbnail", { artifact: pngId, source: "1600x900", natural: dims, data_uri_bytes: src!.length, file_row: await file.innerText() });
  await page.screenshot({ path: shot("thumbnail-and-file.png") });
});

test("the webview made no request and its CSP adds only img-src data:", async () => {
  const c = chat();
  const csp = await c.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute("content");
  expect(csp).toMatch(/^default-src 'none'; script-src 'nonce-[^']+'; style-src 'nonce-[^']+'; img-src data:; form-action 'none'; base-uri 'none'$/);
  const res = await c.locator("body").evaluate(() => performance.getEntriesByType("resource").map(e => e.name));
  expect(res).toEqual([]);
  note("csp", { csp: csp!.replace(/nonce-[^']+/g, "nonce-…"), webview_resource_entries: res });
});

test("clicking the thumbnail opens the image full size in an editor tab; the file opens in a tab", async () => {
  const c = chat();
  await c.locator(`.att[data-artifact="${pngId}"]`).click();
  await expect(page.locator(".tab.active", { hasText: "screen.png" })).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: shot("full-size-tab.png") });
  await c.locator(`.att[data-artifact="${txtId}"]`).click();
  await expect(page.locator(".tab.active", { hasText: "notes.md" })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".monaco-editor .view-line", { hasText: "some text for the reader" }).first()).toBeVisible({ timeout: 10_000 });
});

test("clip button: the chosen file uploads, shows as a chip, and the send carries its artifact id", async () => {
  const c = chat();
  await c.locator("#attach-input").setInputFiles({ name: "clip.txt", mimeType: "text/plain", buffer: Buffer.from("from the clip button\n") });
  await expect(c.locator("#attachments .pend-name", { hasText: "clip.txt" })).toBeVisible({ timeout: 15_000 });
  const ta = c.locator("#composer");
  await ta.click();
  await ta.pressSequentially("clip attach");
  await page.keyboard.press("Control+Enter");
  await expect(ta).toHaveValue("", { timeout: 10_000 });
  await expect(c.locator("#attachments")).toBeHidden();
  const m = await sentWith("clip attach");
  expect(m.artifacts).toHaveLength(1);
  const art = await call("GET", `/v1/artifacts/${m.artifacts[0]}`, undefined, asOwner);
  expect(art).toMatchObject({ filename: "clip.txt", content_type: "text/plain", staged: false });
  await expect(c.locator(`.msg[data-id="${m.id}"] .att .att-name`)).toHaveText("clip.txt");
  note("clip", { message: m.id, artifacts: m.artifacts, filename: art.filename });
});

test("drag-drop onto the composer uploads and sends with the id", async () => {
  const c = chat();
  await c.locator(".cbox").evaluate((box, bytes) => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array(bytes)], "dropped.png", { type: "image/png" }));
    // VS Code hands a plain file drag over a webview to the workbench; Shift held keeps it in the webview
    for (const type of ["dragenter", "dragover", "drop"]) box.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt, shiftKey: true }));
  }, [...PNG_SMALL]);
  await expect(c.locator("#attachments .pend-name", { hasText: "dropped.png" })).toBeVisible({ timeout: 15_000 });
  await c.locator("#composer").click();
  await page.keyboard.press("Control+Enter"); // attachments-only: the host names the file in the text
  const m = await sentWith(/^Attached: `dropped\.png`$/);
  expect(m.artifacts).toHaveLength(1);
  await expect(c.locator(`.msg[data-id="${m.id}"] img.att-thumb`)).toBeVisible({ timeout: 15_000 });
  note("drop", { message: m.id, artifacts: m.artifacts, text: m.text });
  await page.screenshot({ path: shot("drop-sent.png") });
});

test("pasting a screenshot uploads it under a pasted-… name and sends with the id", async () => {
  const c = chat();
  const ta = c.locator("#composer");
  await ta.click();
  await ta.evaluate((el, bytes) => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array(bytes)], "image.png", { type: "image/png" }));
    const ev = new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: dt });
    // Firefox's ClipboardEvent constructor drops init files (a synthetic-event limit, not the real paste
    // path): hand the handler the same DataTransfer the browser gives a real screenshot paste
    const native = !!ev.clipboardData?.files.length;
    if (!native) Object.defineProperty(ev, "clipboardData", { value: dt });
    el.dispatchEvent(ev);
    return native;
  }, [...PNG_SMALL]).then(native => note("paste_event_constructor_carried_files", native));
  await expect(c.locator("#attachments .pend-name", { hasText: /^pasted-\d{8}-\d{6}\.png$/ })).toBeVisible({ timeout: 15_000 });
  await ta.pressSequentially("pasted shot");
  await page.keyboard.press("Control+Enter");
  const m = await sentWith("pasted shot");
  expect(m.artifacts).toHaveLength(1);
  const art = await call("GET", `/v1/artifacts/${m.artifacts[0]}`, undefined, asOwner);
  expect(art.filename).toMatch(/^pasted-\d{8}-\d{6}\.png$/);
  expect(art.content_type).toBe("image/png");
  note("paste", { message: m.id, artifacts: m.artifacts, filename: art.filename });
});

test("an over-size and a disallowed file are refused with the board's message; the draft is kept", async () => {
  const c = chat();
  const ta = c.locator("#composer");
  await ta.click();
  await ta.pressSequentially("draft that must survive");
  await c.locator("#attach-input").setInputFiles({ name: "huge.txt", mimeType: "text/plain", buffer: Buffer.alloc(26 * 1024 * 1024, 0x61) });
  await expect(c.locator("#send-error")).toContainText("Not attached: huge.txt: the file is over the 25 MB upload limit", { timeout: 60_000 });
  await expect(ta).toHaveValue("draft that must survive");
  const tooBig = await c.locator("#send-error").innerText();
  await page.screenshot({ path: shot("refused-oversize.png") });
  await c.locator("#attach-input").setInputFiles({ name: "tool.exe", mimeType: "application/octet-stream", buffer: Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x03, 0x00, 0x00, 0x00, 0xff, 0xfe]) });
  await expect(c.locator("#send-error")).toContainText("Not attached: tool.exe: that file type is not accepted", { timeout: 15_000 });
  await expect(ta).toHaveValue("draft that must survive");
  await expect(c.locator("#attachments .pend")).toHaveCount(0);
  await expect(c.locator("#send")).toBeEnabled();
  note("refused", { oversize: tooBig, disallowed: await c.locator("#send-error").innerText(), draft: await ta.inputValue() });
  await page.screenshot({ path: shot("refused-type.png") });
});
