// C13 live check on the running Code tab (:9410) at 1920x1080: sign in as this seat (EDP8_PARTICIPANT or
// EDP_HANDLE + EDP8_TOKEN from env, typed into the input box, never logged), open the epic, and check the
// tabs (s-f4e767cfd1): Chat / Changes / Commits under a one-line header; each group header in Changes
// expands by a real click and paints its rows; Commits lists cards; the # picker opens at the workspace
// folder and `#../` lists the git root, where `edp-pool/` is picked as a root-relative token (not sent).
// node c13-live.cjs <chromium|stockff> <outdir> <epicTitle>
const path = require('node:path');
const fs = require('node:fs');
const WEB = path.resolve(__dirname, '../../../web/node_modules');
const [which, outDir, epicTitle] = process.argv.slice(2);
const pw = require(`${WEB}/playwright-core`);
const PART = process.env.EDP8_PARTICIPANT || process.env.EDP_HANDLE, TOK = process.env.EDP8_TOKEN;
fs.mkdirSync(outDir, { recursive: true });
const logf = path.join(outDir, `${which}.log`);
const L = s => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + '\n'); };
let fails = 0;
const check = (ok, what) => { L(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) fails++; };
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
  const cmd = async t => {
    for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await page.keyboard.press('F1'); await page.waitForTimeout(700); }
    await quick.locator('input').fill(`>${t}`); await row(t).click();
  };
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
  const aux = await page.locator('.part.auxiliarybar').boundingBox();
  await page.mouse.move(aux.x + 1, 540); await page.mouse.down(); await page.mouse.move(1920 - 712, 540, { steps: 10 }); await page.mouse.up();
  await page.locator('.notifications-toasts .notification-toast').first().waitFor({ state: 'hidden', timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(3000);
  const tabs = await c.locator('[role=tablist] [role=tab]').allTextContents();
  check(tabs.length === 3 && /^Chat/.test(tabs[0]) && /^Changes/.test(tabs[1]) && /^Commits/.test(tabs[2]), `tabs: ${tabs.join(' | ')}`);
  const tl = await c.locator('#timeline').evaluate(e => ({ h: Math.round(e.getBoundingClientRect().height), panel: window.innerHeight }));
  check(tl.h / tl.panel >= 0.7, `chat thread share ${tl.h}/${tl.panel} = ${(100 * tl.h / tl.panel).toFixed(1)}%`);
  await page.screenshot({ path: path.join(outDir, `${which}-1-chat.png`) });
  // painted = the element is on screen and the topmost element at its centre is it (or inside it)
  const painted = loc => loc.evaluate(e => { const r = e.getBoundingClientRect(); if (r.height < 4 || r.bottom > innerHeight) return false; const t = document.elementFromPoint(r.x + Math.min(20, r.width / 2), r.y + r.height / 2); return !!t && (t === e || e.contains(t)); });
  await c.locator('#tab-changes').click();
  await c.locator('#changes-summary').waitFor({ timeout: 10000 });
  L(`changes: ${await c.locator('#changes-summary').textContent()}`);
  for (const g of ['scoped', 'all']) {
    const t = c.locator(`#changes-${g}-toggle`);
    if (!(await t.count())) { L(`changes group ${g}: absent`); continue; }
    if ((await t.getAttribute('aria-expanded')) !== 'true') await t.click();
    await page.waitForTimeout(300);
    const first = c.locator(`#changes-${g} .cf`).first();
    const n = await c.locator(`#changes-${g} .cf`).count();
    check((await t.getAttribute('aria-expanded')) === 'true' && (n === 0 || await painted(first)), `changes ${g}: click expands, ${n} rows, first painted`);
  }
  await page.screenshot({ path: path.join(outDir, `${which}-2-changes.png`) });
  await c.locator('#tab-commits').click();
  await page.waitForTimeout(800);
  const nc = await c.locator('#panel-commits .cm-list > .commit').count();
  L(`commits: ${await c.locator('#commits-summary').textContent()} (${nc} cards)`);
  if (nc) {
    const card = c.locator('#panel-commits .cm-list > .commit').first();
    await card.locator('.cm-head').click();
    check((await card.locator('.cm-head').getAttribute('aria-expanded')) === 'true' && await painted(card.locator('.cf').first()), 'commits: first card expands by click, files painted');
  }
  await page.screenshot({ path: path.join(outDir, `${which}-3-commits.png`) });
  await c.locator('#tab-chat').click();
  const comp = c.locator('#composer');
  await comp.click();
  await comp.pressSequentially('#');
  await c.locator('#paths [role=option]').first().waitFor({ timeout: 15000 });
  const home = await c.locator('#paths [role=option]').evaluateAll(es => es.map(e => e.dataset.path));
  check(home.length > 1 && home.every(p => p.startsWith('v8/')), `# opens at v8: ${home.slice(0, 6).join(', ')}…`);
  await page.screenshot({ path: path.join(outDir, `${which}-4-hash-home.png`) });
  await comp.pressSequentially('../');
  await page.waitForTimeout(800);
  const rootRows = await c.locator('#paths [role=option]').evaluateAll(es => es.map(e => e.dataset.path));
  check(rootRows.includes('edp-pool') || rootRows.some(p => /^edp-pool\/?$/.test(p)), `#../ lists the git root: ${rootRows.slice(0, 8).join(', ')}`);
  await comp.pressSequentially('edp-p');
  await c.locator('#paths [role=option]', { hasText: 'edp-pool' }).first().waitFor({ timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, `${which}-5-hash-root.png`) });
  await page.keyboard.press('Enter');
  await page.waitForTimeout(300);
  const val = await comp.inputValue();
  check(val === '`edp-pool/` ', `pick inserts a root-relative token: ${JSON.stringify(val)}`);
  await page.screenshot({ path: path.join(outDir, `${which}-6-picked.png`) });
  await comp.fill(''); // never sent
  await browser.close();
  L(fails ? `FAIL (${fails})` : 'PASS');
  process.exit(fails ? 2 : 0);
})().catch(e => { L(`FAIL ${String(e.message || e).split('\n')[0].slice(0, 300)}`); process.exit(1); });
