// C15 live check on the running Code tab (:9410) at 1920x1080 (s-e14d316891, architect m-b698d0b92c): sign in
// as this seat (EDP8_PARTICIPANT or EDP_HANDLE + EDP8_TOKEN from env, typed into the input box, never logged),
// open the epic and the Inbox tab. look: the question waits, the badge counts the rows. answer: the same, then
// answer it from its row (text from C15_ANSWER, Ctrl+Enter) and see the row leave; badges logged before/after.
// gone: the question is no longer listed. A screenshot at each step.
// node c15-live.cjs <chromium|stockff> <outdir> <epicTitle> <look|answer|gone> <questionMsgId>
const path = require('node:path');
const fs = require('node:fs');
const WEB = path.resolve(__dirname, '../../../web/node_modules');
const [which, outDir, epicTitle, mode, qid] = process.argv.slice(2);
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
  const inbox = async () => {
    await c.locator('#tab-inbox').click();
    await c.locator('#inbox-summary').waitFor({ timeout: 15000 });
    await page.waitForTimeout(3000); // the decisions read settles
    const badge = async id => (await c.locator(`#tab-${id} .tab-badge`).count()) ? (await c.locator(`#tab-${id} .tab-badge`).textContent()) : null;
    return {
      crumb: (await c.locator('#crumb-current').textContent()).trim(),
      summary: (await c.locator('#inbox-summary').textContent()).trim(),
      keys: await c.locator('.ib-row').evaluateAll(es => es.map(e => e.dataset.key)),
      badges: { chat: await badge('chat'), changes: await badge('changes'), commits: await badge('commits'), inbox: await badge('inbox') },
      aria: await c.locator('#tab-inbox').getAttribute('aria-label'),
    };
  };
  const snap = async (name, s) => { L(`${name}: ${JSON.stringify(s)}`); await page.screenshot({ path: path.join(outDir, `${which}-${name}.png`) }); };
  const key = `q:${qid}`, rowq = c.locator(`.ib-row[data-key="${key}"]`);
  const before = await inbox(); await snap(`1-${mode}`, before);
  if (mode === 'gone') {
    check(!before.keys.includes(key), `${key} has left the Inbox`);
  } else {
    check(before.keys.includes(key), `${key} waits in the Inbox`);
    check(before.badges.inbox === String(before.keys.length), `Inbox badge ${before.badges.inbox} counts the ${before.keys.length} rows`);
  }
  if (mode === 'answer') {
    const text = process.env.C15_ANSWER;
    if (!text) throw new Error('C15_ANSWER is empty');
    await rowq.locator('.ib-text').fill(text);
    await page.waitForTimeout(300);
    await snap('2-typed', await inbox());
    await rowq.locator('.ib-text').press('Control+Enter');
    await rowq.waitFor({ state: 'detached', timeout: 20000 });
    await page.waitForTimeout(2000);
    const after = await inbox(); await snap('3-answered', after);
    check(!after.keys.includes(key), `${key} left the Inbox after the answer`);
    for (const k of ['chat', 'changes', 'commits', 'inbox'])
      L(`badge ${k}: ${before.badges[k]} -> ${after.badges[k]}`);
  }
  await browser.close();
  L(fails ? `FAIL (${fails})` : 'PASS');
  process.exit(fails ? 2 : 0);
})().catch(e => { L(`FAIL ${String(e.message || e).split('\n')[0].slice(0, 300)}`); process.exit(1); });
