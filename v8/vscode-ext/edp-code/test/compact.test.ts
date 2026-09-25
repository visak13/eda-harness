// @vitest-environment jsdom
// C9 compact webview (s-b084884e6b): the uncommitted chip scoped to the open epic (option (a)), message
// anchors resolved against the shared repo, the per-viewer fold state, and the folded chips (jsdom).
import { describe, expect, it } from 'vitest';
import { parseInbound, type UncommittedCard } from '../src/core/chatProtocol';
import { anchorPath, inScope, sameRows, touchedPaths, uncommittedCard, type WorkFile } from '../src/core/uncommitted';
import { FOLDED, restoreLocal } from '../src/core/viewState';
import { renderUncommitted, uncommittedLabel } from '../webview/cards';

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
  it('nothing saved: everything folded, kind note', () =>
    expect(restoreLocal(undefined)).toEqual({ v: 1, drafts: {}, kind: 'note', fold: FOLDED }));
  it('round-trips what the view saved (JSON, as getState/setState do)', () => {
    const saved = { v: 1, drafts: { 'epic-0123456789': 'half a thought' }, kind: 'steer', fold: { uncommitted: true, unlinked: false, allSeats: true } };
    expect(restoreLocal(JSON.parse(JSON.stringify(saved)))).toEqual(saved);
  });
  it('a 0.4.0 state (no fold) keeps drafts and folds everything', () =>
    expect(restoreLocal({ v: 1, drafts: { 's-0123456789': 'x' }, kind: 'question' })).toEqual({ v: 1, drafts: { 's-0123456789': 'x' }, kind: 'question', fold: FOLDED }));
  it('garbage never throws and never smuggles fields', () => {
    expect(restoreLocal({ v: 1, drafts: { bad: 'x', 's-0123456789': 7 }, kind: 'rm -rf', fold: { uncommitted: 'yes', extra: true } }))
      .toEqual({ v: 1, drafts: {}, kind: 'note', fold: FOLDED });
    for (const g of [null, 7, 'x', [], { v: 2, fold: { uncommitted: true } }]) expect(restoreLocal(g).fold).toEqual(FOLDED);
  });
});

describe('the Uncommitted chip and its list (jsdom)', () => {
  const card: UncommittedCard = uncommittedCard(work, { kind: 'epic', paths: new Set(['v8/b.ts']) });
  it('the chip reads n/N; clean and unscoped variants', () => {
    expect(uncommittedLabel(card).text).toBe('Uncommitted · 1/4');
    expect(uncommittedLabel(card).aria).toBe('Uncommitted changes: 1 file this epic touched, 4 files across all seats');
    expect(uncommittedLabel(null).text).toBe('Uncommitted · clean');
    expect(uncommittedLabel(uncommittedCard(work)).text).toBe('Uncommitted · 4');
  });
  it("scoped: only the epic's rows, a show-all toggle with the rest's count, a scoped multi-diff", () => {
    const box = document.createElement('div');
    const posts: unknown[] = [];
    let all: boolean | undefined;
    renderUncommitted(box, card, false, m => posts.push(m), a => (all = a));
    expect([...box.querySelectorAll('.cf')].map(b => (b as HTMLElement).dataset.path)).toEqual(['v8/b.ts']);
    expect(box.querySelector('#uncommitted-open')!.textContent).toBe('Uncommitted changes — this epic1 file');
    const t = box.querySelector<HTMLButtonElement>('#uncommitted-all')!;
    expect(t.textContent).toBe('show all seats (3 more)');
    t.click();
    expect(all).toBe(true);
    box.querySelector<HTMLButtonElement>('#uncommitted-open')!.click();
    expect(posts).toEqual([{ type: 'openUncommitted', scoped: true }]);
  });
  it('all seats: every row, the epic rows marked, an unscoped multi-diff, a way back', () => {
    const box = document.createElement('div');
    const posts: unknown[] = [];
    renderUncommitted(box, card, true, m => posts.push(m), () => {});
    expect(box.querySelectorAll('.cf').length).toBe(4);
    expect(box.querySelectorAll('li.touched').length).toBe(1);
    expect(box.querySelector('#uncommitted-all')!.textContent).toBe('only this epic (1)');
    box.querySelector<HTMLButtonElement>('#uncommitted-open')!.click();
    expect(posts).toEqual([{ type: 'openUncommitted' }]);
  });
  it('nothing this epic touched: says so, and the toggle still reaches the rest', () => {
    const box = document.createElement('div');
    renderUncommitted(box, uncommittedCard(work, { kind: 'epic', paths: new Set() }), false, () => {}, () => {});
    expect(box.textContent).toContain('No uncommitted file is one this epic touched.');
    expect(box.querySelector<HTMLButtonElement>('#uncommitted-open')!.disabled).toBe(true);
    expect(box.querySelector('#uncommitted-all')!.textContent).toBe('show all seats (4 more)');
  });
});
