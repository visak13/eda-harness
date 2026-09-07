import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const executable=process.env.CONCEPT_CHROME || 'C:\\Users\\aksou\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe';
const browser=spawn(executable,['--headless=new','--disable-gpu','--no-sandbox','--in-process-gpu','--disable-features=NetworkServiceSandbox','--no-first-run','--no-default-browser-check','--hide-scrollbars','--remote-debugging-pipe',`--user-data-dir=${path.join(root,'.render-profile')}`],{stdio:['ignore','ignore','pipe','pipe','pipe'],windowsHide:true});
browser.stderr.on('data',chunk=>process.stderr.write(chunk));
browser.on('exit',(code)=>{if(code)console.error('Browser exited',code)});
let buffer='',id=0;
const pending=new Map();
browser.stdio[4].on('data',chunk=>{buffer+=chunk.toString();let split;while((split=buffer.indexOf('\0'))>=0){const raw=buffer.slice(0,split);buffer=buffer.slice(split+1);if(!raw)continue;const m=JSON.parse(raw);if(pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result)}}});
function cdp(method,params={},sessionId){return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});browser.stdio[3].write(JSON.stringify({id:n,method,params,...(sessionId?{sessionId}:{})})+'\0')})}
const qa=[];
try{
 const {targetId}=await cdp('Target.createTarget',{url:'about:blank'});
 const {sessionId:s}=await cdp('Target.attachToTarget',{targetId,flatten:true});
 await cdp('Page.enable',{},s);
 for(const k of ['A','B','C']) for(const page of ['inbox','epics','tiles']){
  const stem=`concept-${k}-${page}`;
  await cdp('Emulation.setDeviceMetricsOverride',{width:page==='tiles'?1200:1440,height:900,deviceScaleFactor:1,mobile:false},s);
  await cdp('Page.navigate',{url:pathToFileURL(path.join(root,stem+'.html')).href},s);
  await new Promise(r=>setTimeout(r,180));
  await cdp('Runtime.evaluate',{expression:'document.fonts.ready',awaitPromise:true},s);
  const checks=await cdp('Runtime.evaluate',{expression:`JSON.stringify({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,fonts:document.fonts.status,epicRows:document.querySelectorAll('.epic-row').length,composer:document.querySelector('.composer')?.getBoundingClientRect().toJSON(),lastRow:document.querySelector('.epic-row:last-child')?.getBoundingClientRect().toJSON(),tileFooter:document.querySelector('.tile-footer')?.getBoundingClientRect().toJSON()})`,returnByValue:true},s);
  qa.push({file:stem+'.png',...JSON.parse(checks.result.value)});
  const shot=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,fromSurface:true},s);
  fs.writeFileSync(path.join(root,stem+'.png'),Buffer.from(shot.data,'base64'));
  console.log(stem+'.png');
 }
 fs.writeFileSync(path.join(root,'render-checks.json'),JSON.stringify(qa,null,2));
 await cdp('Browser.close');
}catch(err){console.error(err);browser.kill();process.exitCode=1}
