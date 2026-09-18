import { test, expect, BASE } from './fixtures';
test.use({ boardFile: 'qa-ui-integration' });

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
