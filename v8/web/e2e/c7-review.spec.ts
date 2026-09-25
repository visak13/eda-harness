// C7 bounded review probes. They record observations; these are not acceptance verdicts.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { BASE, EPIC, test, expect } from './fixtures';
import { startCodeServer, folderParam } from './code-server';

const ff = process.env.CHAT_BROWSER === 'stockff';
if (ff) test.use({ browserName: 'firefox', channel: 'moz-firefox', launchOptions: { executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe' } });
test.use({ boardFile: 'c7-review', viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: 'serial', timeout: 180_000 });
const out = path.resolve('e2e/evidence/c7-review', ff ? 'stockff' : 'chromium');
const observed: Record<string, unknown> = {};
const save = () => { fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'observations.json'), JSON.stringify(observed, null, 2)); };
async function call(method: string, route: string, body?: unknown) {
  const response = await fetch(BASE() + route, { method, headers: { 'content-type': 'application/json', 'X-Participant': 'arch' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const result = await response.json();
  if (!result.ok) throw new Error(JSON.stringify(result.error));
  return result.value;
}
let story: string, design: string;
test.beforeAll(async ({ board: _board }) => {
  story = (await call('POST', '/v1/tickets', { kind: 'story', work_type: 'feature', title: 'C7 review fixture', parent_id: EPIC() })).id;
  design = (await call('POST', '/v1/docs', { doc_type: 'design', title: 'C7 design', body_md: '# Review\n\nA visible passage for quoting.\n', scope: EPIC() })).id;
  await call('PATCH', '/v1/tickets/' + story, { design_ref: design });
  await call('POST', '/v1/messages', { ticket_id: story, kind: 'note', text: 'Review fixture message.' });
});

test('record quote-popover Tab boundary in the doc drawer', async ({ page }) => {
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner&doc=${design}&v=1`);
  const paragraph = page.getByTestId('doc-body').locator('p').first();
  await expect(paragraph).toContainText('A visible passage');
  await paragraph.evaluate(el => { const r = document.createRange(); r.selectNodeContents(el); const s = getSelection()!; s.removeAllRanges(); s.addRange(r); document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); });
  const pop = page.getByTestId('quote-popover');
  await expect(pop).toBeVisible();
  const button = pop.getByTestId('quote-add');
  await button.focus();
  await page.keyboard.press('Tab');
  observed.drawerTab = await page.evaluate(() => ({ active: document.activeElement?.outerHTML.slice(0, 250), insideDrawer: !!document.querySelector('[data-testid=drawer-panel]')?.contains(document.activeElement), insidePopover: !!document.querySelector('[data-testid=quote-popover]')?.contains(document.activeElement) }));
  save();
  await page.screenshot({ path: path.join(out, 'drawer-tab.png') });
});

test('record actual chat and reader CSP, style application and sign-out state', async ({ browser }) => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'edp-c7-review-'));
  const repo = path.join(tmp, 'repo'); fs.mkdirSync(repo);
  fs.writeFileSync(path.join(repo, 'sample.txt'), 'review fixture\n');
  const git = (args: string[]) => execFileSync('git', ['-c', 'user.name=review', '-c', 'user.email=review@example.invalid', ...args], { cwd: repo });
  git(['init', '-q']); git(['add', 'sample.txt']); git(['commit', '-qm', 'fixture']);
  const token = 'c7-throwaway-owner-token';
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, 'tokens.json'), JSON.stringify({ owner: token, tokuser: token + '-b' }));
  const cs = await startCodeServer(tmp, { 'edp.boardUrl': BASE() });
  const page = await browser.newPage();
  const csp: string[] = [];
  page.on('console', m => { if (/content.security|style-src|script-src/i.test(m.text())) csp.push(m.text()); });
  page.on('pageerror', m => { if (/content.security|style-src|script-src/i.test(m.message)) csp.push(m.message); });
  try {
    await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
    await expect(page.locator('div.monaco-workbench')).toBeVisible({ timeout: 60_000 });
    const quick = page.locator('.quick-input-widget');
    const command = async (name: string) => {
      await expect(async () => { if (!await quick.isVisible()) await page.keyboard.press('F1'); await expect(quick).toBeVisible({ timeout: 1500 }); }).toPass({ timeout: 15000 });
      await quick.locator('input').fill('>' + name);
      await quick.locator('.monaco-list-row', { hasText: name }).first().click();
    };
    const answer = async (title: string, text: string) => {
      await expect(quick.locator('.quick-input-title')).toContainText(title);
      await quick.locator('input').fill(text); await quick.locator('input').press('Enter');
    };
    await command('EDP: Sign in to board');
    await answer('EDP: board participant id', 'owner'); await answer('EDP: token for owner', token);
    await expect(page.locator('.notifications-toasts', { hasText: 'signed in as owner' })).toBeVisible({ timeout: 15000 });
    await command('EDP: Open chat');
    const chat = page.frameLocator('iframe.webview').first().frameLocator('#active-frame');
    await chat.locator('#pick').click({ timeout: 20000 });
    await quick.locator('.monaco-list-row', { hasText: 'C7 review fixture' }).first().click();
    await expect(chat.locator('#crumb-current')).toHaveText('C7 review fixture', { timeout: 20000 });
    const styles = () => ({ csp: document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content'), styles: Array.from(document.querySelectorAll('style')).map(s => ({ nonce: s.nonce, rules: s.sheet?.cssRules.length ?? null, size: s.textContent?.length })), bodyDisplay: getComputedStyle(document.body).display, tokenInHtml: document.documentElement.outerHTML.includes('c7-throwaway-owner-token') });
    observed.chat = await chat.locator('body').evaluate(styles);
    await chat.locator('.msg > .body').first().evaluate(el => { const r = el.ownerDocument.createRange(); r.selectNodeContents(el); const s = el.ownerDocument.getSelection()!; s.removeAllRanges(); s.addRange(r); });
    await chat.locator('#quote-selection').click();
    await chat.locator('#quote-pop-note').fill('private draft from identity A');
    await chat.locator('#quote-pop-add').click();
    await expect(chat.locator('#quote-chips > li.qchip')).toHaveCount(1);
    await chat.locator('#tab-docs').click();
    await chat.locator(`#panel-docs .dc-row[data-id="${design}"] .dc-open`).click({ timeout: 30000 });
    let reader: import('@playwright/test').Frame | undefined;
    await expect(async () => { for (const fr of page.frames()) if (await fr.locator('#rd-title').count()) reader = fr; expect(reader).toBeTruthy(); }).toPass({ timeout: 30000 });
    await expect(reader!.locator('#doc')).toContainText('A visible passage', { timeout: 20000 });
    observed.reader = await reader!.evaluate(styles);
    await page.screenshot({ path: path.join(out, 'reader-before-signout.png') });
    await command('EDP: Sign out of board');
    await expect(page.locator('.notifications-toasts', { hasText: 'signed out' })).toBeVisible({ timeout: 10000 });
    observed.readerAfterSignout = await reader!.locator('#doc').textContent().catch(() => 'closed');
    await command('EDP: Sign in to board');
    await answer('EDP: board participant id', 'tokuser'); await answer('EDP: token for tokuser', token + '-b');
    await expect(page.locator('.notifications-toasts', { hasText: 'signed in as tokuser' })).toBeVisible({ timeout: 15000 });
    await expect(chat.locator('#crumb-current')).toHaveText('C7 review fixture');
    await chat.locator('#tab-chat').click();
    await expect(chat.locator('#quote-chips > li.qchip')).toHaveCount(1);
    observed.otherIdentityDraft = await chat.locator('.qchip-note').inputValue();
    observed.cspConsole = csp;
    observed.browser = browser.version(); save();
  } finally {
    await page.close(); cs.stop();
    // This absolute path was created above with a fixed prefix in os.tmpdir().
    if (path.dirname(tmp) !== path.resolve(os.tmpdir()) || !path.basename(tmp).startsWith('edp-c7-review-')) throw new Error('unexpected temp directory');
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
