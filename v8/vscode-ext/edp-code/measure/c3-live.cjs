// C3 live check on the running Code tab (:9410, or the SPA /ui/code on :9400 with --spa): sign in as
// this seat (EDP8_PARTICIPANT/EDP8_TOKEN from env, typed into the input box, never logged), open the
// epic through `EDP: Chat: open a ticket or epic thread…`, check the thread/Stories strip/architect,
// open the story, POST a note from outside and time its arrival. node c3-live.cjs <chromium|stockff> <outdir> <epicTitle> <storyId>
const path = require('node:path');
const fs = require('node:fs');
const WEB = path.resolve(__dirname, '../../../web/node_modules');
const [which, outDir, epicTitle, story] = process.argv.slice(2);
const pw = require(`${WEB}/playwright-core`);
const PART = process.env.EDP8_PARTICIPANT, TOK = process.env.EDP8_TOKEN, BOARD = process.env.EDP8_BOARD_URL || 'http://127.0.0.1:9400';
fs.mkdirSync(outDir, { recursive: true });
const logf = path.join(outDir, `${which}.log`);
const L = s => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + '\n'); };
(async () => {
  const browser = which === 'stockff'
    ? await pw.firefox.launch({ channel: 'moz-firefox', executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe', headless: true })
    : await pw.chromium.launch({ headless: true, executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe') });
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 950 } })).newPage();
  page.on('pageerror', e => L(`pageerror ${e.message.slice(0, 200)}`));
  L(`browser ${which} ${browser.version()}`);
  await page.goto('http://127.0.0.1:9410/?folder=/c:/Projects/Learning/eda-base3/v8', { waitUntil: 'domcontentloaded' });
  await page.locator('div.monaco-workbench').waitFor({ timeout: 60000 });
  await page.waitForTimeout(5000);
  const quick = page.locator('.quick-input-widget');
  const row = t => quick.locator('.monaco-list-row', { hasText: t }).first();
  const cmd = async t => { await page.keyboard.press('F1'); await quick.locator('input').fill(`>${t}`); await row(t).click(); };
  const type = async (v, title) => { await quick.locator('.quick-input-title', { hasText: title }).waitFor(); const i = quick.locator('input'); await i.fill(''); await i.pressSequentially(v); await page.keyboard.press('Enter'); };
  await cmd('EDP: Sign in to board');
  await type(PART, 'EDP: board participant id');
  await type(TOK, 'EDP: token for');
  await page.locator('.notifications-toasts', { hasText: 'signed in as' }).waitFor({ timeout: 15000 });
  L('signed in');
  await cmd('EDP: Chat: open a ticket or epic thread…');
  await quick.locator('.quick-input-title', { hasText: 'EDP chat: open a thread' }).waitFor({ timeout: 10000 });
  await quick.locator('input').fill(epicTitle); // the list is virtualised: filter first
  await row(epicTitle).waitFor({ timeout: 30000 });
  await page.screenshot({ path: path.join(outDir, `${which}-picker.png`) });
  await row(epicTitle).click();
  const c = page.locator('iframe.webview').first().contentFrame().locator('#active-frame').contentFrame();
  await c.locator('#crumb-current', { hasText: epicTitle }).waitFor({ timeout: 20000 });
  await c.locator('#feed-status', { hasText: 'live' }).waitFor({ timeout: 20000 });
  const aux = await page.locator('.part.auxiliarybar').boundingBox(), ed = await page.locator('.part.editor').boundingBox();
  L(`epic open: crumb="${await c.locator('#crumb-current').textContent()}" architect="${await c.locator('#architect').textContent()}" stories=${await c.locator('.story').count()} messages=${await c.locator('.msg').count()} aux.x=${aux?.x} editor.right=${ed ? ed.x + ed.width : '?'}`);
  L(`stories: ${(await c.locator('.story').allTextContents()).join(' | ')}`);
  await page.screenshot({ path: path.join(outDir, `${which}-epic.png`) });
  await c.locator(`.story[data-id="${story}"]`).click();
  await c.locator('#crumb-epic').waitFor({ timeout: 15000 });
  L(`story open: crumb="${await c.locator('#crumb-current').textContent()}" back="${await c.locator('#crumb-epic').textContent()}" messages=${await c.locator('.msg').count()}`);
  const text = `C3 live check (${which}): a note posted from outside the panel at ${new Date().toISOString()}`;
  const t0 = Date.now();
  const r = await fetch(`${BOARD}/v1/messages`, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Participant': PART, 'X-Token': TOK }, body: JSON.stringify({ ticket_id: story, kind: 'note', text }) });
  L(`POST /v1/messages -> ${r.status}`);
  await c.locator('.msg .body', { hasText: text }).waitFor({ timeout: 10000 });
  L(`live note visible after ${Date.now() - t0} ms`);
  await page.screenshot({ path: path.join(outDir, `${which}-story-live.png`) });
  await c.locator('#crumb-epic').click();
  await c.locator('#crumb-current', { hasText: epicTitle }).waitFor({ timeout: 15000 });
  L(`back to epic: note on epic thread? ${await c.locator('.msg .body', { hasText: text }).count()} (0 = never merged)`);
  const csp = await page.locator('iframe.webview').first().contentFrame().locator('#active-frame').contentFrame().locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
  L(`CSP: ${csp}`);
  await browser.close();
  L('PASS');
})().catch(e => { L(`FAIL ${String(e.message || e).split('\n')[0].slice(0, 300)}`); process.exit(1); });
