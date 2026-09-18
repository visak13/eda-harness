import { test, expect } from './fixtures';
import fs from 'node:fs';
test.use({ boardFile: 'qa-modal-reachability' });
for (const [width, height] of [[320,568],[844,390]]) test(`short modal preview fully reachable ${width}`, async ({page}) => {
  await page.setViewportSize({width,height});
  await page.goto('/ui/epics?as=owner');
  await page.getByRole('button',{name:'New epic',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'New epic',exact:true});
  await dialog.evaluate(el=>{el.scrollTop=el.scrollHeight;});
  const preview=page.getByTestId('new-epic-preview');
  const p=(await preview.boundingBox())!;
  const actions=(await page.getByTestId('new-epic-create').locator('..').boundingBox())!;
  console.log('Full scroll preview/actions', {width,p,actions});
  fs.mkdirSync('e2e/evidence/qa-recheck',{recursive:true});
  await page.screenshot({path:`e2e/evidence/qa-recheck/modal-bottom-${width}.png`});
  expect(p.y).toBeGreaterThanOrEqual(12);
  expect(p.y+p.height).toBeLessThanOrEqual(actions.y+1);
  await page.getByTestId('new-epic-spawn').click({trial:true});
});
