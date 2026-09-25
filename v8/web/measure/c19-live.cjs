// C19 live look (s-35ca5ca2ac, criterion c-03a5db1412): on the LIVE board UI (:9400, C18 live), send
// a message on the story thread quoting two passages of design-10b21760d9 and one earlier message,
// through the real UI (select → popover → Quote, chips, Ctrl+Enter), then screenshot its three quote
// cards. Identity is the running seat (EDP_HANDLE + EDP8_TOKEN); the token goes in the URL once and
// the SPA strips it from the address bar.
//   node measure/c19-live.cjs chromium|stockff
// Screenshots: e2e/evidence/c19-live/<browser>/ (gitignored; uploaded as board artifacts).
const fs = require("node:fs");
const path = require("node:path");
const { chromium, firefox } = require("playwright");

const BOARD = process.env.EDP8_BOARD_URL ?? "http://127.0.0.1:9400";
const SEAT = process.env.EDP_HANDLE;
const TOKEN = process.env.EDP8_TOKEN;
const STORY = "s-35ca5ca2ac";
const DESIGN = "design-10b21760d9";
const VERSION = 12;
const MSG = "m-5a2ea5c4e5"; // the architect's C19 steer on this thread
const which = process.argv[2] ?? "chromium";
const OUT = path.join(__dirname, "..", "e2e", "evidence", "c19-live", which);

async function select(page, scope, text, until) {
  const ok = await page.evaluate(({ scope, text, until }) => {
    const root = document.querySelector(scope);
    if (!root) return false;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = []; let all = "";
    for (let n = w.nextNode(); n; n = w.nextNode()) { nodes.push(n); all += n.data; }
    const at = all.indexOf(text);
    if (at < 0) return false;
    const endAt = until ? all.indexOf(until, at) + until.length : at + text.length;
    const r = document.createRange(); let pos = 0;
    for (const n of nodes) {
      const end = pos + n.data.length;
      if (at >= pos && at < end) r.setStart(n, at - pos);
      if (endAt > pos && endAt <= end) { r.setEnd(n, endAt - pos); break; }
      pos = end;
    }
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    r.startContainer.parentElement.scrollIntoView({ block: "center" });
    return true;
  }, { scope, text, until });
  if (!ok) throw new Error(`"${text}" not on screen in ${scope}`);
  await page.evaluate(() => document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true })));
}

async function quote(page, note) {
  const pop = page.getByTestId("quote-popover");
  await pop.waitFor();
  if (note) { await pop.getByTestId("quote-note").click(); await page.keyboard.type(note); }
  await pop.getByTestId("quote-add").click();
  await pop.waitFor({ state: "hidden" });
}

(async () => {
  if (!SEAT || !TOKEN) throw new Error("EDP_HANDLE and EDP8_TOKEN must be set (run from the seat shell)");
  fs.mkdirSync(OUT, { recursive: true });
  const browser = which === "stockff"
    ? await firefox.launch({ channel: "moz-firefox", executablePath: process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe" })
    : await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const as = encodeURIComponent(SEAT);
  try {
    await page.goto(`${BOARD}/ui/ticket/${STORY}?as=${as}&token=${encodeURIComponent(TOKEN)}`);
    await page.getByTestId("thread").waitFor();
    for (const r of await page.getByTestId("quote-chip-remove").all()) await r.click(); // a clean tray

    // two passages of the design at v12, through the doc drawer
    await page.goto(`${BOARD}/ui/ticket/${STORY}?as=${as}&doc=${DESIGN}&v=${VERSION}`);
    await page.getByTestId("doc-body").getByText("Class fix:", { exact: true }).first().waitFor();
    await select(page, "[data-testid=doc-body]", "The board validates each quote");
    await page.screenshot({ path: path.join(OUT, "01-doc-popover.png") });
    await quote(page, "the C18 check C19 feeds");
    await select(page, "[data-testid=doc-body]", "text: the quoted passage, stored inline");
    await quote(page, "why the card shows the passage, not a link only");

    // one earlier message on this thread
    await page.goto(`${BOARD}/ui/ticket/${STORY}?as=${as}`);
    await page.getByTestId("thread").waitFor();
    await select(page, `li[id="${MSG}"]`, "Read the owner's words");
    await quote(page, "");

    const chips = page.getByTestId("quote-chip");
    if ((await chips.count()) !== 3) throw new Error(`expected 3 chips, got ${await chips.count()}`);
    const text = `C19 live look (${which}): one message, three quotes (two from ${DESIGN} v${VERSION}, one from ${MSG}). Evidence only; no action needed.`;
    await page.getByTestId("composer-text").click();
    await page.keyboard.type(text);
    await page.getByTestId("quote-chips").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(OUT, "02-composer-chips.png") });
    await page.getByTestId("composer-text").press("Control+Enter");
    await page.getByTestId("sent-note").waitFor();

    const row = page.getByTestId("thread-message").filter({ hasText: `C19 live look (${which})` }).last();
    await row.waitFor();
    const cards = row.getByTestId("quote-card");
    await cards.nth(2).waitFor();
    const n = await cards.count();
    const labels = await row.getByTestId("quote-source").allTextContents();
    await row.scrollIntoViewIfNeeded();
    await row.screenshot({ path: path.join(OUT, "03-quote-cards.png") });
    await page.screenshot({ path: path.join(OUT, "04-thread.png") });
    const id = await row.getAttribute("id");
    console.log(JSON.stringify({ browser: which, message: id, cards: n, sources: labels.map((s) => s.trim()) }));
    if (n !== 3) process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
