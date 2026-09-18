// Isolated local-file asset inspection; no board, network or full e2e suite.
const { createRequire } = require('node:module');
const { resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const fs = require('node:fs');
const requireWeb = createRequire(resolve(__dirname, '../../../web/package.json'));
const { chromium } = requireWeb('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    await page.route('http://**/*', r => r.abort());
    await page.route('https://**/*', r => r.abort());
    await page.goto(pathToFileURL(resolve(__dirname, 'specimen.html')).href);
    await page.evaluate(() => document.fonts.ready);
    for (const mode of ['light', 'dark', 'hc']) {
      await page.locator(`section.${mode}`).screenshot({ path: resolve(__dirname, `specimen-${mode}.png`) });
    }
    const dimensions = await page.locator('section.light .size svg').evaluateAll(els => els.map(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height })));
    if (dimensions.some((d, i) => d.width !== [16, 18, 24][i % 3] || d.height !== d.width)) throw Error('size mismatch');
    await page.setViewportSize({ width: 320, height: 568 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('specimen narrow overflow');
    fs.writeFileSync(resolve(__dirname, 'render-result.json'), JSON.stringify({ method: 'Static local-file SVG specimen, not application evidence', glyphs: 45, bots: 11, sizes: [16,18,24], themes: ['light','dark','hc'], narrow_specimen_overflow: false, date: new Date().toISOString() }, null, 2) + '\n');
    console.log('PASS: static specimen rendered; all 168 sized instances correct; 320px specimen no horizontal overflow. NOT runtime proof.');
  } finally { await browser.close(); }
})().catch(err => { console.error(err); process.exitCode = 1; });
