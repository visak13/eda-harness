import { test, expect, BASE } from './fixtures';
import AxeBuilder from '@axe-core/playwright';
test.use({ boardFile: 's5-notifications' });
// Engineering integration only: synthetic click dispatch is NOT a native Windows/Firefox trial.
test('integrated feed, real IDB multitab ledger, private display and draft-safe router handoff', async ({ page, context, request }) => {
  await context.grantPermissions(['notifications']);
  const post = async (path: string, data: unknown, actor = 'owner') => {
    const res = await request.post(`${BASE()}${path}`, { data, headers: { 'X-Participant': actor } });
    expect(res.ok(), await res.text()).toBe(true); return (await res.json()).value;
  };
  const epic = await post('/v1/tickets', { kind: 'epic', work_type: 'feature', title: 'Notification integration' });
  // S17 c-066a9b347a: Enable notifications lives on Settings → Notifications (no longer the account
  // menu). Enable there, then return to the epic through the SPA (same tab, same worker).
  await page.goto(`/ui/settings?as=owner&tab=notifications`);
  const panel = page.getByRole('region', { name: 'Board notifications' });
  await expect(panel).toBeVisible();
  const baseline = page.waitForResponse(res => res.url().includes('/v1/me/notifications?since=-1'));
  await panel.getByRole('button', { name: 'Enable notifications' }).click();
  await baseline;
  await expect(panel.getByRole('status')).toContainText('enabled while');
  await page.goto(`/ui/epic/${epic.id}?as=owner`);
  await expect(panel).toBeHidden();
  const worker = context.serviceWorkers()[0]; expect(worker).toBeTruthy();
  // Suppress desktop UI only inside this owned test worker; exercise real ledger + handshake.
  await worker.evaluate(() => {
    const sw = globalThis as any;
    sw.__shows = [];
    sw.registration.showNotification = async (title: string, options: any) => { sw.__shows.push({ title, ...options }); };
  });
  const second = await context.newPage();
  const secondBaseline = second.waitForResponse(res => res.url().includes('/v1/me/notifications?since=-1'));
  await second.goto(`/ui/epic/${epic.id}?as=owner`); await secondBaseline;
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Retain first-tab draft');
  await second.getByRole('textbox', { name: 'Message', exact: true }).fill('Retain second-tab draft');
  const message = await post('/v1/messages', { ticket_id: epic.id, kind: 'question', to: 'owner', text: 'PRIVATE QUESTION BODY' }, 'arch');
  await expect.poll(() => worker.evaluate(() => (globalThis as any).__shows.length)).toBe(1);
  const notification = await worker.evaluate(() => (globalThis as any).__shows[0]);
  expect(notification.title).toBe('Board needs your attention');
  expect(JSON.stringify(notification)).not.toMatch(/PRIVATE QUESTION|X-Token|Notification integration/);
  expect(notification.data.url).toContain(`#${message.id}`);
  // Replay the same show request concurrently from two real clients, not a mocked IDB.
  const replay = async (tab: typeof page) => tab.evaluate(async data => {
    const registration = await navigator.serviceWorker.ready;
    return await new Promise(resolve => {
      const channel = new MessageChannel(); channel.port1.onmessage = ev => { channel.port1.close(); resolve(ev.data); };
      registration.active!.postMessage({ protocol: 'edp8-notifications-v1', type: 'show', ...data }, [channel.port2]);
    });
  }, notification.data);
  await Promise.all([replay(page), replay(second)]);
  expect(await worker.evaluate(() => (globalThis as any).__shows.length)).toBe(1);
  const ledger = await page.evaluate(async () => await new Promise(resolve => {
    const opening = indexedDB.open('edp8-notifications-v1');
    opening.onsuccess = () => { const db = opening.result; const tx = db.transaction('seen'); const read = tx.objectStore('seen').getAllKeys(); read.onsuccess = () => resolve(read.result); tx.oncomplete = () => db.close(); };
  }));
  expect(JSON.stringify(ledger)).not.toMatch(/PRIVATE|secret|token/);
  expect((ledger as unknown[]).length).toBe(1);
  await worker.evaluate(async data => {
    const sw = globalThis as any;
    // Synthetic events lack OS activation, so focus is simulated here, not asserted as native proof.
    sw.WindowClient.prototype.focus = async function () { return this; };
    let done: Promise<unknown> = Promise.resolve();
    const event = new Event('notificationclick');
    Object.assign(event, { notification: { data, close() {} }, waitUntil(p: Promise<unknown>) { done = p; } });
    sw.dispatchEvent(event); await done;
  }, notification.data);
  await expect.poll(async () => (await page.getByRole('button', { name: 'Open waiting request' }).count()) + (await second.getByRole('button', { name: 'Open waiting request' }).count())).toBe(1);
  expect(context.pages()).toHaveLength(2);
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Retain first-tab draft');
  await expect(second.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Retain second-tab draft');
  const selected = await page.getByRole('button', { name: 'Open waiting request' }).count() ? page : second;
  await selected.getByRole('textbox', { name: 'Message', exact: true }).fill('');
  await selected.getByRole('button', { name: 'Open waiting request' }).click();
  await expect(selected).toHaveURL(new RegExp(`request=${notification.data.request}#${message.id}`));
  // Audit the request landing, then show the notifications panel (Settings → Notifications, S17)
  // for the second audit and the screenshot.
  // @ts-expect-error shared axe adapter has dual playwright-core types
  const landing = await new AxeBuilder({ page: selected }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(landing.violations.filter(v => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
  await selected.goto(`/ui/settings?as=owner&tab=notifications`);
  await expect(selected.getByRole('region', { name: 'Board notifications' })).toBeVisible();
  // @ts-expect-error shared axe adapter has dual playwright-core types
  const audit = await new AxeBuilder({ page: selected }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(audit.violations.filter(v => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
  await selected.screenshot({ path: 'e2e/evidence/s5-notifications.png' });
  await selected.setViewportSize({ width: 320, height: 568 });
  expect(await selected.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await selected.screenshot({ path: 'e2e/evidence/s5-notifications-320.png' });
  await second.close();
});
