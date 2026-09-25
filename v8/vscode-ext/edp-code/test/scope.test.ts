// @vitest-environment jsdom
// C14 (s-8cc2cc80b3): the Changes tab follows the scope picker. One shared fixture, an epic with two
// stories (one with a task): a story's "This story" group holds only files its own tickets touched
// (commits naming it or its tasks, anchors on those threads); the epic's other files fall into the
// folded "All seats" group. The epic's group is the whole tree, as before.
import { describe, expect, it } from 'vitest';
import type { ChatState } from '../src/core/chatProtocol';
import { openScope, scopeTickets, uncommittedCard, type WorkFile } from '../src/core/uncommitted';
import { restoreLocal } from '../src/core/viewState';
import type { TabCtx } from '../webview/tabs';
import { changesBadge, renderChanges } from '../webview/views/changes';

const EPIC = 'epic-0123456789', S1 = 's-1111111111', S2 = 's-2222222222', T1 = 't-1111111111';
type T = { id: string; kind: string; parent_id: string | null };
const epic: T = { id: EPIC, kind: 'epic', parent_id: null };
const s1 = { id: S1, kind: 'story', parent_id: EPIC };
const s2 = { id: S2, kind: 'story', parent_id: EPIC };
const t1 = { id: T1, kind: 'task', parent_id: S1 };
/** the host's `this.tree`: every ticket of the epic (the change cards' set) */
const tree = [s2, t1, s1, epic];
const commits = [
  { tickets: [S1], files: [{ path: 'v8/s1.ts' }] },
  { tickets: [T1], files: [{ path: 'v8/t1.ts', oldPath: 'v8/t1-old.ts' }] },
  { tickets: [S2], files: [{ path: 'v8/s2.ts' }] },
  { tickets: [EPIC], files: [{ path: 'v8/epic.md' }] },
  { tickets: [], files: [{ path: 'v8/nobody.ts' }] },
];
const anchors = [
  { thread: S1, path: 'v8/s1-anchor.ts' }, { thread: T1, path: 'v8/t1-anchor.ts' },
  { thread: S2, path: 'v8/s2-anchor.ts' }, { thread: EPIC, path: 'v8/epic-anchor.ts' },
];
const work: WorkFile[] = ['epic-anchor.ts', 'epic.md', 'nobody.ts', 's1-anchor.ts', 's1.ts', 's2-anchor.ts', 's2.ts', 't1-anchor.ts', 't1.ts', 'x.ts']
  .map(p => ({ path: `v8/${p}`, status: 'M' as const }));
const S1_OWN = ['v8/s1-anchor.ts', 'v8/s1.ts', 'v8/t1-anchor.ts', 'v8/t1.ts'];
const EPIC_OWN = ['v8/epic-anchor.ts', 'v8/epic.md', 'v8/s1-anchor.ts', 'v8/s1.ts', 'v8/s2-anchor.ts', 'v8/s2.ts', 'v8/t1-anchor.ts', 'v8/t1.ts'];

describe('scopeTickets: the picked scope, never the whole tree for a story', () => {
  it('an epic owns every ticket of its tree', () =>
    expect([...scopeTickets(epic, tree)].sort()).toEqual([EPIC, S1, S2, T1].sort()));
  it('a story owns itself and its tasks only', () => {
    expect([...scopeTickets(s1, tree)].sort()).toEqual([S1, T1].sort());
    expect([...scopeTickets(s2, tree)]).toEqual([S2]);
  });
  it('a task (or any other ticket) owns itself', () => expect([...scopeTickets(t1, tree)]).toEqual([T1]));
});

describe('openScope: commits naming the scope + anchors on its threads only', () => {
  it('story: its own and its task\'s commits (rename source too) and anchors; never a sibling\'s or the epic\'s', () => {
    const sc = openScope(s1, tree, commits, anchors);
    expect(sc.kind).toBe('story');
    expect([...sc.paths].sort()).toEqual([...S1_OWN, 'v8/t1-old.ts'].sort());
  });
  it('epic: the whole tree, as before', () => {
    const sc = openScope(epic, tree, commits, anchors);
    expect(sc.kind).toBe('epic');
    expect([...sc.paths].sort()).toEqual([...EPIC_OWN, 'v8/t1-old.ts'].sort());
  });
  it('a lone ticket is a ticket scope', () => expect(openScope(t1, tree, commits, anchors).kind).toBe('ticket'));
});

function state(uncommitted: ChatState['uncommitted'], ticket: { id: string; kind: string }): ChatState {
  return {
    type: 'state', v: 1, me: null, ticket: { ...ticket, title: 'T', status: 'in_progress' }, epic: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' },
    stories: [], commits: [], unlinked: [], uncommitted, architect: null, people: [], items: [], hasOlder: false, chip: null, feed: 'live', notice: null,
  };
}
function render(t: T) {
  const card = uncommittedCard(work, openScope(t, tree, commits, anchors));
  const panel = document.createElement('section');
  const local = restoreLocal(undefined);
  const c: TabCtx = { state: state(card, t), local, post: () => {}, persist: () => {}, select: () => {}, chatUnread: 0 };
  renderChanges(panel, c);
  const rows = (sel: string) => [...panel.querySelectorAll(`${sel} .cf`)].map(b => (b as HTMLElement).dataset.path);
  return { card, panel, rows, open: () => { panel.querySelector<HTMLButtonElement>('#changes-all-toggle')!.click(); } };
}

describe('the Changes tab follows the picker: epic → story → epic (jsdom)', () => {
  it('each switch changes the first group\'s title, rows and badge; the rest sits in folded All seats', () => {
    const e = render(epic);
    expect(e.panel.querySelector('#changes-scoped-toggle')!.textContent).toBe(`▾This epic${EPIC_OWN.length} files`);
    expect(e.rows('#changes-scoped')).toEqual(EPIC_OWN);
    expect(changesBadge(e.card)).toEqual({ text: '8', aria: '8 files this epic touched, 10 files uncommitted across all seats' });
    expect(e.panel.querySelector('#changes-all-toggle')!.getAttribute('aria-expanded')).toBe('false');

    const s = render(s1);
    expect(s.panel.querySelector('#changes-scoped-toggle')!.textContent).toBe('▾This story4 files');
    expect(s.rows('#changes-scoped')).toEqual(S1_OWN);
    expect(changesBadge(s.card)).toEqual({ text: '4', aria: '4 files this story touched, 10 files uncommitted across all seats' });
    // the epic's other files count inside the folded All seats group
    expect(s.panel.querySelector('#changes-all-toggle')!.textContent).toBe('▸All seats6 more');
    expect(s.rows('#changes-all')).toEqual([]);
    s.open();
    expect(s.rows('#changes-all')).toEqual(['v8/epic-anchor.ts', 'v8/epic.md', 'v8/nobody.ts', 'v8/s2-anchor.ts', 'v8/s2.ts', 'v8/x.ts']);
    expect(s.panel.querySelector('#changes-all ul')!.getAttribute('aria-label')).toBe('Uncommitted files outside this story');

    const back = render(epic);
    expect(back.rows('#changes-scoped')).toEqual(EPIC_OWN);
    expect(changesBadge(back.card)!.text).toBe('8');
  });
});
