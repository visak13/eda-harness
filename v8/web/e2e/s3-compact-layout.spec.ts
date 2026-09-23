import { test, expect, EPIC, BASE } from './fixtures';
test.use({ boardFile: 's3-compact-layout' });
test.beforeEach(async ({ request }) => {
  const current = await request.get(`${BASE()}/v1/epics/${EPIC()}/page`, { headers: { 'X-Participant': 'owner' } });
  expect(current.ok()).toBe(true);
  if ((await current.json()).value.board.epic.children.length) return;
  const response = await request.post(`${BASE()}/v1/tickets`, { headers: { 'X-Participant': 'arch' }, data: {
    kind: 'story', work_type: 'feature', parent_id: EPIC(), title: 'Work destination child',
  } });
  expect(response.ok(), await response.text()).toBe(true);
});

// RETIRED (finding 4, s-d7c39c4b0f): this block exercised the pre-R1 inline epic layout that 9734d1d
// deleted — the `#work-details` disclosure, its `work-search` box reached by opening that disclosure,
// "Work" as an <a> link, the mobile Workspace-navigation menu and the usage↔find slot adjacency. R1
// replaced all of it with the WorkHeader links row → right Drawer. The behaviors that survive are
// covered by current specs (usage↔find adjacency retired with the Usage widget in S19): mobile
// Workspace-navigation / Sections in s2-foundations.spec.ts; the Work drawer + Open-in-tab in s3-workflow.spec.ts and s3-review.spec.ts.
for (const width of [320, 390, 1440]) test.skip(`single navigation and retained capabilities ${width}`, async () => {});

// KEPT (finding 9, epic c-bb6cf0d4d6 "existing navigation behaviour is retained"): old Slack pings
// and bookmarks carry ?tab=/#hash URLs, so those destinations must still land on the new viewers even
// though the tabbed surface is gone. WorkHeader migrates the legacy entry to ?view= (a #m- message
// anchor still wins). These four destinations are re-asserted against the Drawer viewers below.
test('message deep link takes precedence over a legacy work tab', async ({ page, request }) => {
  const response = await request.post(`${BASE()}/v1/messages`, { headers: { 'X-Participant': 'owner' }, data: {
    ticket_id: EPIC(), kind: 'note', text: 'Message deep-link destination',
  } });
  expect(response.ok()).toBe(true);
  const message = (await response.json()).value;
  await page.goto(`/ui/epic/${EPIC()}?as=owner&tab=work#${message.id}`);
  await expect(page.locator(`[id="${message.id}"]`)).toBeInViewport();
  // The message anchor wins: the legacy tab is dropped and no viewer drawer opens.
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

for (const legacy of ['overview', 'work', 'documents', 'thread']) for (const mode of ['query', 'hash']) test(`legacy ${mode} ${legacy} destination opens the new viewer`, async ({ page }) => {
  await page.goto(`/ui/epic/${EPIC()}?as=owner${mode === 'query' ? `&tab=${legacy}` : `#${legacy}`}`);
  await expect(page.getByRole('tablist')).toHaveCount(0);
  if (legacy === 'documents') {
    await expect(page.getByRole('dialog', { name: 'Files & evidence', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  } else if (legacy !== 'thread') { // overview + work both open the Work viewer, which holds work-search
    const dialog = page.getByRole('dialog', { name: 'Work', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId('work-search')).toBeVisible();
  } else { // thread is the conversation itself — no viewer opens
    await expect(page.getByRole('dialog')).toHaveCount(0);
  }
  await expect(page.getByTestId('conversation-composer')).toBeVisible();
});
