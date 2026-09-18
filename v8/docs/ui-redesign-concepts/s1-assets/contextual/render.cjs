const {createRequire}=require('node:module');
const {resolve}=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=createRequire(resolve(__dirname,'../../../../web/package.json'))('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
  await page.route('http://**/*',r=>r.abort());await page.route('https://**/*',r=>r.abort());
  await page.goto(pathToFileURL(resolve(__dirname,'sample.html')).href);
  await page.evaluate(()=>document.fonts.ready);
  if(await page.locator('img').evaluateAll(imgs=>imgs.some(i=>!i.complete||!i.naturalWidth)))throw Error('Missing existing avatar');
  for(const [mode,name] of [['','epic'],['review-view','review'],['dark','dark'],['dark review-view','dark-review']]){
   await page.evaluate(m=>document.body.className=m,mode);
   await page.screenshot({path:resolve(__dirname,`contextual-${name}.png`)});
  }
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>document.body.className='');
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Narrow horizontal overflow');
  await page.screenshot({path:resolve(__dirname,'contextual-narrow.png'),fullPage:true});
  console.log('Rendered epic/review light/dark at 1440x900 and narrow epic at 390px; avatars loaded; no narrow horizontal overflow. NOT runtime evidence.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
