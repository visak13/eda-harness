import { test, expect, EPIC, BASE } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
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

for (const width of [320, 390, 1440]) test(`single navigation and retained capabilities ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/ui/epic/${EPIC()}?as=owner`);
  await expect(page.getByTestId('conversation-total')).toBeVisible();
  await expect(page.getByRole('tablist')).toHaveCount(0);
  const draft = page.getByTestId('composer-text');
  await draft.fill('Keep this exact unsent message');
  await draft.evaluate(el => { (el as HTMLTextAreaElement).dataset.sameNode = 'yes'; });
  await page.getByRole('link', { name: 'Work', exact: true }).click();
  await expect(page.locator('#work-details')).toHaveAttribute('open', '');
  await expect(page.getByTestId('work-search')).toBeVisible();
  await page.locator('#work-details > summary').click();
  await page.getByRole('button', { name: 'Files & evidence', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Files & evidence', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(draft).toHaveValue('Keep this exact unsent message');
  await expect(draft).toHaveAttribute('data-same-node', 'yes');
  if (width < 768) {
    const menu = page.getByRole('button', { name: 'Workspace navigation', exact: true });
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('navigation', { name: 'Sections' })).toBeHidden();
    await menu.focus(); await page.keyboard.press('Enter');
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    const sections = page.getByRole('navigation', { name: 'Sections' });
    await expect(sections.getByRole('link', { name: /Epics/ })).toBeVisible();
    await expect(sections.getByRole('link', { name: /Seats/ })).toBeVisible();
    await expect(sections.getByRole('link', { name: /Needs you/ })).toBeVisible();
    if (width === 320) {
      fs.mkdirSync('e2e/evidence/s3-final-layout', { recursive: true });
      await page.screenshot({ path: 'e2e/evidence/s3-final-layout/navigation-320.png', fullPage: true });
    }
    const usage = page.getByRole('button', { name: 'Usage', exact: true });
    await expect(usage).toBeVisible();
    expect(await usage.evaluate(el => el.closest('#shell-usage-slot')?.nextElementSibling?.getAttribute('data-testid'))).toBe('find-open');
    await usage.click();
    await expect(page.getByRole('dialog', { name: 'Subscription usage' })).toBeVisible();
    await page.keyboard.press('Escape'); await expect(usage).toBeFocused();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    const prefs = page.getByRole('button', { name: 'Account and preferences', exact: true });
    await prefs.click();
    await expect(page.getByRole('dialog', { name: 'Preferences', exact: true })).toBeVisible();
    await page.keyboard.press('Escape'); await expect(prefs).toBeFocused();
    // The disclosure itself closes on Escape only after its nested panel has closed.
    await page.keyboard.press('Escape'); await expect(menu).toBeFocused();
    await expect(sections).toBeHidden();
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('dialog', { name: /Find/ })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(menu).toBeFocused();
  }
  await expect(draft).toHaveValue('Keep this exact unsent message');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  // @ts-expect-error shared axe adapter's duplicate playwright-core types
  const audit = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(audit.violations.filter(v => ['serious', 'critical'].includes(v.impact ?? ''))).toEqual([]);
  if (width < 768) {
    await draft.fill(''); // no unsent draft when deliberately leaving the source
    const menu = page.getByRole('button', { name: 'Workspace navigation', exact: true });
    await menu.click();
    await page.getByRole('navigation', { name: 'Sections' }).getByRole('link', { name: /Epics/ }).click();
    await expect(page).toHaveURL(/\/ui\/epics/);
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('navigation', { name: 'Sections' })).toBeHidden();
  }
});

test('message deep link takes precedence over a legacy work tab', async ({ page, request }) => {
  const response = await request.post(`${BASE()}/v1/messages`, { headers: { 'X-Participant': 'owner' }, data: {
    ticket_id: EPIC(), kind: 'note', text: 'Message deep-link destination',
  } });
  expect(response.ok()).toBe(true);
  const message = (await response.json()).value;
  await page.goto(`/ui/epic/${EPIC()}?as=owner&tab=work#${message.id}`);
  await expect(page.locator(`[id="${message.id}"]`)).toBeInViewport();
  await expect(page.locator('#work-details')).not.toHaveAttribute('open', '');
});

for (const legacy of ['overview', 'work', 'documents', 'thread']) for (const mode of ['query', 'hash']) test(`legacy ${mode} ${legacy} destination remains usable`, async ({ page }) => {
  await page.goto(`/ui/epic/${EPIC()}?as=owner${mode === 'query' ? `&tab=${legacy}` : `#${legacy}`}`);
  await expect(page.getByRole('tablist')).toHaveCount(0);
  if (legacy === 'documents') {
    await expect(page.getByRole('dialog', { name: 'Files & evidence', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  } else if (legacy !== 'thread') {
    await expect(page.locator('#work-details')).toHaveAttribute('open', '');
    await expect(page.getByTestId('work-search')).toBeVisible();
  }
  await expect(page.getByTestId('composer-text')).toBeVisible();
});
