// S7 live look (s-03c7e9168b, criterion c-6a5c213ef6): the LIVE /ui/code on :9400, whose iframe is
// code-server behind the :9410 host guard, in Chromium or stock Firefox. In the frame it:
//   1. opens a file (Quick Open v8/README.md),
//   2. opens an integrated terminal and runs a command that writes a marker file (read back here),
//   3. opens a Markdown preview (the webview frame renders the README heading),
//   4. signs the EDP extension in as this seat, tags README lines 1-2 to this seat on this story, and
//      reads the message back from the board: its code_context carries a commit,
//   5. opens this story in EDP Chat: the extension's webview renders the thread with a live feed.
// Fails on any error dialog, a password/login page, or a pageerror naming the guard. Signs the
// extension out at the end, so no seat credential stays in the owner's editor.
// Identity is the running seat (EDP_HANDLE + EDP8_TOKEN; the token goes in the URL once / typed
// into the input box, never logged).
//   node measure/s7-guard-live.cjs chromium|stockff
// Screenshots: e2e/evidence/s7-guard-live/<browser>/ (gitignored; uploaded as board artifacts).
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { chromium, firefox } = require("playwright");

const BOARD = process.env.EDP8_BOARD_URL ?? "http://127.0.0.1:9400";
const SEAT = process.env.EDP_HANDLE;
const TOKEN = process.env.EDP8_TOKEN;
const STORY = "s-03c7e9168b";
const STORY_TITLE = "S7 Host-allowlist gatekeeper";
const which = process.argv[2] ?? "chromium";
const OUT = path.join(__dirname, "..", "e2e", "evidence", "s7-guard-live", which);
fs.mkdirSync(OUT, { recursive: true });
const logf = path.join(OUT, "run.log");
fs.writeFileSync(logf, "");
const L = (s) => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + "\n"); };
let fails = 0;
const check = (ok, what) => { L(`${ok ? "PASS" : "FAIL"} ${what}`); if (!ok) fails++; };

(async () => {
  if (!SEAT || !TOKEN) throw new Error("EDP_HANDLE and EDP8_TOKEN must be set (the running seat)");
  const browser = which === "stockff"
    ? await firefox.launch({ channel: "moz-firefox", executablePath: process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe" })
    : await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 200)));
  page.on("response", (r) => { if (r.url().includes(":9410") && [403, 421].includes(r.status())) errors.push(`guard ${r.status()} ${r.url().slice(0, 120)}`); });
  L(`browser ${which} ${browser.version()}`);
  const shot = (n) => page.screenshot({ path: path.join(OUT, `${n}.png`) });
  try {
    await page.goto(`${BOARD}/ui/code?as=${encodeURIComponent(SEAT)}&token=${encodeURIComponent(TOKEN)}`);
    const frameEl = page.locator("iframe").first();
    await frameEl.waitFor({ timeout: 30000 });
    const src = await frameEl.getAttribute("src");
    L(`iframe src ${src}`);
    check(/^http:\/\/(127\.0\.0\.1|localhost):9410\//.test(src ?? ""), "the Code tab frames code-server on :9410 (shape A)");
    const f = page.frameLocator("iframe").first();
    await f.locator("div.monaco-workbench").waitFor({ timeout: 90000 });
    await page.waitForTimeout(6000);
    check(await f.locator("input[type=password]").count() === 0, "no password prompt in the frame");
    const quick = f.locator(".quick-input-widget");
    const cmd = async (t) => {
      for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await f.locator("div.monaco-workbench").press("F1"); await page.waitForTimeout(700); }
      await quick.locator("input").fill(`>${t}`);
      await quick.locator(".monaco-list-row", { hasText: t }).first().click();
    };
    const answer = async (title, v, pickText) => {
      await quick.locator(".quick-input-title", { hasText: title }).waitFor({ timeout: 20000 });
      const i = quick.locator("input"); await i.fill(""); await i.pressSequentially(v);
      if (pickText) { await quick.locator(".monaco-list-row", { hasText: pickText }).first().waitFor({ timeout: 20000 }); await page.waitForTimeout(300); }
      await i.press("Enter");
    };

    // 1. open a file
    await f.locator(".part.editor").first().click();
    for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await page.keyboard.press("Control+p"); await page.waitForTimeout(700); }
    await quick.locator("input").fill("README.md");
    await quick.locator(".monaco-list-row", { hasText: "README.md" }).first().click();
    const tab = f.locator(".tabs-container .tab", { hasText: "README.md" }).first();
    await tab.waitFor({ timeout: 20000 });
    await f.locator(".monaco-editor .view-lines").first().waitFor();
    check(true, "opened v8/README.md in an editor tab");
    await shot("1-file");

    // 2. integrated terminal: a marker file written by the shell proves it runs
    const marker = path.join(os.tmpdir(), `s7-guard-term-${which}-${Date.now()}.txt`);
    await cmd("Terminal: Create New Terminal");
    const term = f.locator(".terminal-wrapper .xterm").first();
    await term.waitFor({ timeout: 30000 });
    await page.waitForTimeout(4000);
    await term.click();
    await page.keyboard.type(`Set-Content -Path '${marker}' -Value "ok $PID"`);
    await page.keyboard.press("Enter");
    let wrote = false;
    for (let i = 0; i < 40 && !wrote; i++) { await page.waitForTimeout(500); wrote = fs.existsSync(marker); }
    check(wrote, `integrated terminal ran a command (${path.basename(marker)} ${wrote ? fs.readFileSync(marker, "utf8").trim() : "missing"})`);
    await shot("2-terminal");
    if (wrote) fs.rmSync(marker);
    await cmd("View: Close Panel").catch(() => {});

    // 3. Markdown preview: a webview whose document renders the README's first heading
    await tab.click();
    await cmd("Markdown: Open Preview");
    const pv = f.locator(".tabs-container .tab", { hasText: "Preview README.md" }).first();
    await pv.waitFor({ timeout: 20000 });
    let heading = "";
    for (let i = 0; i < 30 && !heading; i++) {
      await page.waitForTimeout(1000);
      for (const fr of page.frames()) {
        try { const h = await fr.locator("h1").first().textContent({ timeout: 200 }); if (h && fr.url().includes("webview")) { heading = h.trim(); break; } } catch { /* not this frame */ }
      }
    }
    check(!!heading, `Markdown preview rendered the README heading (${heading ? `"${heading.slice(0, 60)}"` : "no heading in any webview frame"})`);
    await shot("3-md-preview");

    // 4. EDP tag with a commit
    await cmd("EDP: Sign in to board");
    await answer("EDP: board participant id", SEAT);
    await answer("EDP: token for", TOKEN);
    await f.locator(".notifications-toasts", { hasText: "signed in as" }).waitFor({ timeout: 20000 });
    await tab.click();
    await f.locator(".monaco-editor .view-lines").first().click();
    await f.locator("div.monaco-workbench").press("Control+Home");
    await f.locator("div.monaco-workbench").press("Shift+ArrowDown");
    await f.locator("div.monaco-workbench").press("Shift+ArrowDown");
    const note = `S7 guard live check (${which}): tag through the :9410 guard`;
    await cmd("EDP: Tag selection on board");
    await answer("EDP: tag", SEAT, SEAT);
    await answer("EDP: ticket for", STORY, STORY);
    await answer("EDP: note to", note);
    await answer("EDP: message kind", "note", "note");
    const toast = f.locator(".notifications-toasts", { hasText: "EDP: tagged" }).first();
    await toast.waitFor({ timeout: 20000 });
    const mid = ((await toast.textContent()) ?? "").match(/m-[0-9a-f]{10}/)?.[0];
    await shot("4-tag-sent");
    const r = await fetch(`${BOARD}/v1/messages/${mid}`, { headers: { "X-Participant": SEAT, "X-Token": TOKEN } });
    const m = (await r.json()).value ?? {};
    const cc = m.code_context ?? {};
    check(!!mid && /^[0-9a-f]{7,40}$/.test(cc.commit ?? ""), `EDP tag ${mid} landed with code_context ${cc.path}:L${cc.line_start}-${cc.line_end} commit ${cc.commit}`);

    // EDP Chat (the extension's webview) opens this story's thread and goes live (c-0ea9442d61); after the tag,
    // since with a thread open the tag command fills the chat composer instead of asking
    await cmd("EDP: Chat: open a ticket or epic thread");
    await quick.locator(".quick-input-title", { hasText: "EDP chat: open a thread" }).waitFor({ timeout: 10000 });
    await quick.locator("input").fill(STORY_TITLE);
    await quick.locator(".monaco-list-row", { hasText: STORY_TITLE }).first().click({ timeout: 30000 });
    // the chat is one of several webview frames (the Markdown preview is another): find it by its crumb
    let crumb = "", live = "", rows = 0;
    for (let i = 0; i < 30 && !(crumb.includes(STORY_TITLE) && /live/.test(live)); i++) {
      await page.waitForTimeout(1000);
      for (const fr of page.frames()) {
        try {
          if (!(await fr.locator("#crumb-current").count())) continue;
          crumb = (await fr.locator("#crumb-current").textContent({ timeout: 500 })) ?? "";
          live = (await fr.locator("#feed-status").textContent({ timeout: 500 })) ?? "";
          rows = await fr.locator("#timeline > *").count();
          break;
        } catch { /* not this frame */ }
      }
    }
    check(crumb.includes(STORY_TITLE) && /live/.test(live) && rows > 0,
      `EDP Chat rendered this story's thread (crumb "${crumb.slice(0, 50)}", feed "${live.trim()}", ${rows} timeline rows)`);
    await shot("5-chat");

    const dialogs = await f.locator(".monaco-dialog-box").count();
    check(dialogs === 0, `no error dialog (${dialogs} dialog boxes)`);
    check(!errors.some((e) => /guard|421|403/.test(e)), `no guard refusal seen by the page (${errors.length} page errors${errors.length ? ": " + errors.slice(0, 3).join(" | ") : ""})`);
    await cmd("EDP: Sign out of board").catch(() => L("sign-out command not found"));
    await page.waitForTimeout(1500);
  } catch (e) {
    check(false, `run aborted: ${e.message.split("\n")[0]}`);
    await shot("abort").catch(() => {});
  } finally {
    await browser.close();
  }
  L(fails ? `${fails} FAIL` : "all PASS");
  process.exit(fails ? 1 : 0);
})();
