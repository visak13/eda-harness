// C6 (s-6a52d6545a) second-clone check: the extension's own core, run against a REAL second clone of
// this repo at another path that is BEHIND the host (its newest commits pruned), with real git and fs.
// It is what the extension host does on a teammate's machine: code cards (codeTarget + `git cat-file`
// + stat) and change cards (the clone's own `git log` index, diff sides joined to the clone root, the
// openDiff presence gate). Prints one PASS/FAIL row per check; exit 1 on any FAIL. The clone is made
// in a temp dir and removed at the end. Run from v8/vscode-ext/edp-code:
//   npx esbuild measure/c6-second-clone.ts --bundle --platform=node --format=cjs --outfile=%TEMP%\c6.cjs; node %TEMP%\c6.cjs [hostRepo] [behind=3]
import { execFileSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { COMMIT, codeTarget, pullText } from '../src/core/codeTarget';
import { commitWindow, logArgs, parseLog } from '../src/core/commits';
import { sides } from '../src/core/diffSides';

const host = path.resolve(process.argv[2] ?? process.cwd()); // the bundle runs from %TEMP%: no __dirname
const behind = Number(process.argv[3] ?? 3);
const git = (cwd: string, args: string[]) => execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 64 << 20, stdio: ['ignore', 'pipe', 'pipe'] });
const has = (root: string, sha: string) => { try { git(root, ['cat-file', '-e', `${sha}^{commit}`]); return true; } catch { return false; } };
const exists = (root: string, rel: string) => fs.existsSync(path.join(root, ...rel.split('/')));

let fails = 0;
const row = (ok: boolean, what: string, got: unknown) => { if (!ok) fails++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${what}  -> ${JSON.stringify(got)}`); };

const hostRoot = git(host, ['rev-parse', '--show-toplevel']).trim();
const head = git(hostRoot, ['rev-parse', 'HEAD']).trim();
const old = git(hostRoot, ['rev-parse', `HEAD~${behind}`]).trim();
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'edp-c6-clone-'));
const clone = path.join(tmp, 'eda-base3-teammate');
try {
  git(tmp, ['clone', '-q', '--depth', String(behind + 20), '--no-checkout', 'file:///' + hostRoot.replace(/\\/g, '/'), clone]);
  git(clone, ['checkout', '-q', '-B', 'main', old]);
  // a teammate who has not pulled: the host's newer commits are not in this clone at all
  for (const ref of ['refs/remotes/origin/main', 'refs/remotes/origin/HEAD']) { try { git(clone, ['update-ref', '-d', ref]); } catch { /* absent */ } }
  git(clone, ['reflog', 'expire', '--expire=now', '--all']);
  git(clone, ['gc', '-q', '--prune=now']);
  console.log(`host ${hostRoot} @ ${head.slice(0, 7)}; clone ${clone} @ ${old.slice(0, 7)} (${behind} behind)`);

  // -- code cards: the anchor carries the HOST's absolute repo_root; only `path` is used -------------
  const file = 'v8/vscode-ext/edp-code/src/core/codeTarget.ts';
  const atOld = { repo_root: hostRoot, path: file, line_start: 3, line_end: 5, commit: old };
  const t1 = codeTarget(atOld, [clone], exists, has);
  row('root' in t1 && t1.root === clone && !('missingCommit' in t1), 'code card, commit in the clone: opens the file in the clone, not the host repo_root', t1);

  const atHead = { ...atOld, commit: head };
  const t2 = codeTarget(atHead, [clone], exists, has);
  row('root' in t2 && t2.root === clone && t2.missingCommit === true, 'code card, commit only on the host, file in the clone: opens the clone copy, flagged missingCommit', t2);

  const onlyOnHost = fs.readdirSync(hostRoot).find(n => fs.statSync(path.join(hostRoot, n)).isFile() && !exists(clone, n));
  if (onlyOnHost) {
    const t3 = codeTarget({ ...atHead, path: onlyOnHost }, [clone], exists, has);
    row('pull' in t3 && t3.pull === head, `code card, commit and file (${onlyOnHost}) only on the host: "pull to see this change", no error`, 'pull' in t3 ? pullText(t3.pull) : t3);
  } else console.log('SKIP  no host-only file to anchor');

  const t4 = codeTarget(atHead, [hostRoot, clone], exists, has);
  row('root' in t4 && t4.root === hostRoot, 'both repos open: the one holding the commit wins', t4);

  // -- change cards: the clone's own log is the index; diffs join the clone root -------------------
  const idx = parseLog(git(clone, logArgs(commitWindow({ count: 50, days: 3650 }))));
  const shas = new Set(idx.map(c => c.sha));
  row(shas.has(old) && !shas.has(head), 'change-card index is the clone\'s own history (has its HEAD, not the host HEAD)', { indexed: idx.length, hasOld: shas.has(old), hasHead: shas.has(head) });

  const c = idx.find(x => x.files.length > 0)!;
  const empty = git(clone, ['hash-object', '-t', 'tree', '--stdin']).trim() || '4b825dc642cb6eb9a060e54bf8d69288fbee4904';
  const s = sides(c, c.files[0], empty, p => path.join(clone, ...p.split('/')), (u, ref) => `${u}@${ref}`);
  row(String(s.r).startsWith(clone) && String(s.l).startsWith(clone), 'change-card file diff sides resolve under the clone root', { l: s.l, r: s.r });

  const gate = (sha: string) => (COMMIT.test(sha) && has(clone, sha) ? 'open diff' : pullText(sha));
  row(gate(c.sha) === 'open diff', 'openDiff gate, commit in the clone: opens', gate(c.sha));
  row(gate(head) === pullText(head), 'openDiff gate, commit not in the clone: "pull to see this change"', gate(head));
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
console.log(fails ? `${fails} FAILED` : 'ALL PASS');
process.exit(fails ? 1 : 0);
