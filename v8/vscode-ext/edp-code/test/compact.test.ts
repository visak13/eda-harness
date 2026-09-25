// @vitest-environment jsdom
// C9 compact webview (s-b084884e6b): the uncommitted chip scoped to the open epic (option (a)), message
// anchors resolved against the shared repo, the per-viewer fold state, and the folded chips (jsdom).
import { describe, expect, it } from 'vitest';
import { parseInbound, type UncommittedCard } from '../src/core/chatProtocol';
import { anchorPath, inScope, sameRows, touchedPaths, uncommittedCard, type WorkFile } from '../src/core/uncommitted';
import { FOLDED, restoreLocal } from '../src/core/viewState';

const work: WorkFile[] = [
  { path: 'v8/a.ts', status: 'M' }, { path: 'v8/b.ts', status: 'M' }, { path: 'v8/new.md', oldPath: 'v8/old.md', status: 'R' },
  { path: 'x/other.py', status: 'U' },
];

describe('touchedPaths: commits naming the scope + anchors', () => {
  const commits = [
    { tickets: ['s-0123456789'], files: [{ path: 'v8/a.ts' }, { path: 'v8/new.md', oldPath: 'v8/old.md' }] },
    { tickets: ['s-9999999999'], files: [{ path: 'x/other.py' }] },
  ];
  it('only commits naming one of the ids count; renames add both sides', () =>
    expect([...touchedPaths(commits, new Set(['s-0123456789']), [])].sort()).toEqual(['v8/a.ts', 'v8/new.md', 'v8/old.md']));
  it('anchors add their paths', () =>
    expect([...touchedPaths(commits, new Set(), ['v8/b.ts'])]).toEqual(['v8/b.ts']));
});

describe('anchorPath: a message anchor relative to the shared repo root', () => {
  const root = 'c:\\Projects\\Learning\\eda-base3';
  it('same root (case and slashes differ): the path as is', () =>
    expect(anchorPath({ repo_root: 'C:/Projects/Learning/eda-base3', path: 'v8/a.ts' }, root)).toBe('v8/a.ts'));
  it('a nested root prefixes its sub-path', () =>
    expect(anchorPath({ repo_root: 'C:/Projects/Learning/eda-base3/v8', path: 'src/x.py' }, root)).toBe('v8/src/x.py'));
  it('a parent root strips it; outside the repo is null', () => {
    expect(anchorPath({ repo_root: 'C:/Projects/Learning', path: 'eda-base3/v8/a.ts' }, root)).toBe('v8/a.ts');
    expect(anchorPath({ repo_root: 'C:/Projects/Learning', path: 'other/a.ts' }, root)).toBeNull();
  });
  it("another machine's root keeps the repo-relative path; unsafe paths are dropped", () => {
    expect(anchorPath({ repo_root: '/home/ravi/eda-base3', path: 'v8/a.ts' }, root)).toBe('v8/a.ts');
    expect(anchorPath({ repo_root: root, path: '../etc/passwd' }, root)).toBeNull();
    expect(anchorPath({ repo_root: root, path: '/abs' }, root)).toBeNull();
    expect(anchorPath({ repo_root: 'x', path: 'v8\\a.ts' }, null)).toBe('v8/a.ts');
  });
});

describe('uncommittedCard with a scope (option (a))', () => {
  const scope = { kind: 'epic' as const, paths: new Set(['v8/b.ts', 'v8/old.md']) };
  const card = uncommittedCard(work, scope, new Date('2026-09-25T07:00:00Z'));
  it('touched rows first and flagged (a rename matches by its old path); scoped counts them', () => {
    expect(card.files.map(f => [f.path, !!f.touched])).toEqual([['v8/b.ts', true], ['v8/new.md', true], ['v8/a.ts', false], ['x/other.py', false]]);
    expect([card.scoped, card.total, card.scope]).toEqual([2, 4, 'epic']);
  });
  it('touched rows are never cut by the cap', () => {
    const many: WorkFile[] = Array.from({ length: 250 }, (_, i) => ({ path: `f${String(i).padStart(3, '0')}`, status: 'M' }));
    const c = uncommittedCard(many, { kind: 'epic', paths: new Set(['f249']) });
    expect(c.files[0]).toMatchObject({ path: 'f249', touched: true });
    expect([c.files.length, c.more, c.scoped]).toEqual([200, 50, 1]);
  });
  it('a scope change is a new card to post; the same scope is not', () => {
    expect(sameRows(card, uncommittedCard(work, scope))).toBe(true);
    expect(sameRows(card, uncommittedCard(work, { kind: 'epic', paths: new Set(['v8/a.ts']) }))).toBe(false);
    expect(sameRows(card, uncommittedCard(work, null))).toBe(false);
  });
  it('inScope', () => {
    expect(inScope({ path: 'n', oldPath: 'v8/old.md' }, scope.paths)).toBe(true);
    expect(inScope({ path: 'v8/a.ts' }, scope.paths)).toBe(false);
  });
});

describe('parseInbound: openUncommitted.scoped', () => {
  it('scoped: true passes; anything else is refused', () => {
    expect(parseInbound({ v: 1, type: 'openUncommitted', scoped: true })).toEqual({ v: 1, type: 'openUncommitted', scoped: true });
    expect(parseInbound({ v: 1, type: 'openUncommitted', scoped: 'yes' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'openUncommitted', scoped: false })).toBeNull();
  });
});

describe('restoreLocal: the per-viewer fold state survives a reload', () => {
  const base = { v: 1, drafts: {}, kind: 'note', fold: FOLDED, tab: 'chat', seen: {}, inbox: {}, replies: {}, who: null, others: {} };
  it('nothing saved: the scope open, the rest folded, kind note, the Chat tab', () =>
    expect(restoreLocal(undefined)).toEqual(base));
  it('round-trips what the view saved (JSON, as getState/setState do)', () => {
    const saved = { v: 1, drafts: { 'epic-0123456789': 'half a thought' }, kind: 'steer', fold: { scoped: false, unlinked: true, allSeats: true },
      tab: 'commits', seen: { 'epic-0123456789': '2026-09-25T07:00:00.000Z' }, inbox: { 'q:m-0123456789': 'half an answer' },
      replies: { 's-0123456789': { id: 'm-0123456789', by: 'owner', excerpt: 'the parent', to: 'owner' } },
      who: '["http://127.0.0.1:9400","owner"]', others: { '["http://127.0.0.1:9400","qa"]': { drafts: { 's-0123456789': 'qa draft' }, inbox: {}, replies: {} } } };
    expect(restoreLocal(JSON.parse(JSON.stringify(saved)))).toEqual(saved);
  });
  it('a 0.4.0 state (no fold) keeps drafts and takes the defaults', () =>
    expect(restoreLocal({ v: 1, drafts: { 's-0123456789': 'x' }, kind: 'question' })).toEqual({ ...base, drafts: { 's-0123456789': 'x' }, kind: 'question' }));
  it('garbage never throws and never smuggles fields', () => {
    expect(restoreLocal({ v: 1, drafts: { bad: 'x', 's-0123456789': 7 }, kind: 'rm -rf', fold: { uncommitted: 'yes', extra: true }, tab: '<b>', seen: { bad: 'x', 's-0123456789': 'not a date' } }))
      .toEqual(base);
    for (const g of [null, 7, 'x', [], { v: 2, fold: { scoped: false } }]) expect(restoreLocal(g).fold).toEqual(FOLDED);
  });
});
