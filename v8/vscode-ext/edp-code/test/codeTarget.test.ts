import { describe, expect, it, vi } from 'vitest';
import { COMMIT, codeTarget, pullText, safeRelPath } from '../src/core/codeTarget';

const a = { repo_root: 'C:\\Projects\\Learning\\eda-base3', path: 'v8/src/edp8/board.py', line_start: 10, line_end: 20, commit: 'abc1234' };

describe('codeTarget', () => {
  it('resolves the repo-relative path in the matching local repo first', () => {
    const roots = ['D:\\other', 'c:\\projects\\learning\\eda-base3'];
    expect(codeTarget(a, roots, () => true)).toEqual({ root: 'c:\\projects\\learning\\eda-base3', path: 'v8/src/edp8/board.py', line_start: 10, line_end: 20, commit: 'abc1234' });
  });

  it('falls back to any open repo that has the file (a teammate clone)', () => {
    const t = codeTarget(a, ['/home/ravi/eda-base3'], (r, p) => r === '/home/ravi/eda-base3' && p === 'v8/src/edp8/board.py');
    expect(t).toMatchObject({ root: '/home/ravi/eda-base3' });
  });

  it('says so when no open repo has the file', () => {
    expect(codeTarget(a, ['D:\\x'], () => false)).toEqual({ error: 'v8/src/edp8/board.py is not in any open repo' });
  });

  it('refuses absolute, backslashed and climbing paths', () => {
    for (const p of ['../secret', 'v8/../../x', '/etc/passwd', 'C:/x', 'v8\\x', '', 'v8//x', './x']) {
      expect(safeRelPath(p), p).toBeUndefined();
      expect('error' in codeTarget({ ...a, path: p }, ['C:\\r'], () => true)).toBe(true);
    }
  });

  it('clamps bad line numbers', () => {
    expect(codeTarget({ ...a, line_start: 0, line_end: -3 }, ['C:\\r'], () => true)).toMatchObject({ line_start: 1, line_end: 1 });
  });
});

// C6 (s-6a52d6545a): a teammate's second clone at another path, which may be behind the host
describe('codeTarget on a second clone', () => {
  const sha = 'e07da58' + '0'.repeat(33);
  const host = 'C:\\Projects\\Learning\\eda-base3';
  const clone = 'D:\\work\\eda-base3-clone';
  const b = { ...a, repo_root: host, commit: sha };

  it('opens the file in the clone, never the host path, when the clone has the commit', () => {
    const t = codeTarget(b, [clone], () => true, (r, c) => r === clone && c === sha);
    expect(t).toEqual({ root: clone, path: 'v8/src/edp8/board.py', line_start: 10, line_end: 20, commit: sha });
  });

  it('prefers the root that has the anchored commit over the repo_root match', () => {
    const t = codeTarget(b, [host, clone], () => true, r => r === clone);
    expect(t).toMatchObject({ root: clone });
    expect(t).not.toHaveProperty('missingCommit');
  });

  it('says pull to see this change when no local repo has the commit and the file is absent', () => {
    const t = codeTarget(b, [clone], () => false, () => false);
    expect(t).toEqual({ pull: sha, path: 'v8/src/edp8/board.py' });
    expect(pullText(sha)).toBe('e07da58 is not in this clone; pull to see this change.');
  });

  it('opens the clone\'s own copy, marked missingCommit, when the commit is absent but the file exists', () => {
    expect(codeTarget(b, [clone], () => true, () => false)).toMatchObject({ root: clone, missingCommit: true });
  });

  it('flags missingCommit when the root with the file lacks the commit that another open repo has', () => {
    const other = 'D:\\work\\other';
    const t = codeTarget(b, [clone, other], (r) => r === clone, (r) => r === other);
    expect(t).toMatchObject({ root: clone, missingCommit: true });
  });

  it('keeps the file-only rule when the commit is elsewhere locally but the file moved away', () => {
    expect(codeTarget(b, [clone], () => false, () => true)).toEqual({ error: 'v8/src/edp8/board.py is not in any open repo' });
  });

  it('never probes git for a null or non-sha commit', () => {
    const probe = vi.fn(() => false);
    expect(codeTarget({ ...b, commit: null }, [clone], () => true, probe)).toMatchObject({ root: clone, commit: null });
    expect(codeTarget({ ...b, commit: '--output=x' }, [clone], () => true, probe)).toMatchObject({ root: clone });
    expect(probe).not.toHaveBeenCalled();
    expect(COMMIT.test('-' + sha.slice(1))).toBe(false);
  });
});
