// Restricted Mode live check (architect m-f04c23905e item 1): a THROWAWAY code-server (the pinned build, temp user-data and
// extensions dirs, a spare loopback port, workspace trust ON and the startup prompt off, so a folder opens in Restricted
// Mode) with the given vsix installed. Passes when the Heronry commands and the Chat view are there while the window says
// Restricted Mode, and a guarded git command is refused. Kills only its own pid.
// node restricted-live.cjs <outdir> <vsix> <label> [present|absent]
const path = require('node:path'), fs = require('node:fs'), os = require('node:os'), net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const V8 = path.resolve(__dirname, '../../..');
const pw = require(path.join(V8, 'web/node_modules/playwright-core'));
const [outDir, vsix, label, expect = 'present'] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const L = s => console.log(`${new Date().toISOString()} ${s}`);
const lock = JSON.parse(fs.readFileSync(path.join(V8, 'vscode-ext/code-server.lock.json'), 'utf8'));
const TOOLS = [process.env.EDP_TOOLS_DIR, path.join(V8, '.tools')].filter(Boolean).map(d => path.join(d, 'code-server', lock.version, lock.server_dir)).find(d => fs.existsSync(d));
const NODE = path.join(TOOLS, lock.node);
const env = () => { const e = {}; for (const [k, v] of Object.entries(process.env)) if (!/^(EDP8?_|PORT$|CODE_SERVER_|VSCODE_PROXY_URI$)/i.test(k)) e[k] = v; e.EXTENSIONS_GALLERY = '{}'; return e; };
const freePort = () => new Promise((res, rej) => { const s = net.createServer(); s.on('error', rej); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const palette = async (page, text) => { await page.keyboard.press('F1'); await page.waitForTimeout(600); await page.keyboard.type(text); await page.waitForTimeout(1200); };
(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rm-cs-'));
  const userDir = path.join(tmp, 'user-data'), extDir = path.join(tmp, 'extensions'), folder = process.env.FOLDER_ELSE ? fs.mkdtempSync(path.join(os.tmpdir(), 'rm-work-')) : path.join(tmp, 'work');
  for (const d of [path.join(userDir, 'User'), path.join(userDir, 'Machine'), extDir, folder]) fs.mkdirSync(d, { recursive: true });
  spawnSync('git', ['init', '-q', folder]);
  fs.writeFileSync(path.join(folder, 'a.txt'), 'hello\n');
  const settings = JSON.stringify({ 'security.workspace.trust.enabled': process.env.TRUST_OFF ? false : true, 'security.workspace.trust.startupPrompt': 'never', 'security.workspace.trust.emptyWindow': false,
    'workbench.startupEditor': 'none', 'workbench.tips.enabled': false, 'telemetry.telemetryLevel': 'off', 'extensions.autoUpdate': false, 'edp.boardUrl': 'http://127.0.0.1:9', ...(process.env.SEED_TRUST ? { 'extensions.supportUntrustedWorkspaces': { 'edp.edp-code': { supported: 'limited' } } } : {}) }, null, 1);
  fs.writeFileSync(path.join(userDir, 'User/settings.json'), settings); fs.writeFileSync(path.join(userDir, 'Machine/settings.json'), settings);
  const config = path.join(tmp, 'config.yaml'); fs.writeFileSync(config, 'auth: none\ncert: false\n');
  const base = ['--config', config, '--user-data-dir', userDir, '--extensions-dir', extDir];
  const inst = spawnSync(NODE, [TOOLS, ...base, '--install-extension', vsix, '--force'], { env: env(), encoding: 'utf8', timeout: 120000 });
  if (inst.status !== 0) throw new Error(`vsix install failed: ${inst.stdout} ${inst.stderr}`);
  const list = spawnSync(NODE, [TOOLS, ...base, '--list-extensions', '--show-versions'], { env: env(), encoding: 'utf8', timeout: 60000 });
  L(`[${label}] extensions: ${list.stdout.trim().replace(/\s+/g, ' ')}`);
  const port = await freePort();
  const cs = spawn(NODE, [TOOLS, ...base, '--bind-addr', `127.0.0.1:${port}`, '--auth', 'none', '--disable-telemetry', '--disable-update-check', '--disable-proxy'], { env: env(), stdio: 'ignore', windowsHide: true });
  const stop = () => { if (cs.pid && cs.exitCode === null) spawnSync('taskkill', ['/PID', String(cs.pid), '/T', '/F'], { stdio: 'ignore' }); };
  let fails = 0; const check = (ok, what) => { L(`${ok ? 'ok  ' : 'FAIL'} [${label}] ${what}`); if (!ok) fails++; };
  try {
    for (const end = Date.now() + 60000; ; await new Promise(r => setTimeout(r, 300))) { try { if ((await fetch(`http://127.0.0.1:${port}/healthz`)).ok) break; } catch { /* not up */ } if (Date.now() > end) throw new Error('code-server did not answer'); }
    const browser = await pw.chromium.launch({ headless: true, executablePath: path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe') }); const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
    await page.goto(`http://127.0.0.1:${port}/?folder=${encodeURIComponent('/' + folder.replace(/\\/g, '/'))}`);
    await page.waitForSelector('.monaco-workbench', { timeout: 60000 });
    await page.waitForTimeout(12000); // the extension host starts, onStartupFinished fires
    check((await page.locator('.statusbar').getByText(/Restricted Mode/i).count()) > 0, 'the status bar says Restricted Mode (the folder is NOT trusted)');
    if (process.env.EXT_STATUS) { // what the workbench itself says about the extension (Extensions view, installed)
      await palette(page, 'Extensions: Show Installed Extensions'); await page.keyboard.press('Enter'); await page.waitForTimeout(2500);
      await page.locator('.extension-list-item').first().click(); await page.waitForTimeout(3000);
      await page.screenshot({ path: path.join(outDir, `${label}-0-extension.png`) });
      L(`[${label}] extension editor: ${(await page.locator('.extension-editor, .extensions-viewlet').allInnerTexts()).join(' ').replace(/s+/g, ' ').slice(0, 400)}`);
      await page.keyboard.press('Escape');
    }
    if (process.env.RUNNING) {
      await page.keyboard.press('Escape'); await palette(page, 'Developer: Show Running Extensions'); await page.keyboard.press('Enter'); await page.waitForTimeout(4000);
      await page.screenshot({ path: path.join(outDir, `${label}-0-running.png`) });
      L(`[${label}] running extensions: ${(await page.locator('.runtime-extensions-editor').allInnerTexts()).join(' ').replace(/\s+/g, ' ').slice(0, 1500)}`);
      await page.keyboard.press('Escape');
    }
    await palette(page, 'Heronry:');
    const cmds = await page.locator('.quick-input-list .monaco-list-row').allInnerTexts();
    await page.screenshot({ path: path.join(outDir, `${label}-1-commands.png`) });
    const have = cmds.filter(c => /Heronry/i.test(c)).length;
    L(`[${label}] palette rows for "Heronry:": ${have}`);
    if (expect === 'present') check(have > 0, 'Heronry commands exist in Restricted Mode (the extension activated)');
    else check(have === 0, 'no Heronry commands: the extension did not activate (this is the 0.10.6 manifest)');
    if (expect === 'present') {
      await page.keyboard.press('Escape');
      await palette(page, 'Heronry: Open Chat'); await page.keyboard.press('Enter'); await page.waitForTimeout(4000);
      check((await page.getByText('Heronry Chat').count()) > 0, 'the Heronry Chat view is on screen');
      await page.screenshot({ path: path.join(outDir, `${label}-2-chat-view.png`) });
      await palette(page, 'Heronry: Checkout'); await page.keyboard.press('Enter'); await page.waitForTimeout(3000);
      const toasts = (await page.locator('.notifications-toasts, .notification-list-item').allInnerTexts()).join(' | ').replace(/\s+/g, ' ');
      L(`[${label}] after a guarded git command: ${toasts.slice(0, 300)}`);
      check(/Restricted Mode|trust|no git repository/i.test(toasts), 'a guarded git command is refused (Restricted Mode / no repository text)');
      await page.screenshot({ path: path.join(outDir, `${label}-3-git-refused.png`) });
    }
    await browser.close();
  } finally { stop(); }
  L(fails ? `${fails} FAILED` : 'ALL OK'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
