// C16 live check on the running Code tab (:9410, edp-code 0.9.0) at 1920x1080 (s-579fa02cca, architect m-a47cb14106):
// sign in as this seat (EDP8_PARTICIPANT or EDP_HANDLE + EDP8_TOKEN from env, typed into the input box, never logged),
// open the epic, the Docs tab lists its docs; the design opens in the reader, full screen (zen); Compare v12 then v11
// opens the source diff (v11 on the left), full screen. A screenshot at each step; checks logged. Read-only: no write.
// node c16-live.cjs <chromium|stockff> <outdir> <epicTitle> <docId> <newer> <older>
const path = require('node:path');
const fs = require('node:fs');
const WEB = path.resolve(__dirname, '../../../web/node_modules');
const [which, outDir, epicTitle, docId, newer, older] = process.argv.slice(2);
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
  const shot = async name => page.screenshot({ path: path.join(outDir, `${which}-${name}.png`) });
  const activeTab = () => page.locator('.tabs-container .tab.active');
  const titleAction = re => page.locator('.editor-group-container.active .editor-actions').getByRole('button', { name: re });
  const hidden = async sel => !(await page.locator(sel).isVisible().catch(() => false));
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
  const aux = await page.locator('.part.auxiliarybar').boundingBox();
  await page.mouse.move(aux.x + 1, 540); await page.mouse.down(); await page.mouse.move(1920 - 712, 540, { steps: 10 }); await page.mouse.up();
  await page.locator('.notifications-toasts .notification-toast').first().waitFor({ state: 'hidden', timeout: 20000 }).catch(() => {});
  // the Docs tab
  await c.locator('#tab-docs').click();
  const drow = c.locator(`#panel-docs .dc-row[data-id="${docId}"]`);
  await drow.waitFor({ timeout: 30000 });
  const rows = await c.locator('#panel-docs .dc-row').evaluateAll(es => es.map(e => `${e.dataset.id} ${e.querySelector('.dc-type')?.textContent} ${e.querySelector('.dc-version')?.textContent} ${e.querySelector('.dc-status')?.textContent}`));
  L(`docs: ${rows.length} rows: ${JSON.stringify(rows)}`);
  check(rows.some(r => r.startsWith(`${docId} design v${newer}`)), `${docId} listed as design v${newer}`);
  await shot('1-docs-tab');
  // the reader, full screen
  await drow.locator('.dc-open').click();
  await activeTab().filter({ hasText: `· v${newer}` }).waitFor({ timeout: 30000 });
  let rd;
  for (let i = 0; i < 60 && !rd; i++) {
    for (const f of page.frames()) if ((await f.title().catch(() => '')) === `EDP ${docId} v${newer}` && await f.locator('#doc h2').count().catch(() => 0)) rd = f;
    if (!rd) await page.waitForTimeout(500);
  }
  check(!!rd, `the reader renders ${docId} v${newer}`);
  if (rd) {
    const h2 = await rd.locator('#doc h2').count(), toc = await rd.locator('.rd-toc a').count(), opts = await rd.locator('#rd-version option').count();
    const ls = await rd.locator('#doc [data-ls]').count();
    L(`reader: ${h2} h2, ${toc} outline links, ${opts} versions, ${ls} elements carry data-ls`);
    check(h2 > 5 && toc > 5 && opts === Number(newer) && ls > 50, 'rendered markdown with an outline, a version picker and source line stamps');
  }
  await titleAction(/^Full screen/).click();
  await page.waitForTimeout(1200);
  check(await hidden('.part.sidebar') && await hidden('.part.auxiliarybar') && await hidden('.part.activitybar'), 'full screen: side bars and activity bar hidden');
  await shot('2-reader-fullscreen');
  if (rd) { await rd.locator('#doc h2').nth(5).scrollIntoViewIfNeeded(); await page.waitForTimeout(400); await shot('3-reader-fullscreen-scrolled'); }
  await cmd('View: Toggle Zen Mode');
  await page.waitForTimeout(1000);
  check(!(await hidden('.part.auxiliarybar')), 'full screen off: the chat is back');
  // compare newer ↔ older from the Docs row
  await c.locator('#tab-docs').click();
  await drow.locator('.act', { hasText: 'Compare' }).click();
  const pick = async v => { const r = quick.locator('.monaco-list-row').filter({ has: page.locator('.label-name', { hasText: new RegExp(`^v${v}$`) }) }).first(); await r.waitFor({ timeout: 15000 }); await r.click(); };
  await pick(newer); await pick(older);
  await activeTab().filter({ hasText: `v${older} ↔ v${newer}` }).waitFor({ timeout: 30000 });
  const diff = page.locator('.editor-group-container.active .monaco-diff-editor');
  await diff.locator('.modified .view-lines').waitFor({ timeout: 20000 });
  const marks = async () => [await diff.locator('.line-insert, .char-insert').count(), await diff.locator('.line-delete, .char-delete').count()];
  let [ins, del] = await marks();
  for (let i = 0; i < 20 && ins + del === 0; i++) { await page.waitForTimeout(500); [ins, del] = await marks(); }
  L(`diff tab "${(await activeTab().textContent()).trim()}": ${ins} insert and ${del} delete decorations in view`);
  check(ins + del > 0, `v${older} ↔ v${newer} source diff shows changes`);
  await shot('4-diff');
  await cmd('View: Toggle Zen Mode');
  await page.waitForTimeout(1200);
  // zen re-lays the diff out side by side; wait until both sides paint text again
  // the relayout can leave the viewport past the painted lines: step to the first change with the title bar's Next Change
  await titleAction(/^Next Change/).click({ timeout: 5000 }).catch(e => L(`next change: ${e.message.split('\n')[0]}`));
  await page.waitForTimeout(800);
  for (let i = 0; i < 30 && !((await diff.locator('.modified .view-line').count() > 5) && (await diff.locator('.original .view-line').count())); i++) await page.waitForTimeout(500);
  await page.waitForTimeout(1500);
  [ins, del] = await marks();
  L(`full screen diff: ${await diff.locator('.original .view-line').count()} original / ${await diff.locator('.modified .view-line').count()} modified lines painted, ${ins} insert and ${del} delete decorations`);
  check(ins + del > 0, 'full screen diff shows the changes side by side');
  await shot('5-diff-fullscreen');
  await cmd('View: Toggle Zen Mode');
  await page.waitForTimeout(800);
  L(fails ? `${fails} check(s) FAILED` : 'all checks ok');
  await browser.close();
  process.exit(fails ? 1 : 0);
})().catch(e => { L(`error ${e.message.split('\n')[0]}`); process.exit(2); });
