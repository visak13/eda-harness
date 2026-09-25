// C1 spike measurement: live :9410, one browser per run. node c1-measure.cjs <chromium|firefox> <outdir> [steps]
const path = require('node:path');
const fs = require('node:fs');
const WEB = 'C:/Projects/Learning/eda-base3/v8/web/node_modules';
const which = process.argv[2];
const outDir = process.argv[3];
const steps = (process.argv[4] || 'view,inline,panel').split(',');
const pw = which === 'stockff' ? require(`${WEB}/playwright-core`) : require(`${WEB}/playwright/node_modules/playwright-core`)  // its browsers (chromium-1234, firefox-1538) are the installed ones;
fs.mkdirSync(outDir, { recursive: true });
const logf = path.join(outDir, `${which}.log`);
const L = (s) => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + '\n'); };

(async () => {
  const browser = which === 'stockff'
    // the owner's browser build (stock Firefox, WebDriver BiDi), on a temporary profile, never the owner's
    ? await pw.firefox.launch({ channel: 'moz-firefox', executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe', headless: true })
    : await pw[which].launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  let page = await ctx.newPage();
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) L(`console.${m.type()} [${m.location()?.url?.slice(0, 80)}] ${m.text().slice(0, 300)}`); });
  page.on('pageerror', (e) => L(`pageerror ${e.message.slice(0, 300)}`));
  page.on('requestfailed', (r) => L(`requestfailed ${r.url().slice(0, 160)} ${r.failure()?.errorText}`));
  L(`browser ${which} ${browser.version()}`);
  await page.goto('http://127.0.0.1:9410/?folder=/c:/Projects/Learning/eda-base3/v8', { waitUntil: 'domcontentloaded' });
  await page.locator('div.monaco-workbench').waitFor({ timeout: 60000 });
  L('workbench visible');
  await page.waitForTimeout(4000); // let extensions activate (spike is onStartupFinished)

  async function run(title) {
    await page.locator('div.monaco-workbench').click({ position: { x: 700, y: 400 } }).catch(() => {});
    await page.keyboard.press('F1');
    const q = page.locator('.quick-input-widget');
    await q.locator('input').fill(`>${title}`);
    await q.locator('.monaco-list-row', { hasText: title }).first().click({ timeout: 15000 });
    L(`ran command: ${title}`);
  }
  async function readWebview(label, container) {
    // the webview is iframe.webview (host) > iframe#active-frame (content)
    const deadline = Date.now() + 20000;
    let status = null, variant = null, ua = null;
    while (Date.now() < deadline) {
      for (const f of page.frames()) {
        try {
          const s = await f.locator('#status').textContent({ timeout: 500 });
          if (s) { status = s; variant = await f.locator('#variant').textContent(); ua = await f.locator('#ua').textContent(); }
        } catch { /* not this frame */ }
      }
      if (status && status.startsWith('round-trip')) break;
      await page.waitForTimeout(500);
    }
    L(`${label}: status=${JSON.stringify(status)} variant=${variant} ua=${ua}`);
    if (container) {
      const inAux = await page.locator('.part.auxiliarybar iframe.webview').count();
      const box = await page.locator('.part.auxiliarybar').boundingBox().catch(() => null);
      const ed = await page.locator('.part.editor').boundingBox().catch(() => null);
      L(`${label}: webviews in .part.auxiliarybar=${inAux} auxbar=${JSON.stringify(box)} editor=${JSON.stringify(ed)}`);
    }
    await page.screenshot({ path: path.join(outDir, `${which}-${label}.png`) });
    return status;
  }

  const quick = page.locator('.quick-input-widget');
  async function answer(text) { await quick.locator('input').fill(text); await page.keyboard.press('Enter'); }
  const S = {};
  S['view'] = async () => {
    await run('Focus on Thread (spike) View');
    await readWebview('view-external', true);
  };
  S['inline'] = async () => {
    await run('Spike: assets inline');
    await readWebview('view-inline', true);
    if (!process.env.KEEP_INLINE) await run('Spike: assets via asWebviewUri');
  };
  S['panel'] = async () => {
    await run('Spike: open WebviewPanel beside');
    await readWebview('panel-beside', false);
  };

  S['reload'] = async () => {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('div.monaco-workbench').waitFor({ timeout: 60000 });
    await page.waitForTimeout(6000);
    L('reloaded; no command run');
    await readWebview('after-reload', true);
  };
  S['pad'] = async () => {
    for (const kb of (process.env.PAD_KB || '1024,8192').split(',')) {
      await run('Spike: assets inline, padded'); await answer(kb);
      await readWebview(`inline-pad-${kb}kb`, false);
    }
    await run('Spike: assets inline');
  };
  S['feed'] = async () => {
    await run('Spike: feed probe'); await answer('engineer.s-a8f1b90d2f'); await answer('');
    await page.waitForTimeout(3000);
    const text = `C1 feed probe ${which} ${new Date().toISOString()}`;
    const t0 = Date.now();
    const r = await fetch('http://127.0.0.1:9400/v1/messages', { method: 'POST',
      headers: { 'X-Participant': 'engineer.s-a8f1b90d2f', 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket_id: 's-a8f1b90d2f', kind: 'note', text }) });
    const j = await r.json(); L(`posted ${j.value?.id} HTTP ${r.status} created_at=${j.value?.created_at}`);
    let seen = null;
    while (Date.now() - t0 < 15000 && !seen) {
      for (const f of page.frames()) { try { const n = await f.locator('#feed li', { hasText: text }).count(); if (n) seen = Date.now() - t0; } catch {} }
      if (!seen) await page.waitForTimeout(100);
    }
    L(`feed: board message visible in the webview after ${seen ?? 'NOT SEEN (15s)'} ms`);
    await page.screenshot({ path: path.join(outDir, `${which}-feed.png`) });
    await run('Spike: stop feed probe');
  };
  S['diff'] = async () => {
    await run('Spike: diff probe (one file)');
    const ok = await page.locator('.monaco-diff-editor').first().waitFor({ timeout: 20000 }).then(() => true, () => false);
    await page.waitForTimeout(1500);
    L(`diff: .monaco-diff-editor visible=${ok} tab=${await page.locator('.tab.active').first().textContent().catch(() => null)}`);
    await page.screenshot({ path: path.join(outDir, `${which}-diff.png`) });
  };
  S['changes'] = async () => {
    await run('Spike: changes probe (multi-diff)');
    const ok = await page.locator('.multiDiffEditor, .monaco-multi-diff-editor').first().waitFor({ timeout: 20000 }).then(() => true, () => false);
    await page.waitForTimeout(2500);
    L(`changes: multi-diff editor visible=${ok} tab=${await page.locator('.tab.active').first().textContent().catch(() => null)}`);
    await page.screenshot({ path: path.join(outDir, `${which}-changes.png`) });
  };
  S['hold'] = async () => {
    const ms = Number(process.env.HOLD_MS || 30000);
    L(`holding ${ms}ms`); await page.waitForTimeout(ms);
    await readWebview('view-after-hold', true);
  };
  S.md = async () => {
    await page.keyboard.press('Control+P'); await quick.locator('input').fill('CLAUDE.md');
    await quick.locator('.monaco-list-row', { hasText: 'CLAUDE.md' }).first().click({ timeout: 15000 });
    await page.waitForTimeout(1500);
    await run('Markdown: Open Preview to the Side');
    let ok = false; const t0 = Date.now();
    while (!ok && Date.now() - t0 < 20000) {
      for (const f of page.frames()) { if (f.url().includes('fake.html')) { try { const t = await f.locator('body').innerText({ timeout: 500 }); if (/Environment/.test(t)) ok = true; } catch {} } }
      if (!ok) await page.waitForTimeout(500);
    }
    L(`md preview rendered=${ok} (fake.html frames=${page.frames().filter(f => f.url().includes('fake.html')).length})`);
    await page.screenshot({ path: path.join(outDir, `${which}-md-preview.png`) });
  };
  S.newpage = async () => {
    const p2 = await ctx.newPage(); await page.close();
    page = p2; await page.goto('http://127.0.0.1:9410/?folder=/c:/Projects/Learning/eda-base3/v8', { waitUntil: 'domcontentloaded' });
    await page.locator('div.monaco-workbench').waitFor({ timeout: 60000 }); await page.waitForTimeout(6000); L('new tab, same profile');
  };
  S.frames = async () => { for (const f of page.frames()) L(`frame ${f.url().slice(0, 150)}`); };
  S.focus = async () => { await run('Focus on Thread (spike) View'); await readWebview('focus', true); };
  S.shot = async () => { await readWebview('shot', true); };
  for (const st of steps) { L(`== step ${st}`); await S[st](); }
  await browser.close();
  L('done');
})().catch((e) => { L(`FATAL ${e.stack}`); process.exit(1); });
