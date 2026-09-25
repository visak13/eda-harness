// C14 live check on the running Code tab (:9410) at 1920x1080: sign in as this seat (EDP8_PARTICIPANT or
// EDP_HANDLE + EDP8_TOKEN from env, typed into the input box, never logged), open the epic, and switch the
// scope picker epic -> story -> epic on the Changes tab (s-8cc2cc80b3): the first group's title ("This
// epic" / "This story"), its rows and the tab badge follow the pick; a screenshot at each step.
// node c14-live.cjs <chromium|stockff> <outdir> <epicTitle> <storyId> [storyId...]
const path = require('node:path');
const fs = require('node:fs');
const WEB = path.resolve(__dirname, '../../../web/node_modules');
const [which, outDir, epicTitle, ...storyIds] = process.argv.slice(2);
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
  const ph = await c.locator('#composer').getAttribute('placeholder');
  check(/Ctrl\+Enter to send$/.test(ph), `composer hint: ${ph}`);
  await c.locator('#tab-changes').click();
  await c.locator('#changes-summary').waitFor({ timeout: 10000 });
  const read = async () => {
    await page.waitForTimeout(2500); // the thread load + anchors settle
    const t = c.locator('#changes-scoped-toggle');
    if ((await t.count()) && (await t.getAttribute('aria-expanded')) !== 'true') await t.click();
    const all = c.locator('#changes-all-toggle');
    if ((await all.count()) && (await all.getAttribute('aria-expanded')) === 'true') await all.click();
    await page.waitForTimeout(300);
    return {
      crumb: (await c.locator('#crumb-current').textContent()).trim(),
      title: (await t.count()) ? (await t.locator('.group-title').textContent()) : null,
      count: (await t.count()) ? (await t.locator('.group-count').textContent()) : null,
      rows: await c.locator('#changes-scoped .cf').evaluateAll(es => es.map(e => e.dataset.path)),
      badge: (await c.locator('#tab-changes .tab-badge').count()) ? await c.locator('#tab-changes .tab-badge').textContent() : null,
      aria: await c.locator('#tab-changes').getAttribute('aria-label'),
      more: (await all.count()) ? (await all.locator('.group-count').textContent()) : null,
    };
  };
  const snap = async (name, s) => { L(`${name}: ${JSON.stringify(s)}`); await page.screenshot({ path: path.join(outDir, `${which}-${name}.png`) }); };
  const epic = await read(); await snap('1-epic', epic);
  check(epic.title === 'This epic', `epic scope group: ${epic.title}`);
  let i = 2;
  for (const id of storyIds) {
    if ((await c.locator('#stories-toggle').getAttribute('aria-expanded')) !== 'true') await c.locator('#stories-toggle').click();
    await c.locator(`.story[data-id="${id}"]`).click();
    await page.waitForFunction(() => true);
    await c.locator('#crumb-epic').waitFor({ state: 'visible', timeout: 15000 });
    const s = await read(); await snap(`${i++}-story-${id}`, s);
    check(s.title === 'This story', `story ${id} group: ${s.title}`);
    check(s.badge !== epic.badge || JSON.stringify(s.rows) !== JSON.stringify(epic.rows), `story ${id}: rows/badge differ from the epic's (${s.badge} vs ${epic.badge})`);
    check(s.rows.every(r => epic.rows.includes(r)), `story ${id}: its rows are a subset of the epic's`);
  }
  await c.locator('#crumb-epic').click();
  await c.locator('#crumb-current', { hasText: epicTitle }).waitFor({ timeout: 15000 });
  const back = await read(); await snap(`${i}-epic-again`, back);
  check(back.title === 'This epic' && JSON.stringify(back.rows) === JSON.stringify(epic.rows), 'back at the epic: the epic group again');
  await browser.close();
  L(fails ? `FAIL (${fails})` : 'PASS');
  process.exit(fails ? 2 : 0);
})().catch(e => { L(`FAIL ${String(e.message || e).split('\n')[0].slice(0, 300)}`); process.exit(1); });
