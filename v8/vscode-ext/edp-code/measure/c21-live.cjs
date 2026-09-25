// C21 live check (s-987e1154ca, owner m-2b78c708eb): the doc reader fills the editor width. A THROWAWAY code-server
// (the pinned build, temp user-data + extensions dirs, spare loopback port, the given vsix installed there; never
// :9410 or v8/.data/code) pointed read-only at the board; sign in as this seat (EDP8_PARTICIPANT or EDP_HANDLE +
// EDP8_TOKEN from env, typed into the input box, never logged), open the epic, Docs tab, the doc in the reader.
// Measured twice: full screen (zen, editor ~1900px) and an editor group dragged to ~1000px. Each time the doc
// column and its extras must span .rd-main's content box (no empty right band), the widest table must fit that
// column, and the outline must show at 160-240px. Screenshots at the top and at the first table. Kills only its pid.
// node c21-live.cjs <chromium|stockff> <outdir> <vsix> <epicTitle> <docId> <version>
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const V8 = path.resolve(__dirname, '../../..');
const pw = require(path.join(V8, 'web/node_modules/playwright-core'));
const [which, outDir, vsix, epicTitle, docId, version] = process.argv.slice(2);
const PART = process.env.EDP8_PARTICIPANT || process.env.EDP_HANDLE, TOK = process.env.EDP8_TOKEN;
const BOARD = process.env.EDP8_BOARD_URL || 'http://127.0.0.1:9400';
fs.mkdirSync(outDir, { recursive: true });
const logf = path.join(outDir, `${which}.log`);
const L = s => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + '\n'); };
let fails = 0;
const check = (ok, what) => { L(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) fails++; };

const lock = JSON.parse(fs.readFileSync(path.join(V8, 'vscode-ext/code-server.lock.json'), 'utf8'));
const SERVER_DIR = path.join(V8, '.tools/code-server', lock.version, lock.server_dir);
const NODE = path.join(SERVER_DIR, lock.node);
const csEnv = () => { const e = {}; for (const [k, v] of Object.entries(process.env)) if (!/^EDP8?_/i.test(k)) e[k] = v; e.EXTENSIONS_GALLERY = '{}'; return e; };
const freePort = () => new Promise((res, rej) => { const s = net.createServer(); s.on('error', rej); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

async function startCodeServer() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'c21-cs-'));
  const userDir = path.join(tmp, 'user-data'), extDir = path.join(tmp, 'extensions');
  for (const d of ['User', 'Machine']) fs.mkdirSync(path.join(userDir, d), { recursive: true });
  fs.mkdirSync(extDir, { recursive: true });
  const settings = JSON.stringify({ 'security.workspace.trust.enabled': false, 'workbench.startupEditor': 'none', 'workbench.tips.enabled': false,
    'telemetry.telemetryLevel': 'off', 'extensions.autoUpdate': false, 'git.openRepositoryInParentFolders': 'never', 'edp.boardUrl': BOARD }, null, 1);
  fs.writeFileSync(path.join(userDir, 'User/settings.json'), settings);
  fs.writeFileSync(path.join(userDir, 'Machine/settings.json'), settings);
  const inst = spawnSync(NODE, [SERVER_DIR, '--user-data-dir', userDir, '--extensions-dir', extDir, '--install-extension', vsix, '--force'], { env: csEnv(), encoding: 'utf8', timeout: 120000 });
  if (inst.status !== 0) throw new Error(`vsix install failed: ${inst.stdout} ${inst.stderr}`);
  const list = spawnSync(NODE, [SERVER_DIR, '--user-data-dir', userDir, '--extensions-dir', extDir, '--list-extensions', '--show-versions'], { env: csEnv(), encoding: 'utf8', timeout: 60000 });
  L(`throwaway code-server extensions: ${list.stdout.trim().replace(/\s+/g, ' ')}`);
  const port = await freePort();
  const cs = spawn(NODE, [SERVER_DIR, '--bind-addr', `127.0.0.1:${port}`, '--auth', 'none', '--disable-telemetry', '--disable-update-check', '--disable-proxy',
    '--disable-workspace-trust', '--user-data-dir', userDir, '--extensions-dir', extDir], { env: csEnv(), stdio: 'ignore', windowsHide: true });
  const stop = () => { if (cs.pid && cs.exitCode === null) spawnSync('taskkill', ['/PID', String(cs.pid), '/T', '/F'], { stdio: 'ignore' }); };
  for (const end = Date.now() + 60000; Date.now() < end;) {
    if (cs.exitCode !== null) throw new Error(`code-server exited early (${cs.exitCode})`);
    try { if ((await fetch(`http://127.0.0.1:${port}/healthz`)).ok) { L(`throwaway code-server pid ${cs.pid} on :${port}, dirs under ${tmp}`); return { port, stop }; } } catch { /* not up */ }
    await new Promise(r => setTimeout(r, 300));
  }
  stop(); throw new Error('code-server did not answer /healthz within 60 s');
}

/** Widths inside the reader frame: .rd-main content box vs the doc, the extras, the widest table, the outline. */
const measure = rd => rd.evaluate(() => {
  const r = e => (e ? e.getBoundingClientRect() : null);
  const main = document.querySelector('.rd-main'), cs = getComputedStyle(main);
  const content = main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const doc = r(document.querySelector('.rd-doc')), extras = r(document.querySelector('.rd-extras')), outline = document.querySelector('.rd-outline');
  const tables = [...document.querySelectorAll('.rd-doc table')].map(t => Math.round(t.getBoundingClientRect().width));
  return { frame: innerWidth, main: main.clientWidth, content: Math.round(content), doc: Math.round(doc.width), docRight: Math.round(doc.right),
    mainRight: Math.round(r(main).right - parseFloat(cs.paddingRight)), extras: Math.round(extras.width), tables: tables.length, widestTable: Math.max(0, ...tables),
    outline: outline && getComputedStyle(outline).display !== 'none' ? Math.round(r(outline).width) : 0,
    docMaxWidth: getComputedStyle(document.querySelector('.rd-doc')).maxWidth, extrasMaxWidth: getComputedStyle(document.querySelector('.rd-extras')).maxWidth };
});

(async () => {
  const cs = await startCodeServer();
  const browser = which === 'stockff'
    ? await pw.firefox.launch({ channel: 'moz-firefox', executablePath: 'C:/Program Files/Mozilla Firefox/firefox.exe', headless: true })
    : await pw.chromium.launch({ headless: true, executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe') });
  try {
    const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
    page.on('pageerror', e => L(`pageerror ${e.message.slice(0, 200)}`));
    L(`browser ${which} ${browser.version()} viewport 1920x1080`);
    await page.goto(`http://127.0.0.1:${cs.port}/?folder=/c:/Projects/Learning/eda-base3/v8`, { waitUntil: 'domcontentloaded' });
    await page.locator('div.monaco-workbench').waitFor({ timeout: 60000 });
    await page.waitForTimeout(5000);
    const quick = page.locator('.quick-input-widget');
    const row = t => quick.locator('.monaco-list-row', { hasText: t }).first();
    const cmd = async t => {
      for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await page.keyboard.press('F1'); await page.waitForTimeout(700); }
      await quick.locator('input').fill(`>${t}`); await row(t).click();
    };
    const type = async (v, title) => { await quick.locator('.quick-input-title', { hasText: title }).waitFor(); const i = quick.locator('input'); await i.fill(''); await i.pressSequentially(v); await page.keyboard.press('Enter'); };
    const shot = async name => page.screenshot({ path: path.join(outDir, `${which}-${name}.png`) });
    const titleAction = re => page.locator('.editor-group-container.active .editor-actions').getByRole('button', { name: re });
    await cmd('EDP: Sign in to board');
    await type(PART, 'EDP: board participant id');
    await type(TOK, 'EDP: token for');
    await page.locator('.notifications-toasts', { hasText: 'signed in as' }).waitFor({ timeout: 15000 });
    L('signed in');
    await cmd('EDP: Chat: open a ticket or epic thread…');
    await quick.locator('.quick-input-title', { hasText: 'EDP chat: open a thread' }).waitFor({ timeout: 10000 });
    await quick.locator('input').fill(epicTitle);
    await row(epicTitle).waitFor({ timeout: 30000 });
    await row(epicTitle).click();
    const c = page.locator('iframe.webview').first().contentFrame().locator('#active-frame').contentFrame();
    await c.locator('#crumb-current', { hasText: epicTitle }).waitFor({ timeout: 20000 });
    await page.locator('.notifications-toasts .notification-toast').first().waitFor({ state: 'hidden', timeout: 20000 }).catch(() => {});
    await c.locator('#tab-docs').click();
    const drow = c.locator(`#panel-docs .dc-row[data-id="${docId}"]`);
    await drow.waitFor({ timeout: 30000 });
    await drow.locator('.dc-open').click();
    await page.locator('.tabs-container .tab.active').filter({ hasText: `· v${version}` }).waitFor({ timeout: 30000 });
    let rd;
    for (let i = 0; i < 60 && !rd; i++) {
      for (const f of page.frames()) if ((await f.title().catch(() => '')) === `EDP ${docId} v${version}` && await f.locator('.rd-doc h2').count().catch(() => 0)) rd = f;
      if (!rd) await page.waitForTimeout(500);
    }
    check(!!rd, `the reader renders ${docId} v${version}`);
    if (!rd) throw new Error('no reader frame');
    const verdict = (m, label, minEditor) => {
      L(`${label}: ${JSON.stringify(m)}`);
      check(m.frame >= minEditor, `${label}: reader frame ${m.frame}px wide (>= ${minEditor})`);
      check(m.docMaxWidth === 'none' && m.extrasMaxWidth === 'none', `${label}: computed max-width none on .rd-doc and .rd-extras`);
      check(Math.abs(m.doc - m.content) <= 2 && Math.abs(m.docRight - m.mainRight) <= 2, `${label}: doc column ${m.doc}px spans .rd-main's content box ${m.content}px (no empty right band)`);
      check(Math.abs(m.extras - m.content) <= 2, `${label}: extras ${m.extras}px span the same width`);
      check(m.widestTable <= m.doc + 1, `${label}: ${m.tables} tables, widest ${m.widestTable}px fits the ${m.doc}px column`);
      check(m.outline >= 160 && m.outline <= 240, `${label}: outline shows at ${m.outline}px (160-240)`);
    };
    const firstTable = async name => { if (await rd.locator('.rd-doc table').count()) { await rd.locator('.rd-doc table').first().scrollIntoViewIfNeeded(); await page.waitForTimeout(400); await shot(name); await rd.locator('.rd-doc').evaluate(e => e.closest('.rd-main').scrollTo(0, 0)); } };
    // 1. full screen (zen)
    await titleAction(/^Full screen/).click();
    await page.waitForTimeout(1500);
    verdict(await measure(rd), 'full screen', 1800);
    await shot('1-fullscreen');
    await firstTable('2-fullscreen-table');
    await cmd('View: Toggle Zen Mode');
    await page.waitForTimeout(1200);
    // 2. an editor group ~1000px: drag the chat's (auxiliary bar) left edge until the editor part is 1000px wide
    const ed = await page.locator('.part.editor').boundingBox();
    const aux = await page.locator('.part.auxiliarybar').boundingBox();
    L(`normal view before drag: editor ${Math.round(ed.width)}px, chat ${aux ? Math.round(aux.width) : 0}px`);
    if (aux) { await page.mouse.move(aux.x + 1, 540); await page.mouse.down(); await page.mouse.move(ed.x + 1000, 540, { steps: 12 }); await page.mouse.up(); }
    await page.waitForTimeout(1200);
    const ed2 = await page.locator('.part.editor').boundingBox();
    L(`normal view after drag: editor ${Math.round(ed2.width)}px`);
    check(Math.abs(ed2.width - 1000) <= 60, `normal view: editor group ${Math.round(ed2.width)}px (~1000)`);
    verdict(await measure(rd), 'normal view', 900);
    await shot('3-normal-1000');
    await firstTable('4-normal-1000-table');
  } finally {
    L(fails ? `${fails} check(s) FAILED` : 'all checks ok');
    await browser.close().catch(() => {});
    cs.stop();
  }
  process.exit(fails ? 1 : 0);
})().catch(e => { L(`error ${e.message.split('\n')[0]}`); process.exit(2); });
