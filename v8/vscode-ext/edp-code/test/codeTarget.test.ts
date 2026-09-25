import { describe, expect, it } from 'vitest';
import { codeTarget, safeRelPath } from '../src/core/codeTarget';

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
