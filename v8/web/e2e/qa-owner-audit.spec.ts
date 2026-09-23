import { test, expect, EPIC, BASE } from './fixtures';
import fs from 'node:fs';
test.use({ boardFile: 'qa-owner-audit' });
test('owner findings: inspect interactive surfaces and retain measurements', async ({page,request}) => {
  test.setTimeout(60000); page.setDefaultTimeout(10000);
  const dir='e2e/evidence/qa-owner-audit';fs.mkdirSync(dir,{recursive:true});
  const evidence:Record<string,unknown>={};
  await page.setViewportSize({width:1440,height:900});
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  const text=page.getByTestId('composer-text');await text.fill('Independent QA draft');
  const status=page.getByLabel('Breadcrumb').getByText('Drafted',{exact:true});
  await status.hover();
  const tip=page.getByRole('tooltip').filter({visible:true});
  evidence.tooltip={trigger:await status.boundingBox(),tips:await tip.allTextContents(),box:await tip.first().boundingBox()};
  await page.screenshot({path:`${dir}/tooltip.png`});
  await page.mouse.move(1000,800);
  const inline=await text.boundingBox();
  await page.getByRole('button',{name:'Expand the composer into the drawer'}).click();
  evidence.expansion={inline,expanded:await text.boundingBox(),resize:await text.evaluate(el=>getComputedStyle(el).resize),drawer:await page.getByRole('dialog').boundingBox()};
  await page.screenshot({path:`${dir}/expanded.png`});
  await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Files & evidence',exact:true}).click();
  const files=page.getByRole('dialog',{name:'Files & evidence',exact:true});
  evidence.emptyFiles=await files.innerText();await page.screenshot({path:`${dir}/files-empty.png`});
  await page.keyboard.press('Escape');
  await page.locator('#work-details > summary').click();
  await page.locator('#work-details').scrollIntoViewIfNeeded();
  await page.screenshot({path:`${dir}/process.png`});
  const rail=page.locator('details').filter({has:page.locator('summary').filter({hasText:'Actions & work details'})}).first();
  await rail.locator(':scope > summary').click();
  for(const detail of await rail.locator('details').all()) await detail.evaluate(el=>{(el as HTMLDetailsElement).open=true;});
  evidence.legacyLinks=await rail.getByRole('link').evaluateAll(els=>els.map(el=>({label:el.textContent,href:el.getAttribute('href')})));
  evidence.legacyButtons=await rail.getByRole('button').allTextContents();
  await rail.scrollIntoViewIfNeeded();await page.screenshot({path:`${dir}/legacy-controls.png`,fullPage:true});
  await page.evaluate(()=>scrollTo(0,0));
  const hover=[];
  for(const label of ['Files & evidence','History']){ // S19: Usage removed from the rail
    const el=page.getByRole('button',{name:label,exact:true});
    await page.mouse.move(0,0);const before=await el.evaluate(e=>{const c=getComputedStyle(e);return [c.backgroundColor,c.color,c.borderColor,c.boxShadow]});
    await el.hover();await page.waitForTimeout(200);const after=await el.evaluate(e=>{const c=getComputedStyle(e);return [c.backgroundColor,c.color,c.borderColor,c.boxShadow]});hover.push({label,before,after});
  }
  evidence.hover=hover;
  await expect(page.getByRole('button',{name:'Usage',exact:true})).toHaveCount(0); // S19: only show what works
  await text.fill('Attachment presentation probe');
  await page.locator('input[type=file]').setInputFiles({name:'qa-evidence.txt',mimeType:'text/plain',buffer:Buffer.from('QA attachment body')});
  await expect(page.getByTestId('composer-send')).toBeEnabled();
  const sent=page.waitForResponse(r=>r.url().endsWith('/v1/messages')&&r.request().method()==='POST');
  await page.getByTestId('composer-send').click();const response=await sent;
  evidence.attachmentRequest=response.request().postDataJSON();evidence.attachmentResponse=await response.json();
  await page.getByTestId('thread').getByText('Attachment presentation probe',{exact:false}).waitFor();
  evidence.attachmentRendered=await page.getByTestId('thread').innerText();
  const artifactId=(evidence.attachmentRequest as {artifacts:string[]}).artifacts[0];
  const content=await request.get(`${BASE()}/v1/artifacts/${artifactId}/content`,{headers:{'X-Participant':'arch'}});
  evidence.recipientRetrieval={status:content.status(),body:await content.text()};
  await page.screenshot({path:`${dir}/attachment.png`,fullPage:true});
  await page.getByRole('button',{name:'Files & evidence',exact:true}).click();
  await page.waitForTimeout(1000); // Bounded observation: SSE keeps networkidle permanently pending.
  evidence.populatedFiles=await page.getByRole('dialog',{name:'Files & evidence',exact:true}).innerText();
  await page.screenshot({path:`${dir}/files-populated.png`});await page.keyboard.press('Escape');
  const links=(evidence.legacyLinks as {href:string|null}[]).filter(x=>x.href?.startsWith('/ui/library'));
  const checks=[];
  for(const link of links){await page.goto(link.href!);await expect(page.locator('main')).not.toContainText('Loading…');checks.push({href:link.href,url:page.url(),main:(await page.locator('main').innerText()).slice(0,1800)});}
  evidence.legacyDestinations=checks;
  fs.writeFileSync(`${dir}/measurements.json`,JSON.stringify(evidence,null,2));
  console.log('owner audit measurements retained',Object.keys(evidence));
});
