// C20 live look (s-29f052c40e, criterion c-660919d3cf): on the LIVE /ui/code (:9400 framing code-server behind the
// :9410 guard), edp-code 0.12.0 builds one message on this story that quotes three sources, and it renders as three
// quote cards in VS Code (EDP Chat) and on the board UI's ticket page. In the frame it:
//   1. signs the EDP extension in as this seat and opens this story's thread in EDP Chat,
//   2. quotes a passage of the architect's ruling message (m-db0d013529) from the chat (selection -> Quote -> note),
//   3. opens the story's design (Docs tab -> the EDP reader) and quotes a §14.5 passage (selection -> Quote in chat),
//   4. quotes README.md lines 1-3 from the editor (Ctrl+Alt+Q -> the inline comment box -> Add to chat),
//   5. sends it with Ctrl+Enter; reads the message back from the board (three quotes: message, doc, code),
//      screenshots the three cards in the chat, then the same message on /ui/ticket/<story> (three cards).
// Signs the extension out at the end. Identity is the running seat (EDP_HANDLE + EDP8_TOKEN; never logged).
//   node measure/c20-quotes-live.cjs chromium|stockff
// Screenshots: e2e/evidence/c20-quotes-live/<browser>/ (gitignored; uploaded as board artifacts).
const fs = require("node:fs");
const path = require("node:path");
const { chromium, firefox } = require("playwright");

const BOARD = process.env.EDP8_BOARD_URL ?? "http://127.0.0.1:9400";
const SEAT = process.env.EDP_HANDLE;
const TOKEN = process.env.EDP8_TOKEN;
const STORY = "s-29f052c40e";
const STORY_TITLE = "C20 VS Code: quote from the doc reader";
const DESIGN = "design-10b21760d9";
const RULING = "m-db0d013529";
const which = process.argv[2] ?? "chromium";
const OUT = path.join(__dirname, "..", "e2e", "evidence", "c20-quotes-live", which);
fs.mkdirSync(OUT, { recursive: true });
const logf = path.join(OUT, "run.log");
fs.writeFileSync(logf, "");
const L = (s) => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + "\n"); };
let fails = 0;
const check = (ok, what) => { L(`${ok ? "PASS" : "FAIL"} ${what}`); if (!ok) fails++; };
const api = async (p) => (await (await fetch(`${BOARD}${p}`, { headers: { "X-Participant": SEAT, "X-Token": TOKEN } })).json()).value;

/** Select the first `n` words of the first element matching `sel` whose text includes `must` (in one text node). */
const selectWords = (loc, n) => loc.evaluate((el, n) => {
  const walk = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let t = walk.nextNode(); t; t = walk.nextNode()) {
    const s = t.textContent ?? "";
    const m = s.match(new RegExp(`^\\s*((?:\\S+\\s+){${n - 1}}\\S+)`));
    if (!m) continue;
    const start = s.indexOf(m[1]);
    const r = el.ownerDocument.createRange();
    r.setStart(t, start); r.setEnd(t, start + m[1].length);
    const sel = el.ownerDocument.getSelection();
    sel.removeAllRanges(); sel.addRange(r);
    return m[1];
  }
  throw new Error("no text node with enough words");
}, n);

(async () => {
  if (!SEAT || !TOKEN) throw new Error("EDP_HANDLE and EDP8_TOKEN must be set (the running seat)");
  const ff = which === "stockff";
  const browser = ff
    ? await firefox.launch({ channel: "moz-firefox", executablePath: process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe" })
    : await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 200)));
  page.on("response", (r) => { if (r.url().includes(":9410") && [403, 421].includes(r.status())) errors.push(`guard ${r.status()} ${r.url().slice(0, 120)}`); });
  L(`browser ${which} ${browser.version()}`);
  const shot = (n) => page.screenshot({ path: path.join(OUT, `${n}.png`) });
  const text = `C20 live check (${which}): three quotes in one message, sent from VS Code through the :9410 guard`;
  try {
    await page.goto(`${BOARD}/ui/code?as=${encodeURIComponent(SEAT)}&token=${encodeURIComponent(TOKEN)}`);
    const frameEl = page.locator("iframe").first();
    await frameEl.waitFor({ timeout: 30000 });
    const f = page.frameLocator("iframe").first();
    await f.locator("div.monaco-workbench").waitFor({ timeout: 90000 });
    await page.waitForTimeout(6000);
    const quick = f.locator(".quick-input-widget");
    const cmd = async (t) => {
      for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await f.locator("div.monaco-workbench").press("F1"); await page.waitForTimeout(700); }
      await quick.locator("input").fill(`>${t}`);
      await quick.locator(".monaco-list-row", { hasText: t }).first().click();
    };
    const answer = async (title, v) => {
      await quick.locator(".quick-input-title", { hasText: title }).waitFor({ timeout: 20000 });
      const i = quick.locator("input"); await i.fill(""); await i.pressSequentially(v);
      await i.press("Enter");
    };
    const frameWith = async (sel, pred = async () => true) => {
      for (let i = 0; i < 40; i++) {
        for (const fr of page.frames()) {
          try { if ((await fr.locator(sel).count()) && (await pred(fr))) return fr; } catch { /* detached */ }
        }
        await page.waitForTimeout(750);
      }
      throw new Error(`no frame with ${sel}`);
    };

    // 1. sign in, open the thread
    await cmd("EDP: Sign in to board");
    await answer("EDP: board participant id", SEAT);
    await answer("EDP: token for", TOKEN);
    await f.locator(".notifications-toasts", { hasText: "signed in as" }).waitFor({ timeout: 20000 });
    await cmd("EDP: Chat: open a ticket or epic thread");
    await quick.locator(".quick-input-title", { hasText: "EDP chat: open a thread" }).waitFor({ timeout: 10000 });
    await quick.locator("input").fill(STORY_TITLE);
    await quick.locator(".monaco-list-row", { hasText: STORY_TITLE }).first().click({ timeout: 30000 });
    const chat = await frameWith("#crumb-current", async (fr) => ((await fr.locator("#crumb-current").textContent()) ?? "").includes("C20"));
    const ruling = chat.locator(`.msg[data-id="${RULING}"] > .body`);
    await ruling.waitFor({ timeout: 30000 });
    check(true, "EDP Chat opened this story's thread");

    // 2. a chat message passage
    await ruling.scrollIntoViewIfNeeded();
    const mq = await selectWords(ruling, 8);
    await chat.locator("#quote-selection").waitFor({ state: "visible", timeout: 5000 });
    await chat.locator("#quote-selection").click();
    await chat.locator("#quote-pop-note").pressSequentially("The ruling this story ships.");
    await shot("1-message-popover");
    await chat.locator("#quote-pop-note").press("Control+Enter");
    await chat.locator("#quote-chips > li.qchip").first().waitFor({ timeout: 10000 });
    check(true, `quoted the ruling message: "${mq}"`);

    // 3. the design passage from the reader
    await chat.locator("#tab-docs").click();
    await chat.locator(`#panel-docs .dc-row[data-id="${DESIGN}"] .dc-open`).click({ timeout: 30000 });
    const reader = await frameWith("#rd-title", async (fr) => (await fr.title()).startsWith(`EDP ${DESIGN} v`));
    L(`reader: ${await reader.title()}`);
    const para = reader.locator("#doc h2, #doc h3").filter({ hasText: "14.5" }).first().locator("xpath=following::p[1]");
    await para.waitFor({ timeout: 20000 });
    await para.scrollIntoViewIfNeeded();
    const dq = await selectWords(para, 10);
    await reader.locator("#rd-quote-sel").waitFor({ state: "visible", timeout: 5000 });
    await reader.locator("#rd-quote-sel").click();
    await reader.locator("#rd-quote-note").pressSequentially("The rule the three cards follow.");
    await shot("2-reader-popover");
    await reader.locator("#rd-quote-add").click();
    await reader.locator("#rd-status", { hasText: "Added" }).waitFor({ timeout: 10000 });
    check(true, `quoted the design in the reader: "${dq}"`);

    // 4. code: README.md lines 1-3 via Ctrl+Alt+Q
    await f.locator(".tabs-container .tab.active").click();
    for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await f.locator("div.monaco-workbench").press("Control+p"); await page.waitForTimeout(700); }
    await quick.locator("input").fill("README.md");
    await quick.locator(".monaco-list-row", { hasText: "README.md" }).first().click();
    await f.locator(".tabs-container .tab.active", { hasText: "README.md" }).waitFor({ timeout: 20000 });
    const num = (n) => f.locator(".monaco-editor .margin-view-overlays .line-numbers", { hasText: new RegExp(`^${n}$`) }).first();
    const a = await num(1).boundingBox(), b = await num(3).boundingBox();
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 5 });
    await page.mouse.up();
    await page.keyboard.press("Control+Alt+Q");
    const box = f.locator(".review-widget").last();
    await box.waitFor({ timeout: 10000 });
    const codeNote = "The lines this check quotes.";
    await page.keyboard.type(codeNote);
    const typed = ((await box.locator(".comment-form .monaco-editor .view-lines").first().innerText()).replace(/\s+/g, " ")).includes("The lines");
    await shot("3-code-comment-box");
    await box.getByRole("button", { name: "Add to chat" }).click();
    await page.waitForTimeout(1500);
    check(true, `quoted README.md lines 1-3 (${typed ? "note typed in the box" : "Playwright Firefox dropped the typed note; entered on the chip"})`);

    // 5. send
    await cmd("EDP: Open chat");
    const chips = chat.locator("#quote-chips > li.qchip");
    await chat.locator("#tab-chat").click().catch(() => {});
    for (let i = 0; i < 20 && (await chips.count()) < 3; i++) await page.waitForTimeout(500);
    check((await chips.count()) === 3, `three chips in the composer (${await chips.count()})`);
    if (!typed) await chips.nth(2).locator(".qchip-note").pressSequentially(codeNote);
    await chat.locator("#composer").click();
    await chat.locator("#composer").pressSequentially(text);
    await shot("4-composer-three-chips");
    await chat.locator("#composer").press("Control+Enter");
    let m;
    for (let i = 0; i < 30 && !m; i++) {
      await page.waitForTimeout(1000);
      const th = await api(`/v1/tickets/${STORY}/thread`);
      m = (th?.thread ?? []).find((x) => x.text === text);
    }
    const q = m?.quotes ?? [];
    check(q.length === 3 && q.map((x) => x.source).join(",") === "message,doc,code",
      `board message ${m?.id} carries ${q.length} quotes (${q.map((x) => `${x.source}:${x.id ?? x.code?.path}`).join(", ")})`);
    fs.writeFileSync(path.join(OUT, "message.json"), JSON.stringify({ id: m?.id, text: m?.text, quotes: q }, null, 1));
    const cards = chat.locator(`.msg[data-id="${m?.id}"] .quote-card`);
    await cards.first().waitFor({ timeout: 15000 });
    await chat.locator(`.msg[data-id="${m?.id}"]`).scrollIntoViewIfNeeded();
    check((await cards.count()) === 3, `VS Code renders ${await cards.count()} quote cards`);
    await shot("5-vscode-three-cards");
    await cmd("EDP: Sign out of board").catch(() => L("sign-out command not found"));
    await page.waitForTimeout(1500);

    // the board UI
    await page.goto(`${BOARD}/ui/ticket/${STORY}?as=${encodeURIComponent(SEAT)}&token=${encodeURIComponent(TOKEN)}`);
    const li = page.locator(`li[id="${m?.id}"]`);
    await li.waitFor({ timeout: 30000 });
    await li.scrollIntoViewIfNeeded();
    const bc = li.locator("[data-testid=quote-card]");
    await bc.first().waitFor({ timeout: 15000 });
    check((await bc.count()) === 3, `the board UI renders ${await bc.count()} quote cards (${(await bc.evaluateAll((e) => e.map((x) => x.getAttribute("data-source")))).join(", ")})`);
    await li.screenshot({ path: path.join(OUT, "6-board-three-cards.png") });
    await shot("6-board-page");

    check(!errors.some((e) => /guard|421|403/.test(e)), `no guard refusal seen by the page (${errors.length} page errors${errors.length ? ": " + errors.slice(0, 3).join(" | ") : ""})`);
  } catch (e) {
    check(false, `run aborted: ${e.message.split("\n")[0]}`);
    await shot("abort").catch(() => {});
  } finally {
    await browser.close();
  }
  L(fails ? `${fails} FAIL` : "all PASS");
  process.exit(fails ? 1 : 0);
})();
