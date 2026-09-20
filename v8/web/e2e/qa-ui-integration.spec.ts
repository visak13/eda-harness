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
  await expect(page.getByTestId('conversation-total')).toHaveText('235 messages');
  await expect(page.getByRole('tablist')).toHaveCount(0);
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
  fs.mkdirSync('e2e/evidence/s3-final-layout', { recursive: true });
  await page.screenshot({ path: 'e2e/evidence/s3-final-layout/populated-1440.png', fullPage: true });
  await page.screenshot({ path: 'e2e/evidence/s3-final-layout/populated-viewport.png' });
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

test('representative three-message conversation comparison', async ({ page, request }) => {
  const { epic, post } = await setupReview(request);
  await post(`/v1/tickets/${epic.id}`, { title: 'Board improvements' }, 'arch', 'PATCH');
  await post('/v1/messages', { ticket_id: epic.id, to: 'arch', kind: 'note', text: 'Keep the conversation central. A little personality is welcome — without making the board harder to use.' }, 'owner');
  const upload = await request.post(`${BASE()}/v1/artifacts/upload`, { headers: { 'X-Participant': 'arch' }, multipart: { file: { name: 'board-layout-sketch.png', mimeType: 'image/png', buffer: fs.readFileSync('../docs/ui-redesign-concepts/s1-assets/final/packet-epic.png') } } });
  expect(upload.ok(), await upload.text()).toBe(true);
  const artifact = (await upload.json()).value;
  await post('/v1/messages', { ticket_id: epic.id, to: 'owner', kind: 'note', text: `Here is the revised design. The review stays beside the conversation; your feedback returns to this thread. ${artifact.id}`, artifacts: [artifact.id] });
  await post('/v1/messages', { ticket_id: epic.id, to: 'arch', kind: 'note', text: 'Keep image replies, mentions and message types. Show status clearly without relying on color alone.' }, 'owner');
  await page.goto(`/ui/epic/${epic.id}?as=owner`);
  await expect(page.getByTestId('thread').locator(':scope > li')).toHaveCount(3);
  await expect(page.getByRole('button', { name: /Design · review requested/ })).toBeVisible();
  await page.getByTestId('order-toggle').click();
  await expect(page.getByTestId('thread').locator(`[data-testid="attachment-card"][data-artifact="${artifact.id}"] img`)).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  fs.mkdirSync('e2e/evidence/s3-final-layout', { recursive: true });
  await page.screenshot({ path: 'e2e/evidence/s3-final-layout/representative-1440.png' });
  const composer = await page.getByTestId('composer').boundingBox();
  console.log('Representative composer geometry', composer);
  expect(composer!.y).toBeLessThan(780);
  await page.setViewportSize({ width: 320, height: 568 });
  await expect(page.getByTestId('composer-send')).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.evaluate(() => scrollTo(0, 0));
  const first = await page.getByTestId('thread').boundingBox();
  console.log('Narrow conversation geometry', first);
  expect(first!.y).toBeLessThan(568); // representative conversation starts in the initial narrow viewport
  expect((await page.getByTestId('app-header').boundingBox())!.height).toBeLessThan(90);
  await expect(page.getByRole('navigation', { name: 'Sections' })).toBeHidden();
  await expect(page.getByRole('tablist')).toHaveCount(0);
  await page.screenshot({ path: 'e2e/evidence/s3-final-layout/representative-320.png', fullPage: true });
  await page.screenshot({ path: 'e2e/evidence/s3-final-layout/representative-320-viewport.png' });
});

test('Needs you negative ruling must not sign off a design', async ({ page, request }) => {
  const { epic, doc, gate } = await setupReview(request);
  const legacyPosts: string[] = [];
  page.on('request', r => { if (r.method() === 'POST' && r.url().includes('/design_signoff/answer')) legacyPosts.push(r.url()); });
  await page.goto('/ui/me?as=owner');
  await page.getByRole('tab', { name: /^Gates/ }).click();
  const form = page.getByTestId('gate-form').filter({ hasText: epic.id });
  await expect(form.getByTestId('gate-answer')).toHaveCount(0);
  await expect(form.getByTestId('gate-submit')).toHaveCount(0);
  await form.getByRole('link', { name: 'Review design at source' }).click();
  const dialog = page.getByRole('dialog', { name: 'Design', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Request changes', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Message', exact: true }).fill('Do not approve; changes required');
  const sent = page.waitForResponse(r => r.url().endsWith('/v1/gates/decide'));
  await dialog.getByRole('button', { name: 'Send', exact: true }).click();
  const response = await sent;
  expect(response.ok()).toBe(true);
  expect(response.request().postDataJSON()).toMatchObject({ ticket_id: epic.id, design_ref: doc.id, gate_event_id: gate.id, reviewed_version: 1, decision: 'request_changes' });
  await expect(dialog).toBeVisible();
  expect(legacyPosts).toEqual([]);
  const context = await request.get(`${BASE()}/v1/tickets/${epic.id}/contextual`, { headers: { 'X-Participant': 'owner' } });
  const value = (await context.json()).value;
  expect(value.events.some((e: { kind: string }) => e.kind === 'gate_answered')).toBe(false);
  expect(value.gates.some((g: { id: string }) => g.id === gate.id)).toBe(true);
  const messages = await request.get(`${BASE()}/v1/messages?ticket_id=${epic.id}`, { headers: { 'X-Participant': 'owner' } });
  expect(JSON.stringify((await messages.json()).value)).toContain('Do not approve; changes required');
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
  const second = page.waitForResponse(r => r.url().endsWith('/v1/gates/decide'));
  await page.getByRole('button', { name: 'Approve design', exact: true }).click();
  console.log('QA second gate response', await (await second).text());
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

for (const action of ['dismiss', 'navigate'] as const) test(`delayed authorization respects later ${action}`, async ({ page, request }) => {
  const { epic, gate } = await setupReview(request);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/v1/me/notifications?*', async route => {
    if (new URL(route.request().url()).searchParams.has('request')) await held;
    await route.continue();
  });
  await page.goto(`/ui/epic/${epic.id}?as=owner&request=${gate.id}`);
  const dialog = page.getByRole('dialog', { name: 'Design', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  if (action === 'navigate') await page.getByRole('link', { name: 'Epics', exact: true }).first().click();
  const current = page.url();
  const response = page.waitForResponse(r => r.url().includes('/v1/me/notifications') && new URL(r.url()).searchParams.has('request'));
  release(); await response;
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(current);
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
  const dialog = page.getByRole('dialog', { name: 'Design', exact: true });
  await expect(dialog).toBeVisible();
  release();
  await expect(page.getByText('Request opened in this tab.', { exact: true })).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`doc=${doc.id}`));
});
