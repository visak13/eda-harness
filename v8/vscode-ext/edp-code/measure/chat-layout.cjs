// qa 0.10.8 (architect m-7e741f6860 items 5 and 6): the Heronry Chat view in a plain chromium page, no code-server and no board.
// The built webview (dist/webview.js + dist/webview-css.css) is loaded with a stub acquireVsCodeApi and fed a ChatState; the
// Inbox rows go through the real scopeInbox (bundled from src/core/inbox.ts), so a board row that names its sender only as
// from_role/from_type shows what the card really shows.  Run `node esbuild.mjs` first.
// node measure/chat-layout.cjs <outdir> <label> [widths=299,390]
const path = require('node:path'), fs = require('node:fs');
const V8 = path.resolve(__dirname, '../../..');
const pw = require(path.join(V8, 'web/node_modules/playwright-core'));
const esbuild = require(path.join(__dirname, '../node_modules/esbuild'));
const [outDir, label, widthsArg = '299,390'] = process.argv.slice(2);
const OUT = path.resolve(outDir); fs.mkdirSync(OUT, { recursive: true });
const L = s => console.log(`${new Date().toISOString()} ${s}`);
let fails = 0;
const check = (ok, what) => { L(`${ok ? 'ok  ' : 'FAIL'} [${label}] ${what}`); if (!ok) fails++; };

const EPIC = 'epic-0123456789', STORY = 's-0123456789', TASK = 't-0123456789';
const TITLE = 'Sample epic: make the Epics list readable on a phone';
const ref = (id, kind, title, status) => ({ id, kind, title, status });

(async () => {
  const tmp = path.join(OUT, '.inbox.cjs');
  await esbuild.build({ entryPoints: [path.join(__dirname, '../src/core/inbox.ts')], bundle: true, format: 'cjs', platform: 'node', outfile: tmp, logLevel: 'warning' });
  const { scopeInbox } = require(path.resolve(tmp));
  fs.rmSync(tmp, { force: true });
  // what GET /v1/inbox lists for the owner: a question from the owner themself, named by from_role/from_type only
  const raw = { questions: [{ id: 'm-0123456789', ticket_id: STORY, created_by: 'owner', created_at: '2026-10-09T10:00:00Z', kind: 'question',
    text: 'Which column keeps its width on a phone?', why: 'addressed to you (@owner)', from_type: 'human', from_role: 'owner' }] };
  const inbox = { scope: EPIC, items: scopeInbox(raw, new Set([EPIC, STORY, TASK]), new Map([[STORY, 'Popover story']])), loading: false, error: null };
  const state = {
    type: 'state', v: 1, me: { id: 'owner', handle: 'owner' }, viewer: '["http://127.0.0.1:9400","owner"]',
    ticket: ref(EPIC, 'epic', TITLE, 'in_progress'), epic: ref(EPIC, 'epic', TITLE, 'in_progress'),
    stories: [{ ...ref(STORY, 'story', 'Popover story', 'in_progress'), unread: 0 }], commits: [], unlinked: [], uncommitted: null,
    architect: 'architect.epic-0123456789', people: [], hasOlder: false, chip: null, feed: { status: 'live' }, notice: null,
    items: [{ id: 'm-aaaaaaaaaa', ticket_id: EPIC, created_by: 'architect.epic-0123456789', created_at: '2026-10-09T09:00:00Z', kind: 'note', text: 'A first note on the thread.', to: null }],
    inbox, docs: { scope: EPIC, docs: [], loading: false, error: null }, decisions: { scope: EPIC, rows: [], canManage: false, loading: false, error: null }, quotes: [],
  };
  const js = fs.readFileSync(path.join(__dirname, '../dist/webview.js'), 'utf8').replace(/<\/script/gi, '<\\/script');
  const css = fs.readFileSync(path.join(__dirname, '../dist/webview-css.css'), 'utf8');
  // the colours VS Code supplies, for the dark+ theme
  const theme = ':root{--vscode-font-family:"Segoe UI",sans-serif;--vscode-font-size:13px;--vscode-foreground:#ccc;--vscode-descriptionForeground:#9d9d9d;--vscode-sideBar-background:#252526;--vscode-input-background:#3c3c3c;--vscode-input-foreground:#ccc;--vscode-textLink-foreground:#3794ff;--vscode-badge-background:#4d4d4d;--vscode-badge-foreground:#fff;--vscode-focusBorder:#007fd4;--vscode-widget-border:#454545;--vscode-button-background:#0e639c;--vscode-button-foreground:#fff}html,body{margin:0;background:var(--vscode-sideBar-background);color:var(--vscode-foreground);font:13px var(--vscode-font-family);height:100%}';
  const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><style>${theme}</style><style>${css}</style></head><body><div id="app"></div><script>let st; window.acquireVsCodeApi = () => ({ postMessage() {}, getState: () => st, setState: v => { st = v; } });</script><script>${js}</script></body></html>`;
  const browser = await pw.chromium.launch({ headless: true, executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe') });
  for (const w of widthsArg.split(',').map(Number)) {
    const page = await (await browser.newContext({ viewport: { width: w, height: 640 } })).newPage();
    page.on('pageerror', e => L(`pageerror ${e.message.slice(0, 200)}`));
    await page.setContent(html);
    await page.evaluate(s => window.dispatchEvent(new MessageEvent('message', { data: s })), state);
    await page.waitForSelector('.tabbar');
    await page.waitForTimeout(400);
    const tabs = await page.evaluate(() => Array.from(document.querySelectorAll('.tabbar .tab')).map(t => ({ id: t.id, top: Math.round(t.getBoundingClientRect().top), right: Math.round(t.getBoundingClientRect().right), w: Math.round(t.getBoundingClientRect().width) })));
    const bar = await page.evaluate(() => { const b = document.querySelector('.tabbar'); return { w: Math.round(b.getBoundingClientRect().width), scroll: b.scrollWidth, client: b.clientWidth }; });
    L(`[${label}] ${w}px tabs: ${JSON.stringify(tabs)} bar ${JSON.stringify(bar)}`);
    await page.screenshot({ path: path.join(OUT, `${label}-tabs-${w}.png`), clip: { x: 0, y: 0, width: w, height: 150 } });
    const picker = await page.evaluate(() => { const p = document.querySelector('.pick-text, .pick'); return { text: p ? p.textContent : null, w: p ? Math.round(p.getBoundingClientRect().width) : 0, clipped: p ? p.scrollWidth > p.clientWidth : null }; });
    L(`[${label}] ${w}px picker ${JSON.stringify(picker)}`);
    check(new Set(tabs.map(t => t.top)).size === 1, `${w}px: every tab is on one row`);
    check(tabs.every(t => t.right <= w + 1) || bar.scroll > bar.client, `${w}px: no tab is cut off without a scroll cue`);
    // a strip that scrolls shows a ‹ › cue on the edge with more behind it (qa round 3: nothing showed it scrolls)
    const cue = await page.evaluate(() => ({ right: getComputedStyle(document.querySelector('.tab-more-right')).display, left: getComputedStyle(document.querySelector('.tab-more-left')).display }));
    L(`[${label}] ${w}px cue ${JSON.stringify(cue)}`);
    check(bar.scroll <= bar.client || cue.right !== 'none', `${w}px: a scrolling strip shows a › cue at rest`);
    if (bar.scroll > bar.client) {
      await page.locator('.tab-more-right').click();
      await page.waitForTimeout(600);
      const after = await page.evaluate(() => ({ left: getComputedStyle(document.querySelector('.tab-more-left')).display, right: getComputedStyle(document.querySelector('.tab-more-right')).display }));
      check(after.left !== 'none' && after.right === 'none', `${w}px: › scrolls to the end, then a ‹ cue is shown and › is gone`);
      await page.screenshot({ path: path.join(OUT, `${label}-tabs-end-${w}.png`), clip: { x: 0, y: 0, width: w, height: 150 } });
      await page.locator('.tab-more-left').click();
      await page.waitForTimeout(600);
    }
    await page.locator('#tab-inbox').click().catch(() => {});
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, `${label}-inbox-${w}.png`) });
    const meta = await page.evaluate(() => (document.querySelector('.ib-meta') || {}).textContent || '');
    L(`[${label}] ${w}px inbox meta: ${meta}`);
    check(!/unknown/.test(meta), `${w}px: the Inbox card does not say "unknown"`);
    await page.close();
  }
  await browser.close();
  L(fails ? `${fails} FAILED` : 'ALL OK'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
