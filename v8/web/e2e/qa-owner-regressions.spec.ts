import {test,expect,EPIC} from './fixtures';
test.use({boardFile:'qa-owner-regressions'});
test('status tooltip stays near its trigger instead of viewport bottom-left',async({page})=>{
 await page.goto(`/ui/epic/${EPIC()}?as=owner`);
 const status=page.getByText('Drafted',{exact:true}).first();await status.hover();
 const anchor=(await status.boundingBox())!;const tip=(await page.getByRole('tooltip').filter({visible:true}).boundingBox())!;
 // Allow any nearby side and a broad gap; this rejects only detached screen-corner help.
 const gapY=Math.max(anchor.y-(tip.y+tip.height),tip.y-(anchor.y+anchor.height),0);
 const gapX=Math.max(anchor.x-(tip.x+tip.width),tip.x-(anchor.x+anchor.width),0);
 expect(Math.max(gapX,gapY)).toBeLessThan(100);
});
test('expanded composer offers more editing height or a user resize affordance',async({page})=>{
 await page.goto(`/ui/epic/${EPIC()}?as=owner`);const text=page.getByTestId('composer-text');await text.fill('Keep draft');
 const before=(await text.boundingBox())!;await page.getByTestId('composer-expand').click();await expect(page.getByRole('dialog')).toBeVisible();
 const after=(await text.boundingBox())!;const resize=await text.evaluate(e=>getComputedStyle(e).resize);
 await expect(text).toHaveValue('Keep draft');expect(after.height>before.height+40||resize==='vertical'||resize==='both').toBe(true);
});
