// usage: node shots.cjs <outdir> <tag>  — headless chromium against :8010 only
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const out = process.argv[2], tag = process.argv[3] || 'x';
const BASE = 'http://127.0.0.1:8010';
const REF = ['reference/cli/', 'reference/settings/', 'reference/rest-api/', 'reference/mcp-tools/',
  'reference/workflow-schema/', 'reference/models/'];
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const report = [];
  for (const scheme of ['slate', 'heronry-light']) {
    for (const w of [1280, 1440, 1920, 390]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: 1000 }, colorScheme: scheme === 'slate' ? 'dark' : 'light' });
      const page = await ctx.newPage();
      for (const p of [...REF, 'download/']) {
        await page.goto(`${BASE}/${p}`, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1500);
        const m = await page.evaluate(() => {
          const toc = document.querySelector('.md-sidebar--secondary');
          const tr = toc && getComputedStyle(toc).display !== 'none' && toc.getBoundingClientRect().width > 0
            ? toc.getBoundingClientRect() : null;
          const content = document.querySelector('.md-content').getBoundingClientRect();
          const tables = [...document.querySelectorAll('.md-content table')];
          const bad = [];
          tables.forEach((t, i) => {
            const r = t.getBoundingClientRect();
            const wrap = t.closest('.md-typeset__scrollwrap') || t.parentElement;
            const overflow = wrap.scrollWidth - wrap.clientWidth;
            const underToc = tr ? r.right > tr.left + 1 : false;
            if (overflow > 1 || underToc || r.right > content.right + 1) bad.push({ i, right: Math.round(r.right), overflow, underToc });
          });
          const docOverflow = document.documentElement.scrollWidth - document.documentElement.clientWidth;
          return { tables: tables.length, bad, toc: !!tr, docOverflow };
        });
        report.push({ scheme, w, page: p, ...m });
        if ((p === 'reference/settings/' || p === 'download/') && (w !== 1440 || true)) {
          const name = `${tag}-${p.replace(/\//g, '_').replace(/_$/, '')}-${w}-${scheme === 'slate' ? 'dark' : 'light'}.png`;
          if (p === 'download/') {
            const el = await page.$('.hy-downloads');
            if (el) await el.scrollIntoViewIfNeeded();
            await page.evaluate(() => window.scrollTo(0, Math.max(0, (document.querySelector('.hy-downloads')?.getBoundingClientRect().top || 0) + window.scrollY - 250)));
          } else {
            await page.evaluate(() => window.scrollTo(0, 0));
          }
          await page.screenshot({ path: path.join(out, name) });
        }
      }
      await ctx.close();
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(out, `${tag}-report.json`), JSON.stringify(report, null, 1));
  for (const r of report) if (r.bad.length || r.docOverflow > 0) console.log(r.scheme, r.w, r.page, 'toc=' + r.toc, 'docOverflow=' + r.docOverflow, JSON.stringify(r.bad.slice(0, 3)), r.bad.length);
  console.log('rows', report.length, 'problem rows', report.filter(r => r.bad.length || r.docOverflow > 0).length);
})().catch(e => { console.error(e); process.exit(1); });
