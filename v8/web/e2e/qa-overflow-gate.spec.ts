// qa gate (epic-44a0576511 final sweep, finding 26): no element may extend past the viewport on the
// epic page or under the design viewer at 1440 / 844 / 320; on failure the widest elements are named.
import { test, expect, BASE } from './fixtures';
test.use({ boardFile: 'qa-overflow-gate' });

async function offenders(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const iw = innerWidth; const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const r = el.getBoundingClientRect();
      if (r.right > iw + 1 && r.width > 0 && r.height > 0) {
        const id = el.dataset.testid ? `[${el.dataset.testid}]` : '';
        out.push(`${el.tagName.toLowerCase()}${id}.${String(el.className).slice(0, 60)} right=${Math.round(r.right)} w=${Math.round(r.width)} sw=${el.scrollWidth}`);
      }
    }
    return { scrollWidth: document.documentElement.scrollWidth, innerWidth: iw, top: out.slice(0, 25) };
  });
}

test('epic page with conversation at 320', async ({ page, request }) => {
  async function post(path: string, data: unknown, actor = 'arch', method = 'POST') {
    const r = await request.fetch(`${BASE()}${path}`, { method, headers: { 'X-Participant': actor }, data });
    expect(r.ok(), await r.text()).toBe(true); return (await r.json()).value;
  }
  const epic = await post('/v1/tickets', { kind: 'epic', work_type: 'feature', title: 'Board improvements' }, 'owner');
  const doc = await post('/v1/docs', { doc_type: 'design', title: 'QA reviewed design', scope: epic.id, body_md: '# Current design' });
  await post('/v1/criteria', { ticket_id: epic.id, text: 'review', check: 'command' });
  await post(`/v1/tickets/${epic.id}`, { design_ref: doc.id }, 'arch', 'PATCH');
  const gate = await post(`/v1/gates/${epic.id}/design_signoff/open`, {});
  await post('/v1/messages', { ticket_id: epic.id, to: 'arch', kind: 'note', text: 'Keep the conversation central. A little personality is welcome — without making the board harder to use.' }, 'owner');
  await post('/v1/messages', { ticket_id: epic.id, to: 'owner', kind: 'note', text: 'Here is the revised design. The review stays beside the conversation; your feedback returns to this thread.' });
  await page.goto(`/ui/epic/${epic.id}?as=owner`);
  await expect(page.getByTestId('thread').locator(':scope > li')).toHaveCount(2);
  for (const [w, h] of [[1440, 900], [844, 390], [320, 568]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(400);
    const o = await offenders(page); expect(o.top, `PLAIN ${w}: ${JSON.stringify(o)}`).toEqual([]);
  }
  await page.screenshot({ path: 'e2e/evidence/qa-overflow/epic-320.png' });
  await page.goto(`/ui/epic/${epic.id}?as=owner&request=${gate.id}`);
  const dialog = page.getByRole('dialog', { name: 'Design', exact: true });
  await expect(dialog).toBeVisible();
  for (const [w, h] of [[1440, 900], [844, 390], [320, 568]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(400);
    const o = await offenders(page); expect(o.top, `DIALOG ${w}: ${JSON.stringify(o)}`).toEqual([]);
  }
  await page.screenshot({ path: 'e2e/evidence/qa-overflow/dialog-320.png' });
});
