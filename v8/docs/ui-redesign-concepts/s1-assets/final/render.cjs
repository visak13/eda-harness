// Single owned local-file Chromium instance. No board service or full e2e suite.
const {createRequire}=require('node:module');const {resolve}=require('node:path');const {pathToFileURL}=require('node:url');const fs=require('node:fs');const crypto=require('node:crypto');
const {chromium}=createRequire(resolve(__dirname,'../../../../web/package.json'))('playwright');
(async()=>{const browser=await chromium.launch({headless:true});const shots=[];try{
 const p=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
 await p.route('http://**/*',r=>r.abort());await p.route('https://**/*',r=>r.abort());
 const shot=async(name,locator)=>{const path=resolve(__dirname,name);await(locator||p).screenshot({path,...(!locator?{fullPage:true}:{})});shots.push({file:name,sha256:crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex')});};
 await p.goto(pathToFileURL(resolve(__dirname,'packet.html')).href);await p.evaluate(()=>document.fonts.ready);
 if(await p.locator('img').evaluateAll(imgs=>imgs.some(i=>!i.complete||!i.naturalWidth)))throw Error('Missing identity asset');
 for(const [mode,name]of[['','epic'],['review-view','review'],['dark review-view','dark-review'],['work-view','work'],['dark work-view','dark-work']]){
  await p.evaluate(m=>document.body.className=m,mode);await shot(`packet-${name}.png`);
  if(mode.includes('work')){
   const overlap=await p.evaluate(()=>document.querySelector('.work-table').getBoundingClientRect().bottom>document.querySelector('.composer').getBoundingClientRect().top);
   if(overlap)throw Error('Work table overlaps composer');
  }
 }
 await p.setViewportSize({width:390,height:844});await p.evaluate(()=>document.body.className='');
 if(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Narrow overflow');await shot('packet-narrow.png');
 await p.setViewportSize({width:1440,height:1000});await p.goto(pathToFileURL(resolve(__dirname,'sizes.html')).href);
 const sizeCounts={};
 for(const t of ['light','dark','hc']){
  await shot(`sizes-${t}.png`,p.locator(`section.${t}`));
  const dims=await p.locator(`section.${t} .sizes svg`).evaluateAll(els=>els.map(e=>({w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height})));
  if(dims.length!==171||dims.some((d,i)=>d.w!==[16,18,24][i%3]||d.h!==d.w))throw Error(`${t} size mismatch`);
  sizeCounts[t]=dims.length;
 }
 fs.writeFileSync(resolve(__dirname,'render-evidence.json'),JSON.stringify({kind:'STATIC asset/context specimen, not running application',rendered_at:new Date().toISOString(),size_instances_per_theme:sizeCounts,sizes:[16,18,24],narrow_width:390,narrow_overflow:false,work_composer_overlap:false,shots},null,2)+'\n');console.log('PASS 9 local screenshots, all171 sizes/theme, no Work/composer overlap or narrow horizontal overflow. Browser closes in finally.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
