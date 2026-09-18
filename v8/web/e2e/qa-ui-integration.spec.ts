import { test, expect, BASE } from './fixtures';
import fs from 'node:fs';
test.use({ boardFile: 'qa-ui-integration' });

test('populated 235-message history keeps total, draft and viewport anchor', async ({ page, request }) => {
  const create = await request.post(`${BASE()}/v1/tickets`, { headers: { 'X-Participant': 'owner' }, data: { kind: 'epic', work_type: 'feature', title: 'QA populated conversation' } });
  const epic = (await create.json()).value;
  for (let i = 0; i < 235; i++) {
    const r = await request.post(`${BASE()}/v1/messages`, { headers: { 'X-Participant': 'owner' }, data: { ticket_id: epic.id, kind: 'note', text: `QA history row ${i} — substantive source conversation.` } });
    expect(r.ok()).toBe(true);
  }
  await page.goto(`/ui/epic/${epic.id}?as=owner`);
  await expect(page.getByRole('tab', { name: 'Thread 235', exact: true })).toBeVisible();
  const draft = page.getByRole('textbox', { name: 'Message', exact: true });
  await draft.fill('QA KEEP independent source draft');
  const list = page.getByTestId('thread');
  await expect(list.locator(':scope > li')).toHaveCount(100);
  await page.getByTestId('order-toggle').click();
  await list.evaluate(el => { el.scrollTop = 180; });
  const anchor = await list.evaluate(el => {
    const top = el.getBoundingClientRect().top;
    const child = [...el.children].find(c => c.getBoundingClientRect().bottom > top)!;
    return { id: child.id, top: child.getBoundingClientRect().top - top };
  });
  await page.getByRole('button', { name: 'Load older messages', exact: true }).click();
  await expect(list.locator(':scope > li')).toHaveCount(200);
  const now = await page.locator(`[id="${anchor.id}"]`).boundingBox();
  // Compare relative to list: button click may scroll the document to reach it.
  const relative = await list.evaluate((el, id) => {
    const child = [...el.children].find(c => c.id === id)!;
    return child.getBoundingClientRect().top - el.getBoundingClientRect().top;
  }, anchor.id);
  expect(now).not.toBeNull();
  expect(Math.abs(relative - anchor.top)).toBeLessThan(2);
  await page.getByRole('button', { name: 'Load older messages', exact: true }).click();
  await expect(list.locator(':scope > li')).toHaveCount(235);
  await expect(draft).toHaveValue('QA KEEP independent source draft');
  await expect(page.getByRole('button', { name: 'Load older messages', exact: true })).toHaveCount(0);
  await page.evaluate(() => scrollTo(0, 0));
  fs.mkdirSync('e2e/evidence/qa-ui', { recursive: true });
  await page.screenshot({ path: 'e2e/evidence/qa-ui/populated-1440.png', fullPage: true });
  await page.screenshot({ path: 'e2e/evidence/qa-ui/populated-viewport.png' });
  console.log('QA composer geometry', await draft.boundingBox());
});

async function setupReview(request: import('@playwright/test').APIRequestContext) {
  async function post(path: string, data: unknown, actor = 'arch', method = 'POST') {
    const r = await request.fetch(`${BASE()}${path}`, { method, headers: { 'X-Participant': actor }, data });
    expect(r.ok(), await r.text()).toBe(true); return (await r.json()).value;
  }
  const epic = await post('/v1/tickets', { kind: 'epic', work_type: 'feature', title: 'QA review claim' }, 'owner');
  const doc = await post('/v1/docs', { doc_type: 'design', title: 'QA reviewed design', scope: epic.id, body_md: '# Current design' });
  await post('/v1/criteria', { ticket_id: epic.id, text: 'review', check: 'command' });
  await post(`/v1/tickets/${epic.id}`, { design_ref: doc.id }, 'arch', 'PATCH');
  const gate = await post(`/v1/gates/${epic.id}/design_signoff/open`, {});
  return { epic, doc, gate, post };
}

test('Needs you negative ruling must not sign off a design', async ({ page, request }) => {
  const { epic } = await setupReview(request);
  await page.goto('/ui/me?as=owner');
  await page.getByRole('tab', { name: /^Gates/ }).click();
  const form = page.getByTestId('gate-form').filter({ hasText: epic.id });
  await form.getByTestId('gate-answer').fill('Do not approve; changes required');
  const sent = page.waitForResponse(r => r.url().includes('/design_signoff/answer'));
  await form.getByTestId('gate-submit').click(); await sent;
  const r = await request.get(`${BASE()}/v1/tickets/${epic.id}`, { headers: { 'X-Participant': 'owner' } });
  expect((await r.json()).value.status).not.toBe('signed_off');
});

test('ordinary comment leaves clean current design approvable', async ({ page, request }) => {
  const { epic, doc } = await setupReview(request);
  await page.goto(`/ui/doc/${doc.id}?as=owner&source=${epic.id}&version=1`);
  await expect(page.getByRole('button', { name: 'Approve design', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Comment without requesting changes' }).click();
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Ordinary comment, not a request for changes.');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Approve design', exact: true })).toBeEnabled();
});

test('same-version new gate has a new approval operation', async ({ page, request }) => {
  const { epic, doc, post } = await setupReview(request);
  const url = `/ui/doc/${doc.id}?as=owner&source=${epic.id}&version=1`;
  await page.goto(url);
  await page.getByRole('button', { name: 'Approve design', exact: true }).click();
  await expect(page.getByText('Design approved at v1.', { exact: true })).toBeVisible();
  await post(`/v1/tickets/${epic.id}`, { status: 'drafted' }, 'owner', 'PATCH');
  await post(`/v1/tickets/${epic.id}`, { design_ref: doc.id }, 'arch', 'PATCH');
  await post(`/v1/gates/${epic.id}/design_signoff/open`, {});
  await page.goto(url);
  await expect(page.getByRole('button', { name: 'Approve design', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Approve design', exact: true }).click();
  await expect(page.getByText('Design approved at v1.', { exact: true })).toBeVisible();
});

test('epic Expand opens the promised drawer editing surface', async ({ page, request }) => {
  const { epic } = await setupReview(request);
  await page.goto(`/ui/epic/${epic.id}?as=owner`);
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Keep my draft');
  await page.getByTestId('composer-expand').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Keep my draft');
});

test('ticket Expand retains failed attachment retry', async ({ page, request }) => {
  const { epic, post } = await setupReview(request);
  const story = await post('/v1/tickets', { kind: 'story', work_type: 'feature', parent_id: epic.id, title: 'Attachment recovery' });
  await page.goto(`/ui/ticket/${story.id}?as=owner`);
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Keep my failed file');
  await page.route('**/v1/artifacts/upload', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { message: 'QA upload failure' } }) }));
  await page.locator('input[type=file]').setInputFiles({ name: 'qa.txt', mimeType: 'text/plain', buffer: Buffer.from('QA file') });
  await expect(page.getByRole('button', { name: 'Retry upload' })).toBeVisible();
  await page.getByTestId('composer-expand').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry upload' })).toBeVisible();
});

test('approval deep link keeps its viewer after delayed notification authorization', async ({ page, request }) => {
  async function post(path: string, data: unknown, actor = 'arch', method = 'POST') {
    const res = await request.fetch(`${BASE()}${path}`, { method, headers: { 'X-Participant': actor }, data });
    expect(res.ok(), await res.text()).toBe(true);
    return (await res.json()).value;
  }
  const epic = await post('/v1/tickets', { kind: 'epic', work_type: 'feature', title: 'QA request race' }, 'owner');
  const doc = await post('/v1/docs', { doc_type: 'design', title: 'QA exact design', scope: epic.id, body_md: '# Review me' });
  await post('/v1/criteria', { ticket_id: epic.id, text: 'Review remains visible', check: 'command' });
  await post(`/v1/tickets/${epic.id}`, { design_ref: doc.id }, 'arch', 'PATCH');
  const gate = await post(`/v1/gates/${epic.id}/design_signoff/open`, {});
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/v1/me/notifications?*', async route => {
    if (new URL(route.request().url()).searchParams.has('request')) await held;
    await route.continue();
  });
  await page.goto(`/ui/epic/${epic.id}?as=owner&request=${gate.id}`);
  const dialog = page.getByRole('dialog', { name: 'Drawer', exact: true });
  await expect(dialog).toBeVisible();
  release();
  await expect(page.getByText('Request opened in this tab.', { exact: true })).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`doc=${doc.id}`));
});
