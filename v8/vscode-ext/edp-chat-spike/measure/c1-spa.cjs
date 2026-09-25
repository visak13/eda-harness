// C1: the spike view through the live SPA Code tab (/ui/code iframe on :9400). node c1-spa.cjs <chromium|stockff> <outdir>
const path = require('node:path');
const fs = require('node:fs');
const WEB = 'C:/Projects/Learning/eda-base3/v8/web/node_modules';
const which = process.argv[2], outDir = process.argv[3];
const pw = require(`${WEB}/playwright-core`);
fs.mkdirSync(outDir, { recursive: true });
const L = (s) => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(path.join(outDir, `${which}-spa.log`), l + '\n'); };
(async () => {
  const browser = which === 'stockff'
    ? await pw.firefox.launch({ channel: 'moz-firefox', executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe', headless: true })
    : await pw.chromium.launch({ headless: true, executablePath: `${process.env.LOCALAPPDATA}/ms-playwright/chromium-1234/chrome-win64/chrome.exe` });
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
  L(`browser ${which} ${browser.version()}`);
  await page.goto('http://127.0.0.1:9400/ui/code', { waitUntil: 'domcontentloaded' });
  // sign in as this seat itself (header-only agent), never with a human's token
  const who = page.getByText('Identity needed');
  if (await who.waitFor({ timeout: 8000 }).then(() => true, () => false)) {
    await page.waitForTimeout(1500); const inp = page.locator('input').first(); await inp.click(); await inp.fill(''); await inp.pressSequentially('engineer.s-a8f1b90d2f'); L(`participant field = ${await inp.inputValue()}`);
    await page.getByRole('button', { name: 'Continue' }).click();
    L('signed in to the SPA as engineer.s-a8f1b90d2f (no token)');
  }
  const frameEl = page.locator('iframe[data-testid="code-frame"]');
  const got = await frameEl.waitFor({ timeout: 30000 }).then(() => true, () => false);
  L(`code-frame present=${got} src=${got ? await frameEl.getAttribute('src') : null}`);
  if (!got) { await page.screenshot({ path: path.join(outDir, `${which}-spa.png`) }); await browser.close(); return; }
  const root = page.frameLocator('iframe[data-testid="code-frame"]');
  await root.locator('div.monaco-workbench').waitFor({ timeout: 60000 });
  await page.waitForTimeout(5000);
  await root.locator('div.monaco-workbench').click({ position: { x: 600, y: 400 } }).catch(() => {});
  await page.keyboard.press('F1');
  await root.locator('.quick-input-widget input').fill('>Focus on Thread (spike) View');
  await root.locator('.quick-input-widget .monaco-list-row', { hasText: 'Focus on Thread (spike) View' }).first().click({ timeout: 15000 });
  let status = null; const t0 = Date.now();
  while (Date.now() - t0 < 20000 && !(status || '').startsWith('round-trip')) {
    for (const f of page.frames()) { try { status = (await f.locator('#status').textContent({ timeout: 300 })) || status; } catch {} }
    await page.waitForTimeout(500);
  }
  L(`spa view status=${JSON.stringify(status)}`);
  await page.screenshot({ path: path.join(outDir, `${which}-spa.png`) });
  await browser.close();
})().catch((e) => { L(`FATAL ${e.stack}`); process.exit(1); });
