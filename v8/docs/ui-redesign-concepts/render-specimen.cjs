// Static reference rendering ONLY. Does not start or connect to any board service.
const { createRequire } = require('node:module');
const { resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const fs = require('node:fs');
const crypto = require('node:crypto');
const requireWeb = createRequire(resolve(__dirname, '../../web/package.json'));
const { chromium } = requireWeb('playwright');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
    await page.goto(pathToFileURL(resolve(__dirname,'revision3-clean-specimen.html')).href);
    await page.evaluate(() => document.fonts.ready);
    const images=[];
    for (const [mode,name] of [['','epic'],['usage-view','usage'],['review-view','review']]) {
      await page.evaluate(value => document.body.className=value,mode);
      const target=resolve(__dirname,`revision3-clean-${name}.png`);
      await page.screenshot({path:target});
      images.push({file:`revision3-clean-${name}.png`,sha256:crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')});
    }
    fs.writeFileSync(resolve(__dirname,'revision3-clean-provenance.json'),JSON.stringify({
      method:'Authored static HTML/CSS and Chromium screenshots; NOT image_gen output or running application',
      viewport:{width:1440,height:900},
      generated_style_reference:'revision3-retro-epic.png (finish rejected; provenance separately retained)',
      avatars:'Read-only exports of existing edp8.avatars human-01 and architect SVG functions; not new generated artwork',
      icons:'Hand-authored specimen SVG placeholders only; final generated/runtime icon family remains S1 work',
      content:'Synthetic illustrative content; no server/API interactions; controls are static',
      limitations:'Desktop visual specimen only; no interaction, responsiveness, accessibility or provider proof',images
    },null,2)+'\n');
    console.log(JSON.stringify({rendered:images.map(x=>x.file)}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
