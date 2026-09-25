// C9 live check on the running Code tab (:9410) at 1920x1080: sign in as this seat (EDP8_PARTICIPANT or
// EDP_HANDLE + EDP8_TOKEN from env, typed into the input box, never logged), open the epic, and measure how
// much of the chat panel's height the message list gets (criterion c-8c3474f044: >= 70%). Logs the header
// line count, each band's height and the ratio; screenshots the whole window.
// node c9-live.cjs <chromium|stockff> <outdir> <epicTitle>
const path = require('node:path');
const fs = require('node:fs');
const WEB = path.resolve(__dirname, '../../../web/node_modules');
const [which, outDir, epicTitle] = process.argv.slice(2);
const pw = require(`${WEB}/playwright-core`);
const PART = process.env.EDP8_PARTICIPANT || process.env.EDP_HANDLE, TOK = process.env.EDP8_TOKEN;
fs.mkdirSync(outDir, { recursive: true });
const logf = path.join(outDir, `${which}.log`);
const L = s => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + '\n'); };
(async () => {
  const browser = which === 'stockff'
    ? await pw.firefox.launch({ channel: 'moz-firefox', executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe', headless: true })
    : await pw.chromium.launch({ headless: true, executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe') });
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  page.on('pageerror', e => L(`pageerror ${e.message.slice(0, 200)}`));
  L(`browser ${which} ${browser.version()} viewport 1920x1080`);
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
  await quick.locator('input').fill(epicTitle);
  await row(epicTitle).waitFor({ timeout: 30000 });
  await row(epicTitle).click();
  const c = page.locator('iframe.webview').first().contentFrame().locator('#active-frame').contentFrame();
  await c.locator('#crumb-current', { hasText: epicTitle }).waitFor({ timeout: 20000 });
  await c.locator('#feed-status', { hasText: 'live' }).waitFor({ timeout: 20000 });
  // the owner's panel is ~710 px wide (art-a6f54001dd): drag the side bar's sash to match
  const aux = await page.locator('.part.auxiliarybar').boundingBox();
  await page.mouse.move(aux.x + 1, 540); await page.mouse.down(); await page.mouse.move(1920 - 712, 540, { steps: 10 }); await page.mouse.up();
  L(`aux bar width ${Math.round((await page.locator('.part.auxiliarybar').boundingBox()).width)} px`);
  await page.locator('.notifications-toasts .notification-toast').first().waitFor({ state: 'hidden', timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(3000); // the uncommitted chip and story counts settle
  const m = await c.locator('body').evaluate(() => {
    const h = s => { const e = document.querySelector(s); if (!e || e.hidden) return 0; return Math.round(e.getBoundingClientRect().height); };
    const hdr = document.querySelector('header.hdr').getBoundingClientRect();
    const pick = document.querySelector('#pick').getBoundingClientRect();
    return {
      panel: window.innerHeight, width: window.innerWidth, header: Math.round(hdr.height), pick: Math.round(pick.height),
      bands: h('#bands'), notice: h('#notice'), pinned: h('#pinned'), timeline: h('#timeline'), composer: h('#composer-form'),
      chips: [...document.querySelectorAll('.band-chip')].filter(e => !e.hidden).map(e => `${e.textContent} [${e.getAttribute('aria-expanded')}]`),
      header_text: [...document.querySelectorAll('header.hdr > :not([hidden])')].filter(e => e.id !== 'stories').map(e => `${e.id || e.className}=${(e.textContent || '').trim().slice(0, 40)}`),
    };
  });
  L(`panel ${m.width}x${m.panel}: header ${m.header} (picker ${m.pick}, one line: ${m.header < m.pick * 1.6}), bands ${m.bands}, notice ${m.notice}, pinned ${m.pinned}, timeline ${m.timeline}, composer ${m.composer}`);
  L(`header: ${m.header_text.join(' | ')}`);
  L(`chips: ${m.chips.join(' | ')}`);
  const ratio = m.timeline / m.panel;
  L(`thread share = ${m.timeline}/${m.panel} = ${(ratio * 100).toFixed(1)}% (${ratio >= 0.7 ? 'PASS' : 'FAIL'} >= 70%)`);
  await page.screenshot({ path: path.join(outDir, `${which}-epic-1920x1080.png`) });
  await c.locator('#stories-toggle').click();
  await page.waitForTimeout(500);
  L(`stories dropdown: ${(await c.locator('#stories .story').allTextContents()).length} rows`);
  await page.screenshot({ path: path.join(outDir, `${which}-stories-dropdown.png`) });
  await c.locator('#stories-toggle').click();
  await browser.close();
  L(ratio >= 0.7 ? 'PASS' : 'FAIL');
  if (ratio < 0.7) process.exit(2);
})().catch(e => { L(`FAIL ${String(e.message || e).split('\n')[0].slice(0, 300)}`); process.exit(1); });
