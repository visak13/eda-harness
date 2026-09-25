// Live checks of the running `code` service (s-3c8c2512d6), re-runnable by qa:
//   node scripts/verify-code-service.mjs [outDir]
// Needs the service up (.\edp.ps1 start code) and Playwright from web/node_modules.
//  1. GitLens blame hover on a v8 line whose commit message holds t-3e246b5e32 shows a link to
//     http://127.0.0.1:<board>/ui/ticket/t-3e246b5e32 (c-353bd62e1d, design v2 section 4).
//  2. The integrated terminal (default profile, Windows PowerShell 5.1) has NO EDP_*/EDP8_* variable
//     (dec-ea925a2d30; strategyhl-e69dbbae06 env-strip proof).
// Prints one PASS/FAIL line per check, writes screenshots to outDir, exits 1 on any FAIL.
import { createRequire } from 'module';
import { execFileSync } from 'child_process';
import { mkdirSync, readFileSync, existsSync, rmSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const V8 = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(V8, 'web', 'package.json'));
const { chromium } = require('playwright');
const OUT = path.resolve(process.argv[2] || path.join(V8, '.data', 'code', 's2-evidence'));
mkdirSync(OUT, { recursive: true });
const PORT = process.env.EDP_CODE_PORT || '9410';
const BOARD = `http://127.0.0.1:${process.env.EDP8_PORT || '9400'}`;
const ID = 't-3e246b5e32';

// a line whose blame commit message names ID: newest commit touching a tracked file that mentions it
function blameTarget() {
  const shas = execFileSync('git', ['-C', V8, 'log', '--format=%H', `--grep=${ID}`, '-n', '30'], { encoding: 'utf8' }).split('\n').filter(Boolean);
  for (const sha of shas) {
    const files = execFileSync('git', ['-C', V8, 'show', '--format=', '--name-only', '--relative', sha], { encoding: 'utf8' })
      .split('\n').filter(f => f.endsWith('.py') && existsSync(path.join(V8, f)));
    for (const f of files) {
      const blame = execFileSync('git', ['-C', V8, 'blame', '-l', '-s', '--', f], { encoding: 'utf8' }).split('\n');
      const i = blame.findIndex(l => l.startsWith(sha) && l.slice(41).replace(/^\s*\d+\)\s?/, '').trim().length > 12);
      if (i >= 0) return { sha, file: f, line: i + 1, text: blame[i].slice(41).replace(/^\s*\d+\)\s?/, '') };
    }
  }
  throw new Error(`no blamed line for ${ID}`);
}

const results = [];
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1500, height: 950 } });
const folder = '/' + V8.replace(/\\/g, '/').replace(/^([A-Za-z]):/, (m, d) => d.toLowerCase() + ':');
await p.goto(`http://127.0.0.1:${PORT}/?folder=${folder}`);
await p.waitForSelector('.monaco-workbench', { timeout: 60000 });
await p.waitForTimeout(8000);

// -- 1. blame hover -----------------------------------------------------------------------------
try {
  const t = blameTarget();
  await p.keyboard.press('Control+P'); await p.waitForTimeout(800);
  await p.keyboard.type(t.file.replace(/\\/g, '/')); await p.waitForTimeout(1500);
  await p.keyboard.press('Enter'); await p.waitForTimeout(3000);
  await p.keyboard.press('Control+G'); await p.waitForTimeout(500);
  await p.keyboard.type(String(t.line)); await p.keyboard.press('Enter'); await p.waitForTimeout(4000);
  // Ctrl+G leaves the cursor on the target line: hover the text area of the highlighted current line
  // (Monaco renders spaces as U+00A0, so matching the line by its text is unreliable)
  const lineEl = p.locator('.view-overlays .current-line').first();
  let href = null;
  for (let attempt = 0; attempt < 6 && !href; attempt++) {
    const box = await lineEl.boundingBox();
    await p.mouse.move(box.x + 260 + attempt * 45, box.y + box.height / 2);
    await p.waitForTimeout(3500);
    const links = await p.locator('.monaco-hover a').evaluateAll(as => as.map(a => [a.textContent, a.getAttribute('data-href') || a.getAttribute('href') || '', a.getAttribute('title') || '']));
    // GitLens renders an autolink as command:gitlens.action.openIssue?<url-encoded {issue:{url}}>
    href = links.map(l => decodeURIComponent(l[1]) + ' ' + l[2]).map(h => (h.match(/https?:\/\/[^\s"')]+\/ui\/ticket\/[\w-]+/) || [null])[0]).find(h => h && h.endsWith(ID)) || null;
  }
  await p.screenshot({ path: path.join(OUT, 'blame-hover.png') });
  const ok = href === `${BOARD}/ui/ticket/${ID}`;
  results.push([ok, `blame hover on ${t.file}:${t.line} (commit ${t.sha.slice(0, 7)}) links ${ID} -> ${href}`]);
} catch (e) { results.push([false, `blame hover: ${e.message}`]); }

// -- 2. terminal env ----------------------------------------------------------------------------
try {
  const marker = path.join(OUT, 'term-env.txt');
  rmSync(marker, { force: true });
  await p.keyboard.press('Escape');
  await p.keyboard.press('Control+Backquote'); await p.waitForTimeout(7000);
  const cmd = `"FLEETVARS=[" + ((Get-ChildItem env: | Where-Object Name -match '^EDP8?_' | ForEach-Object Name) -join ',') + "] PS=" + $PSVersionTable.PSVersion | Out-File -Encoding ascii '${marker}'`;
  await p.keyboard.type(cmd); await p.keyboard.press('Enter'); await p.waitForTimeout(5000);
  await p.screenshot({ path: path.join(OUT, 'term-env.png') });
  const txt = existsSync(marker) ? readFileSync(marker, 'utf8').trim() : '(no marker written)';
  results.push([txt.startsWith('FLEETVARS=[]'), `terminal env: ${txt}`]);
} catch (e) { results.push([false, `terminal env: ${e.message}`]); }

await b.close();
for (const [ok, msg] of results) console.log(`${ok ? 'PASS' : 'FAIL'} ${msg}`);
process.exit(results.every(r => r[0]) ? 0 : 1);
