// Commit attribution over REAL git output (c-9e371f7eff): bytes captured from the shared tree, plus a
// throwaway repo built here with the host's git so merge / rename / binary / root / trailer-placement
// cases are what git itself prints, never hand-written strings.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  attribute, commitWindow, index, logArgs, mergeNewer, naming, parseLog, storyCounts, unlinked, type Commit, type Indexed,
} from '../src/core/commits';

const fixture = (f: string) => readFileSync(join(import.meta.dirname, 'fixtures', f), 'utf8');

describe('parseLog on bytes captured from the shared tree', () => {
  it('f1fca1c (the C2 trailer commit): trailers, 7 modified files, numstat', () => {
    const [c, ...more] = parseLog(fixture('git-log-f1fca1c.bin'));
    expect(more).toEqual([]);
    expect(c.sha).toBe('f1fca1cdc61cc6803c00b00ca736b6323a797245');
    expect(c.parents).toEqual(['3f696c66b4a2cd6fdf470fad3749805c3b83c8a2']);
    expect(c.trailerTickets).toEqual(['s-20fd7644af']);
    expect(c.trailerSeats).toEqual(['engineer.s-20fd7644af']);
    expect(c.files).toHaveLength(7);
    expect(c.files[0]).toEqual({ path: 'v8/.claude/commands/adversary.md', status: 'M', add: 1, del: 0 });
    expect(c.files.at(-1)).toEqual({ path: 'v8/guides/shared-host-rules.md', status: 'M', add: 9, del: 0 });
    expect(attribute(c)).toEqual({ tickets: ['s-20fd7644af'], attribution: 'trailer', trailerSeat: 'engineer.s-20fd7644af' });
  });
  it('85d00e4: renames keep old and new path, numstat lands on the new path', () => {
    const [c] = parseLog(fixture('git-log-85d00e4-renames.bin'));
    expect(c.files[0]).toEqual({ path: '.gitignore', status: 'M', add: 8, del: 0 });
    const r = c.files.find(f => f.path === 'archive/root-v7/eda.bat')!;
    expect(r).toEqual({ path: 'archive/root-v7/eda.bat', oldPath: 'eda.bat', status: 'R', add: 0, del: 0 });
    expect(c.files.filter(f => f.status === 'R').length).toBeGreaterThan(5);
    expect(attribute(c).attribution).toBe('none');
  });
});

// -- a real repo -----------------------------------------------------------------------------------
let dir = '';
let log: Commit[] = [];
const bySubject = (s: string) => log.find(c => c.subject === s)!;
function git(args: string[], env: Record<string, string> = {}) {
  return execFileSync('git', args, { cwd: dir, encoding: 'utf8', env: { ...process.env, ...env } });
}
// distinct, increasing times so the log order is deterministic (git orders by commit date)
let tick = Math.floor(Date.now() / 1000) - 3600;
const when = () => { const d = `${(tick += 60)} +0000`; return { GIT_AUTHOR_DATE: d, GIT_COMMITTER_DATE: d }; };
const commit = (subject: string, body?: string) => git(['commit', '-q', '-m', subject, ...(body ? ['-m', body] : [])], when());

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'edp-commits-'));
  git(['init', '-q', '-b', 'main']);
  git(['config', 'user.name', 'T']); git(['config', 'user.email', 't@x']); git(['config', 'commit.gpgsign', 'false']); git(['config', 'core.autocrlf', 'false']);
  writeFileSync(join(dir, 'a.txt'), 'one\ntwo\nthree\nfour\nfive\nsix\n');
  writeFileSync(join(dir, 'b.bin'), Buffer.from([0, 1, 2, 0, 255, 0]));
  git(['add', '.']); commit('root: first files');
  writeFileSync(join(dir, 'a.txt'), 'one\ntwo\nthree\nfour\nfive\nsix\nseven\n');
  git(['add', '.']); commit('feat: trailer commit', 'Why it changed.\n\nEDP-Ticket: s-0123456789\nEDP-Seat: engineer.s-0123456789');
  writeFileSync(join(dir, 'b.bin'), Buffer.from([0, 9, 9, 0, 255, 0, 7]));
  git(['add', '.']); commit('fix(t-abcdef0123): binary edit', 'The body cites s-1111111111, which must not attribute.');
  writeFileSync(join(dir, 'n.txt'), 'n\n');
  git(['add', '.']); commit('docs: trailer-like line in the middle', 'EDP-Ticket: s-2222222222\n\nThe last paragraph is plain prose.');
  git(['mv', 'a.txt', 'c.txt']); commit('chore: rename a to c');
  git(['rm', '-q', 'b.bin']); commit('chore: delete the binary', 'EDP-Ticket: s-0123456789\nEDP-Ticket: t-9999999999\nEDP-Seat: engineer.s-0123456789');
  writeFileSync(join(dir, 'm.txt'), 'm\n');
  git(['add', '.']); commit('bad trailer s-5555555555', 'EDP-Ticket: not-a-ticket\nEDP-Seat: engineer.s-5555555555');
  git(['checkout', '-q', '-b', 'side']);
  writeFileSync(join(dir, 'd.txt'), 'side\n'); git(['add', '.']); commit('side work s-3333333333');
  git(['checkout', '-q', 'main']);
  // an amended/cherry-picked commit keeps its old author date: cards are placed by commit time
  writeFileSync(join(dir, 'e.txt'), 'main\n'); git(['add', '.']);
  git(['commit', '-q', '-m', 'main work'], { ...when(), GIT_AUTHOR_DATE: `${tick - 3 * 86400} +0000` });
  git(['merge', '-q', '--no-ff', 'side', '-m', 'Merge branch side', '-m', 'EDP-Ticket: epic-4444444444'], when());
  log = parseLog(git(logArgs({ count: 100, days: 30 })));
});
afterAll(() => { if (dir) rmSync(dir, { recursive: true, force: true }); });

describe('parseLog + attribute on a real repo', () => {
  it('reads every commit, newest first', () => {
    expect(log.map(c => c.subject)).toEqual([
      'Merge branch side', 'main work', 'side work s-3333333333', 'bad trailer s-5555555555', 'chore: delete the binary',
      'chore: rename a to c', 'docs: trailer-like line in the middle', 'fix(t-abcdef0123): binary edit', 'feat: trailer commit', 'root: first files',
    ]);
  });
  it('EDP-Ticket/EDP-Seat trailers -> trailer attribution with the seat', () => {
    const c = bySubject('feat: trailer commit');
    expect(attribute(c)).toEqual({ tickets: ['s-0123456789'], attribution: 'trailer', trailerSeat: 'engineer.s-0123456789' });
    expect(c.files).toEqual([{ path: 'a.txt', status: 'M', add: 1, del: 0 }]);
  });
  it('several EDP-Ticket trailers attribute the commit to each', () =>
    expect(attribute(bySubject('chore: delete the binary')).tickets).toEqual(['s-0123456789', 't-9999999999']));
  it('an id only in the subject -> subject attribution; an id in the body is not read', () =>
    expect(attribute(bySubject('fix(t-abcdef0123): binary edit'))).toEqual({ tickets: ['t-abcdef0123'], attribution: 'subject', trailerSeat: null }));
  it('no id -> none (unlinked)', () => expect(attribute(bySubject('main work')).attribution).toBe('none'));
  it('a trailer-like line outside the last paragraph is ignored', () => {
    const c = bySubject('docs: trailer-like line in the middle');
    expect(c.trailerTickets).toEqual([]);
    expect(attribute(c)).toEqual({ tickets: [], attribution: 'none', trailerSeat: null });
  });
  it('a malformed trailer value falls through to the subject id', () =>
    expect(attribute(bySubject('bad trailer s-5555555555'))).toEqual({ tickets: ['s-5555555555'], attribution: 'subject', trailerSeat: 'engineer.s-5555555555' }));
  it('a merge commit: two parents, files diffed against the first parent, trailer on the merge message', () => {
    const c = bySubject('Merge branch side');
    expect(c.parents).toHaveLength(2);
    expect(c.parents[0]).toBe(bySubject('main work').sha);
    expect(c.files).toEqual([{ path: 'd.txt', status: 'A', add: 1, del: 0 }]);
    expect(attribute(c).tickets).toEqual(['epic-4444444444']);
  });
  it('a rename carries old and new path', () =>
    expect(bySubject('chore: rename a to c').files).toEqual([{ path: 'c.txt', oldPath: 'a.txt', status: 'R', add: 0, del: 0 }]));
  it('a binary edit has null counts; a delete is D', () => {
    expect(bySubject('fix(t-abcdef0123): binary edit').files).toEqual([{ path: 'b.bin', status: 'M', add: null, del: null }]);
    expect(bySubject('chore: delete the binary').files).toEqual([{ path: 'b.bin', status: 'D', add: null, del: null }]);
  });
  it('the root commit has no parents and adds its files', () => {
    const c = bySubject('root: first files');
    expect(c.parents).toEqual([]);
    expect(c.files.map(f => [f.path, f.status])).toEqual([['a.txt', 'A'], ['b.bin', 'A']]);
  });
  it('time is the commit time (ms), not the author time', () => {
    const c = bySubject('main work');
    const [ct, at] = git(['log', '-1', '--format=%ct %at', c.sha]).trim().split(' ').map(Number);
    expect(ct - at).toBeGreaterThan(2 * 86400);
    expect(c.at).toBe(ct * 1000);
  });
  it('an incremental read <old>..HEAD returns only the newer commits', () => {
    const old = bySubject('main work').sha;
    expect(parseLog(git(logArgs({ count: 100, days: 30 }, `${old}..HEAD`))).map(c => c.subject)).toEqual(['Merge branch side', 'side work s-3333333333']);
  });
});

describe('selection', () => {
  let ix: Indexed[] = [];
  beforeAll(() => { ix = index(log); });
  it('a story thread: commits naming the story or its tasks', () =>
    expect(naming(ix, new Set(['s-0123456789', 't-abcdef0123'])).map(c => c.subject))
      .toEqual(['chore: delete the binary', 'fix(t-abcdef0123): binary edit', 'feat: trailer commit']));
  it('an epic thread: commits naming the epic only', () =>
    expect(naming(ix, new Set(['epic-4444444444'])).map(c => c.subject)).toEqual(['Merge branch side']));
  it('unlinked = attribution none', () =>
    expect(unlinked(ix).map(c => c.subject)).toEqual(['main work', 'chore: rename a to c', 'docs: trailer-like line in the middle', 'root: first files']));
  it('story counts include tasks, each commit once', () =>
    expect(storyCounts(ix, ['s-0123456789', 's-3333333333', 's-7777777777'], new Map([['s-0123456789', ['t-abcdef0123', 't-9999999999']]])))
      .toEqual(new Map([['s-0123456789', 3], ['s-3333333333', 1], ['s-7777777777', 0]])));
  it('mergeNewer dedupes by sha and bounds the window', () => {
    const m = mergeNewer(ix.slice(0, 3), ix.slice(1), 5);
    expect(m.map(c => c.sha)).toEqual(ix.slice(0, 5).map(c => c.sha));
  });
});

describe('window and argv', () => {
  it('defaults and clamps', () => {
    expect(commitWindow(undefined)).toEqual({ count: 500, days: 30 });
    expect(commitWindow({ count: 0, days: -1 })).toEqual({ count: 500, days: 30 });
    expect(commitWindow({ count: 1e9, days: 12.7 })).toEqual({ count: 5000, days: 12 });
  });
  it('argv is bounded, NUL-separated, unquoted paths, first-parent merges; ranges are validated', () => {
    const a = logArgs({ count: 50, days: 7 });
    expect(a).toEqual(expect.arrayContaining(['-c', 'core.quotepath=false', '-z', '--raw', '--numstat', '-M', '--diff-merges=first-parent', '-n', '50', '--since=7.days', 'HEAD']));
    expect(() => logArgs({ count: 1, days: 1 }, '--output=x')).toThrow();
    expect(() => logArgs({ count: 1, days: 1 }, 'HEAD~1..HEAD')).toThrow();
  });
});
