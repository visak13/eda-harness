import { describe, expect, it } from 'vitest';
import type { FileChange } from '../src/core/commits';
import { cardTitle, diffArgs, fileTitle, sides, workSides } from '../src/core/diffSides';

const EMPTY = '4b825dc642cb6eb9a060e54bf8d69288fbee4904';
const at = (p: string) => `file:///repo/${p}`;
const git = (u: string, ref: string) => `git:${u}@${ref}`;
const C = { sha: 'c'.repeat(40), parents: ['p'.repeat(40)], subject: 'feat: x' };
const f = (status: FileChange['status'], path = 'v8/a.ts', oldPath?: string): FileChange =>
  ({ path, status, add: 1, del: 0, ...(oldPath ? { oldPath } : {}) });

describe('sides (vscode.changes triples)', () => {
  it('M: parent left, commit right', () =>
    expect(sides(C, f('M'), EMPTY, at, git)).toEqual({ label: at('v8/a.ts'), l: git(at('v8/a.ts'), C.parents[0]), r: git(at('v8/a.ts'), C.sha) }));
  it('A: no left side', () => expect(sides(C, f('A'), EMPTY, at, git).l).toBeUndefined());
  it('D: no right side, left at the parent', () => {
    const s = sides(C, f('D'), EMPTY, at, git);
    expect(s.r).toBeUndefined();
    expect(s.l).toBe(git(at('v8/a.ts'), C.parents[0]));
  });
  it('R: the old path on the left', () =>
    expect(sides(C, f('R', 'v8/new.ts', 'v8/old.ts'), EMPTY, at, git))
      .toEqual({ label: at('v8/new.ts'), l: git(at('v8/old.ts'), C.parents[0]), r: git(at('v8/new.ts'), C.sha) }));
  it('root commit: the empty tree on the left', () =>
    expect(sides({ ...C, parents: [] }, f('M'), EMPTY, at, git).l).toBe(git(at('v8/a.ts'), EMPTY)));
  it('merge: the first parent on the left', () =>
    expect(sides({ ...C, parents: ['1'.repeat(40), '2'.repeat(40)] }, f('M'), EMPTY, at, git).l).toBe(git(at('v8/a.ts'), '1'.repeat(40))));
});

describe('diffArgs (vscode.diff needs both sides)', () => {
  it('an added file diffs against the empty tree', () =>
    expect(diffArgs(sides(C, f('A'), EMPTY, at, git), EMPTY, git)).toEqual([git(at('v8/a.ts'), EMPTY), git(at('v8/a.ts'), C.sha)]));
  it('a deleted file diffs to the empty tree', () =>
    expect(diffArgs(sides(C, f('D'), EMPTY, at, git), EMPTY, git)).toEqual([git(at('v8/a.ts'), C.parents[0]), git(at('v8/a.ts'), EMPTY)]));
});

describe('titles', () => {
  it('card and file', () => {
    expect(cardTitle(C)).toBe('ccccccc feat: x');
    expect(fileTitle(C, f('M'))).toBe('v8/a.ts (ccccccc)');
  });
});

describe('workSides (the uncommitted card)', () => {
  it('modified: HEAD left, the working file right', () =>
    expect(workSides({ path: 'v8/a.ts', status: 'M' }, at, git)).toEqual({ label: at('v8/a.ts'), l: git(at('v8/a.ts'), 'HEAD'), r: at('v8/a.ts') }));
  it('untracked / added: no left', () => {
    expect(workSides({ path: 'n.ts', status: 'U' }, at, git).l).toBeUndefined();
    expect(workSides({ path: 'n.ts', status: 'A' }, at, git).l).toBeUndefined();
  });
  it('deleted: no right', () => expect(workSides({ path: 'd.ts', status: 'D' }, at, git).r).toBeUndefined());
  it('renamed: the old path at HEAD on the left', () =>
    expect(workSides({ path: 'n.ts', oldPath: 'o.ts', status: 'R' }, at, git).l).toBe(git(at('o.ts'), 'HEAD')));
});
