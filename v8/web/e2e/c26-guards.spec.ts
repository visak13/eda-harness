// C26 s-7b8efb9b7a (qa m-ed30a7df6e Q2): a window reload keeps the composer draft, the reply target and an Inbox
// draft for the same identity, and another identity on the same window sees none of them. Runs in a REAL
// code-server against this file's own e2e board (never :9400/:9410). Browser: Chromium by default;
// CHAT_BROWSER=stockff runs the installed Firefox. One browser at a time.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { BASE, EPIC, test, expect } from './fixtures';
import { startCodeServer, folderParam } from './code-server';

const ff = process.env.CHAT_BROWSER === 'stockff';
if (ff) test.use({ browserName: 'firefox', channel: 'moz-firefox', launchOptions: { executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe' } });
test.use({ boardFile: 'c26-guards', viewport: { width: 1600, height: 1000 } });
test.describe.configure({ mode: 'serial', timeout: 240_000 });
const out = path.resolve('e2e/evidence/c26-guards', ff ? 'stockff' : 'chromium');
const observed: Record<string, unknown> = {};
const save = () => { fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'observations.json'), JSON.stringify(observed, null, 2)); };
async function call(method: string, route: string, body?: unknown) {
  const response = await fetch(BASE() + route, { method, headers: { 'content-type': 'application/json', 'X-Participant': 'arch' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const result = await response.json();
  if (!result.ok) throw new Error(JSON.stringify(result.error));
  return result.value;
}
let story: string, ask: string;
test.beforeAll(async ({ board: _board }) => {
  story = (await call('POST', '/v1/tickets', { kind: 'story', work_type: 'feature', title: 'C26 reload fixture', parent_id: EPIC() })).id;
  await call('POST', '/v1/messages', { ticket_id: story, kind: 'note', text: 'Reload fixture message.' });
  ask = (await call('POST', '/v1/messages', { ticket_id: story, kind: 'question', to: 'owner', text: 'Owner: which way for the reload fixture?' })).id;
});

test('reload restores composer, reply target and Inbox drafts for the same identity only', async ({ browser }) => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'edp-c26-guards-'));
  const repo = path.join(tmp, 'repo'); fs.mkdirSync(repo);
  fs.writeFileSync(path.join(repo, 'sample.txt'), 'reload fixture\n');
  const git = (args: string[]) => execFileSync('git', ['-c', 'user.name=review', '-c', 'user.email=review@example.invalid', ...args], { cwd: repo });
  git(['init', '-q']); git(['add', 'sample.txt']); git(['commit', '-qm', 'fixture']);
  const token = 'c26-throwaway-owner-token';
  fs.writeFileSync(path.join(process.env.EDP8_E2E_HOME!, 'tokens.json'), JSON.stringify({ owner: token, arch: token + '-b' }));
  const cs = await startCodeServer(tmp, { 'edp.boardUrl': BASE() });
  const page = await browser.newPage();
  try {
    await page.goto(`http://127.0.0.1:${cs.port}/?folder=${folderParam(repo)}`);
    await expect(page.locator('div.monaco-workbench')).toBeVisible({ timeout: 60_000 });
    const quick = page.locator('.quick-input-widget');
    // the whole open-fill-pick is retried: a workbench still restoring after a reload can close the palette under us
    const command = async (name: string) => {
      await expect(async () => {
        if (!await quick.isVisible()) await page.keyboard.press('F1');
        await expect(quick).toBeVisible({ timeout: 1500 });
        await quick.locator('input').fill('>' + name);
        await quick.locator('.monaco-list-row', { hasText: name }).first().click({ timeout: 3000 });
      }).toPass({ timeout: 30000 });
    };
    const answer = async (title: string, text: string) => {
      await expect(quick.locator('.quick-input-title')).toContainText(title);
      await quick.locator('input').fill(text); await quick.locator('input').press('Enter');
    };
    const signIn = async (who: string, tok: string) => {
      await command('EDP: Sign in to board');
      await answer('EDP: board participant id', who); await answer(`EDP: token for ${who}`, tok);
      await expect(page.locator('.notifications-toasts', { hasText: `signed in as ${who}` }).last()).toBeVisible({ timeout: 15000 });
    };
    const chat = page.frameLocator('iframe.webview').first().frameLocator('#active-frame');
    const inboxBox = chat.locator('#panel-inbox .ib-row .ib-text').first();
    const inboxLoaded = async () => { await chat.locator('#tab-inbox').click(); await expect(inboxBox).toBeVisible({ timeout: 20000 }); await chat.locator('#tab-chat').click(); };
    const drafts = async () => {
      await chat.locator('#tab-chat').click();
      const composer = await chat.locator('#composer').inputValue();
      const reply = await chat.locator('#reply-bar').isVisible() ? await chat.locator('#reply-bar .rb-text').textContent() : null;
      await chat.locator('#tab-inbox').click();
      const inbox = await inboxBox.count() ? await inboxBox.inputValue() : null;
      await chat.locator('#tab-chat').click();
      return { composer, reply, inbox };
    };

    await signIn('owner', token);
    await command('EDP: Open chat');
    await chat.locator('#pick').click({ timeout: 20000 });
    await quick.locator('.monaco-list-row', { hasText: 'C26 reload fixture' }).first().click();
    await expect(chat.locator('#crumb-current')).toHaveText('C26 reload fixture', { timeout: 20000 });
    await expect(chat.locator('#feed-status')).toHaveText('live', { timeout: 20000 });
    // the three drafts: a composer draft, a reply target, an unsent Inbox answer
    await chat.locator(`.msg[data-id="${ask}"] .reply`).click();
    await expect(chat.locator('#reply-bar')).toBeVisible();
    await chat.locator('#composer').fill('half a thought, unsent');
    await chat.locator('#tab-inbox').click();
    await expect(inboxBox).toBeVisible({ timeout: 20000 });
    await inboxBox.fill('half an answer, unsent');
    await chat.locator('#tab-chat').click();
    const want = { composer: 'half a thought, unsent', reply: 'Owner: which way for the reload fixture?', inbox: 'half an answer, unsent' };
    observed.beforeReload = await drafts();
    expect(observed.beforeReload).toEqual(want);
    await page.screenshot({ path: path.join(out, 'before-reload.png') });

    // Developer: Reload Window (the whole workbench and its webviews restart; the host re-reads the stored creds)
    const nav = page.waitForEvent('framenavigated', { predicate: f => f === page.mainFrame(), timeout: 60_000 });
    await command('Developer: Reload Window');
    await nav;
    await expect(page.locator('div.monaco-workbench')).toBeVisible({ timeout: 60_000 });
    await command('EDP: Open chat');
    await expect(chat.locator('#crumb-current')).toHaveText('C26 reload fixture', { timeout: 30000 });
    await expect(chat.locator('#feed-status')).toHaveText('live', { timeout: 20000 });
    await inboxLoaded();
    observed.afterReload = await drafts();
    expect(observed.afterReload).toEqual(want);
    await page.screenshot({ path: path.join(out, 'after-reload.png') });

    // another identity on the same window sees none of them
    await signIn('arch', token + '-b');
    await expect(chat.locator('#crumb-current')).toHaveText('C26 reload fixture', { timeout: 30000 });
    observed.otherIdentity = await drafts();
    expect(observed.otherIdentity).toEqual({ composer: '', reply: null, inbox: null });
    await page.screenshot({ path: path.join(out, 'other-identity.png') });

    // and the owner gets all three back
    await signIn('owner', token);
    await expect(chat.locator('#crumb-current')).toHaveText('C26 reload fixture', { timeout: 30000 });
    await inboxLoaded();
    observed.ownerAgain = await drafts();
    expect(observed.ownerAgain).toEqual(want);
    observed.browser = browser.version(); save();
  } finally {
    await page.close(); cs.stop();
    // This absolute path was created above with a fixed prefix in os.tmpdir().
    if (path.dirname(tmp) !== path.resolve(os.tmpdir()) || !path.basename(tmp).startsWith('edp-c26-guards-')) throw new Error('unexpected temp directory');
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
