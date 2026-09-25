// @vitest-environment jsdom
// C13 tabbed webview (s-f4e767cfd1): one tab registry, the ARIA tab bar, the Changes and Commits views,
// the badges, the seen marker, and the host's scope set (a story, or an epic with every ticket of it).
import { describe, expect, it } from 'vitest';
import type { ChatState, CommitCard, UncommittedCard } from '../src/core/chatProtocol';
import { inScope, type Indexed } from '../src/core/commits';
import { uncommittedCard, type WorkFile } from '../src/core/uncommitted';
import { FOLDED, markSeen, restoreLocal, SEEN_MAX, unseenCommits, type ViewLocal } from '../src/core/viewState';
import { TABS } from '../webview/registry';
import { TabBar, type TabCtx } from '../webview/tabs';
import { changesBadge, renderChanges } from '../webview/views/changes';
import { commitsTab, renderCommits } from '../webview/views/commits';

const EPIC = 'epic-0123456789', STORY = 's-0123456789', OTHER = 's-abcdefabcd';
const card = (k: string, at: string, o: Partial<CommitCard> = {}): CommitCard => ({
  type: 'commit', sha: k.repeat(40).slice(0, 40), at, subject: `subject ${k}`, tickets: [STORY], attribution: 'trailer',
  seat: 'engineer.x', seatVia: 'trailer', local: true, more: 0, files: [{ path: 'v8/a.ts', status: 'M', add: 1, del: 0 }], ...o,
});
const work: WorkFile[] = [
  { path: 'v8/a.ts', status: 'M' }, { path: 'v8/b.ts', status: 'M' }, { path: 'v8/c.ts', status: 'A' }, { path: 'v8/d.ts', status: 'U' },
];
function state(o: Partial<ChatState> = {}): ChatState {
  return {
    type: 'state', v: 1, me: null, ticket: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' }, epic: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' },
    stories: [{ id: STORY, kind: 'story', title: 'C13 tabs', status: 'in_progress', unread: 0 }], commits: [], unlinked: [], uncommitted: null,
    architect: null, people: [], items: [], hasOlder: false, chip: null, feed: 'live', notice: null, ...o,
  };
}
function ctx(s: ChatState, local: ViewLocal = restoreLocal(undefined)) {
  const posts: unknown[] = [];
  const c: TabCtx = { state: s, local, post: m => posts.push(m), persist: () => {}, select: () => {}, chatUnread: 0 };
  return { c, posts };
}
const click = (root: ParentNode, sel: string) => root.querySelector<HTMLButtonElement>(sel)!.click();

describe('the registry', () => {
  it('Chat | Changes | Commits | Inbox (C15), unique ids, Chat first (the default)', () => {
    expect(TABS.map(t => t.id)).toEqual(['chat', 'changes', 'commits', 'inbox']);
    expect(TABS.map(t => t.label)).toEqual(['Chat', 'Changes', 'Commits', 'Inbox']);
  });
  it('adding a tab is one entry: the bar builds its button and panel from the entry alone', () => {
    const extra = { id: 'docs', label: 'Docs', badge: () => ({ text: '2', aria: '2 docs' }), render: (p: HTMLElement) => { p.textContent = 'docs'; } };
    const bar = new TabBar([...TABS, extra], 'docs', () => {});
    expect([...bar.bar.querySelectorAll('[role=tab]')].map(b => b.id)).toEqual(['tab-chat', 'tab-changes', 'tab-commits', 'tab-inbox', 'tab-docs']);
    expect(bar.current).toBe('docs');
    expect(bar.panelOf('docs').hidden).toBe(false);
    expect(bar.panelOf('chat').hidden).toBe(true);
  });
});

describe('the tab bar (ARIA tabs, jsdom)', () => {
  it('roles, selection, roving tabindex; an unknown saved tab falls back to the first', () => {
    const bar = new TabBar(TABS, 'nope', () => {});
    expect(bar.current).toBe('chat');
    expect(bar.bar.getAttribute('role')).toBe('tablist');
    const tabs = [...bar.bar.querySelectorAll<HTMLButtonElement>('[role=tab]')];
    expect(tabs.map(t => [t.getAttribute('aria-selected'), t.tabIndex])).toEqual([['true', 0], ['false', -1], ['false', -1], ['false', -1]]);
    expect(bar.panelOf('changes').getAttribute('role')).toBe('tabpanel');
    expect(bar.panelOf('changes').getAttribute('aria-labelledby')).toBe('tab-changes');
    bar.show('commits');
    expect(tabs.map(t => t.getAttribute('aria-selected'))).toEqual(['false', 'false', 'true', 'false']);
    expect([bar.panelOf('chat').hidden, bar.panelOf('changes').hidden, bar.panelOf('commits').hidden]).toEqual([true, true, false]);
  });
  it('click and Arrow/Home/End select through the callback', () => {
    const picked: string[] = [];
    const bar = new TabBar(TABS, 'chat', id => { picked.push(id); bar.show(id); });
    document.body.append(bar.bar);
    click(bar.bar, '#tab-changes');
    const key = (k: string) => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
    bar.bar.querySelector<HTMLButtonElement>('#tab-changes')!.focus();
    key('ArrowRight'); key('ArrowRight'); key('ArrowLeft'); key('Home'); key('End');
    expect(picked).toEqual(['changes', 'commits', 'inbox', 'commits', 'chat', 'inbox']);
    bar.bar.remove();
  });
  it('badges: text hidden from the reader, the count spoken in the tab name', () => {
    const bar = new TabBar(TABS, 'chat', () => {});
    const s = state({ uncommitted: uncommittedCard(work, { kind: 'epic', paths: new Set(['v8/b.ts']) }), commits: [card('a', '2026-09-25T08:00:00Z')] });
    const { c } = ctx(s);
    c.chatUnread = 3;
    bar.badges(c);
    const t = (id: string) => bar.bar.querySelector<HTMLButtonElement>(`#tab-${id}`)!;
    expect(t('chat').getAttribute('aria-label')).toBe('Chat, 3 new messages');
    expect(t('changes').getAttribute('aria-label')).toBe('Changes, 1 file this epic touched, 4 files uncommitted across all seats');
    expect(t('commits').getAttribute('aria-label')).toBe('Commits, 1 new commit'); // nothing seen yet at this scope
    expect(t('changes').querySelector('.tab-badge')!.textContent).toBe('1');
    expect(t('changes').querySelector('.tab-badge')!.getAttribute('aria-hidden')).toBe('true');
    c.chatUnread = 0;
    bar.badges(c);
    expect(t('chat').querySelector('.tab-badge')).toBeNull();
  });
});

describe('the Changes tab (jsdom)', () => {
  const scoped: UncommittedCard = uncommittedCard(work, { kind: 'epic', paths: new Set(['v8/b.ts']) });
  it('badge: the scope count, every file without a scope, none when clean', () => {
    expect(changesBadge(scoped)!.text).toBe('1');
    expect(changesBadge(uncommittedCard(work))!.text).toBe('4');
    expect(changesBadge(null)).toBeNull();
  });
  it("the scope's files first and open; the other seats folded as 'All seats · 3 more'", () => {
    const panel = document.createElement('section');
    const { c } = ctx(state({ uncommitted: scoped }));
    renderChanges(panel, c);
    expect(panel.querySelector('#changes-summary')!.textContent).toBe('4 files uncommitted in the shared tree');
    expect(panel.querySelector('#changes-scoped-toggle')!.getAttribute('aria-expanded')).toBe('true');
    expect([...panel.querySelectorAll('#changes-scoped .cf')].map(b => (b as HTMLElement).dataset.path)).toEqual(['v8/b.ts']);
    expect(panel.querySelector('#changes-all-toggle')!.textContent).toBe('▸All seats3 more');
    expect(panel.querySelector('#changes-all-toggle')!.getAttribute('aria-expanded')).toBe('false');
    expect(panel.querySelectorAll('#changes-all .cf').length).toBe(0);
  });
  it('every group header expands and collapses by click, and the fold is kept in the viewer state', () => {
    const panel = document.createElement('section');
    const local = restoreLocal(undefined);
    const { c } = ctx(state({ uncommitted: scoped }), local);
    renderChanges(panel, c);
    click(panel, '#changes-all-toggle');
    expect(local.fold.allSeats).toBe(true);
    expect([...panel.querySelectorAll('#changes-all .cf')].map(b => (b as HTMLElement).dataset.path)).toEqual(['v8/a.ts', 'v8/c.ts', 'v8/d.ts']);
    click(panel, '#changes-scoped-toggle');
    expect(local.fold.scoped).toBe(false);
    expect(panel.querySelectorAll('#changes-scoped .cf').length).toBe(0);
    click(panel, '#changes-all-toggle');
    expect(panel.querySelectorAll('#changes-all .cf').length).toBe(0);
    expect(local.fold).toEqual({ scoped: false, allSeats: false, unlinked: false });
  });
  it('a file opens its diff; Open all the multi-diff; Open the scope multi-diff', () => {
    const panel = document.createElement('section');
    const { c, posts } = ctx(state({ uncommitted: scoped }));
    renderChanges(panel, c);
    click(panel, '#changes-scoped .cf');
    click(panel, '#changes-open-all');
    click(panel, '#changes-open-scoped');
    expect(posts).toEqual([{ type: 'openUncommitted', path: 'v8/b.ts' }, { type: 'openUncommitted' }, { type: 'openUncommitted', scoped: true }]);
  });
  it('clean: says so and Open all is disabled; nothing this scope touched: says so', () => {
    const panel = document.createElement('section');
    renderChanges(panel, ctx(state()).c);
    expect(panel.textContent).toContain('The shared tree is clean');
    expect(panel.querySelector<HTMLButtonElement>('#changes-open-all')!.disabled).toBe(true);
    renderChanges(panel, ctx(state({ uncommitted: uncommittedCard(work, { kind: 'epic', paths: new Set() }) })).c);
    expect(panel.textContent).toContain('No uncommitted file is one this epic touched.');
    expect(panel.querySelector('#changes-all-toggle')!.textContent).toBe('▸All seats4 more');
  });
});

describe('the Commits tab (jsdom)', () => {
  const commits = [card('b', '2026-09-25T10:00:00Z', { thread: false, story: STORY }), card('a', '2026-09-25T08:00:00Z', { thread: true, story: null, tickets: [EPIC] })];
  const unlinked = [card('f', '2026-09-25T07:00:00Z', { attribution: 'none', seat: null, seatVia: null, tickets: [] })];
  it('epic scope: newest first, labelled by story (or epic), folded cards; Unlinked collapsed at the bottom', () => {
    const panel = document.createElement('section');
    renderCommits(panel, ctx(state({ commits, unlinked })).c);
    expect([...panel.querySelectorAll('.cm-list > .commit')].map(e => (e as HTMLElement).dataset.sha!.slice(0, 1))).toEqual(['b', 'a']);
    expect([...panel.querySelectorAll('.cm-story')].map(e => e.textContent)).toEqual(['C13 tabs', 'epic']);
    expect(panel.querySelectorAll('.cf').length).toBe(0);
    expect(panel.lastElementChild!.id).toBe('commits-unlinked');
    expect(panel.querySelector('#commits-unlinked-toggle')!.getAttribute('aria-expanded')).toBe('false');
  });
  it('a card head click expands its files and a second folds them; the Unlinked header toggles', () => {
    const panel = document.createElement('section');
    const local = restoreLocal(undefined);
    const { c, posts } = ctx(state({ commits, unlinked }), local);
    renderCommits(panel, c);
    click(panel, '.commit[data-sha^="b"] .cm-head');
    expect(panel.querySelector('.commit[data-sha^="b"] .cm-head')!.getAttribute('aria-expanded')).toBe('true');
    click(panel, '.commit[data-sha^="b"] .cf');
    click(panel, '.commit[data-sha^="b"] .cm-open');
    expect(posts).toEqual([{ type: 'openDiff', sha: 'b'.repeat(40), path: 'v8/a.ts' }, { type: 'openDiff', sha: 'b'.repeat(40) }]);
    click(panel, '.commit[data-sha^="b"] .cm-head');
    expect(panel.querySelectorAll('.commit[data-sha^="b"] .cf').length).toBe(0);
    click(panel, '#commits-unlinked-toggle');
    expect(local.fold.unlinked).toBe(true);
    expect(panel.querySelector('#commits-unlinked .commit .cm-seat')!.textContent).toBe('unlinked');
  });
  it('a Chat marker jump (focusSha) opens that card expanded, even inside the folded Unlinked group', () => {
    const panel = document.createElement('section');
    document.body.append(panel);
    const { c } = ctx(state({ commits, unlinked }));
    c.focusSha = 'f'.repeat(40);
    renderCommits(panel, c);
    expect(panel.querySelector('#commits-unlinked-toggle')!.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(panel.querySelector('.commit[data-sha^="f"] .cm-head'));
    expect(c.focusSha).toBeUndefined();
    panel.remove();
  });
  it('story scope: no labels, no Unlinked group', () => {
    const panel = document.createElement('section');
    renderCommits(panel, ctx(state({ ticket: { id: STORY, kind: 'story', title: 'S', status: 'x' }, commits: [commits[0]] })).c);
    expect(panel.querySelector('.cm-story')).toBeNull();
    expect(panel.querySelector('#commits-unlinked')).toBeNull();
    expect(panel.querySelector('#commits-summary')!.textContent).toBe('1 commit name this story');
  });
  it('the badge counts commits newer than this scope last saw; rendering the tab marks them seen', () => {
    const local = restoreLocal(undefined);
    local.seen[EPIC] = '2026-09-25T09:00:00Z';
    const { c } = ctx(state({ commits }), local);
    expect(commitsTab.badge(c)).toEqual({ text: '1', aria: '1 new commit' });
    renderCommits(document.createElement('section'), c);
    expect(local.seen[EPIC]).toBe('2026-09-25T10:00:00Z');
    expect(commitsTab.badge(c)).toBeNull();
  });
});

describe('seen markers (pure)', () => {
  it('unseenCommits: newer than the marker; no marker = all', () => {
    const cs = [{ at: '2026-09-25T10:00:00Z' }, { at: '2026-09-25T08:00:00Z' }];
    expect(unseenCommits(cs, '2026-09-25T09:00:00Z')).toBe(1);
    expect(unseenCommits(cs, undefined)).toBe(2);
  });
  it('markSeen only moves forward, and keeps at most SEEN_MAX scopes', () => {
    const local = restoreLocal(undefined);
    expect(markSeen(local, EPIC, [{ at: '2026-09-25T10:00:00Z' }])).toBe(true);
    expect(markSeen(local, EPIC, [{ at: '2026-09-25T08:00:00Z' }])).toBe(false);
    expect(local.seen[EPIC]).toBe('2026-09-25T10:00:00Z');
    expect(markSeen(local, OTHER, [])).toBe(false);
    for (let i = 0; i < SEEN_MAX + 5; i++) markSeen(local, `s-${i.toString(16).padStart(10, '0')}`, [{ at: new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString() }]);
    expect(Object.keys(local.seen).length).toBe(SEEN_MAX);
    expect(local.fold).toEqual(FOLDED);
  });
});

describe('the host scope set (core inScope)', () => {
  const ix = (sha: string, tickets: string[]): Indexed => ({ sha: sha.repeat(40), tickets } as unknown as Indexed);
  const cs = [ix('1', [EPIC]), ix('2', [STORY]), ix('3', ['t-0000000001']), ix('4', []), ix('5', ['s-9999999999'])];
  it('epic scope: the epic and every ticket of it; `thread` marks only the epic-named ones (ruling m-2e3b14065e)', () => {
    const r = inScope(cs, new Set([EPIC]), new Set([EPIC, STORY, 't-0000000001']));
    expect(r.map(x => [x.c.sha[0], x.thread])).toEqual([['1', true], ['2', false], ['3', false]]);
  });
  it('story scope: the story and its tasks, all in the thread', () => {
    const ids = new Set([STORY, 't-0000000001']);
    expect(inScope(cs, ids, ids).map(x => [x.c.sha[0], x.thread])).toEqual([['2', true], ['3', true]]);
  });
});
