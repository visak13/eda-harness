// @vitest-environment jsdom
// C5 change cards: the inbound gate for diff intents, card building (seat labels), the uncommitted
// merge, and the view's placement by time (jsdom).
import { describe, expect, it } from 'vitest';
import { isRepoPath, parseInbound, type ChatState, type CommitCard } from '../src/core/chatProtocol';
import { cardOf, CARD_FILES, type Indexed } from '../src/core/commits';
import { S, sameRows, uncommittedCard, workFiles } from '../src/core/uncommitted';
import { commitCardEl, insertByTime, markerEl, placeMarkers, renderMarkers, seatLabel } from '../webview/cards';

const SHA = 'a'.repeat(40);

describe('parseInbound: openDiff / openUncommitted', () => {
  it('a card and a file row', () => {
    expect(parseInbound({ v: 1, type: 'openDiff', sha: SHA })).toEqual({ v: 1, type: 'openDiff', sha: SHA });
    expect(parseInbound({ v: 1, type: 'openDiff', sha: SHA, path: 'v8/a b.ts' })).toEqual({ v: 1, type: 'openDiff', sha: SHA, path: 'v8/a b.ts' });
    expect(parseInbound({ v: 1, type: 'openUncommitted' })).toEqual({ v: 1, type: 'openUncommitted' });
    expect(parseInbound({ v: 1, type: 'openUncommitted', path: 'x.md', extra: 'dropped' })).toEqual({ v: 1, type: 'openUncommitted', path: 'x.md' });
  });
  it('refuses bad shas and paths', () => {
    for (const bad of ['HEAD', 'a'.repeat(39), 'A'.repeat(40), `${SHA} --output=x`, '--all']) expect(parseInbound({ v: 1, type: 'openDiff', sha: bad })).toBeNull();
    for (const p of ['../x', 'v8/../../etc', '/etc/passwd', 'C:/x', 'a\\b', 'a\0b', '', 7]) {
      expect(parseInbound({ v: 1, type: 'openDiff', sha: SHA, path: p })).toBeNull();
      expect(parseInbound({ v: 1, type: 'openUncommitted', path: p })).toBeNull();
    }
    expect(parseInbound({ type: 'openDiff', sha: SHA })).toBeNull();
  });
  it('isRepoPath', () => {
    expect(isRepoPath('v8/.claude/commands/qa.md')).toBe(true);
    expect(isRepoPath('a..b/c')).toBe(true);
    expect(isRepoPath('x'.repeat(5000))).toBe(false);
  });
});

const ix = (o: Partial<Indexed>): Indexed => ({
  sha: SHA, parents: [], at: Date.parse('2026-09-25T07:00:00Z'), subject: 'x', trailerTickets: [], trailerSeats: [],
  files: [], tickets: [], attribution: 'none', trailerSeat: null, ...o,
});

describe('cardOf', () => {
  const assignee = (t: string) => (t === 's-0123456789' ? 'engineer.s-0123456789' : null);
  it('trailer seat wins', () => {
    const c = cardOf(ix({ attribution: 'trailer', tickets: ['s-0123456789'], trailerSeat: 'qa.x' }), assignee);
    expect([c.seat, c.seatVia]).toEqual(['qa.x', 'trailer']);
  });
  it('a trailer without EDP-Seat falls back to the assignee, labelled', () => {
    const c = cardOf(ix({ attribution: 'trailer', tickets: ['s-0123456789'] }), assignee);
    expect([c.seat, c.seatVia, seatLabel(c)]).toEqual(['engineer.s-0123456789', 'assignee', 'engineer.s-0123456789 (assignee)']);
  });
  it('subject attribution -> the assignee, labelled; no assignee -> no seat', () => {
    expect(seatLabel(cardOf(ix({ attribution: 'subject', tickets: ['s-0123456789'] }), assignee))).toBe('engineer.s-0123456789 (assignee)');
    expect(seatLabel(cardOf(ix({ attribution: 'subject', tickets: ['s-9999999999'] }), assignee))).toBe('no seat');
  });
  it('a subject id with an EDP-Seat trailer shows that seat', () => {
    const c = cardOf(ix({ attribution: 'subject', tickets: ['s-9999999999'], trailerSeat: 'engineer.x' }), assignee);
    expect([c.seat, c.seatVia]).toEqual(['engineer.x', 'trailer']);
  });
  it("the fallback is the FIRST ticket's assignee, never a later ticket's", () =>
    expect(seatLabel(cardOf(ix({ attribution: 'subject', tickets: ['s-9999999999', 's-0123456789'] }), assignee))).toBe('no seat'));
  it('none names no seat', () => expect(seatLabel(cardOf(ix({}), assignee))).toBe('unlinked'));
  it('lists at most CARD_FILES files and counts the rest; time is ISO', () => {
    const files = Array.from({ length: CARD_FILES + 7 }, (_, i) => ({ path: `f${i}`, status: 'M' as const, add: 1, del: 0 }));
    const c = cardOf(ix({ files }), assignee);
    expect([c.files.length, c.more, c.at]).toEqual([CARD_FILES, 7, '2026-09-25T07:00:00.000Z']);
  });
});

describe('workFiles (uncommitted vs HEAD)', () => {
  it('merges index, working tree and untracked into one row per path', () => {
    const rows = workFiles(
      [{ path: 'v8/a.ts', status: S.INDEX_MODIFIED }, { path: 'v8/new.ts', status: S.INDEX_ADDED }, { path: 'v8/n2.ts', oldPath: 'v8/o2.ts', status: S.INDEX_RENAMED }],
      [{ path: 'v8/a.ts', status: S.MODIFIED }, { path: 'v8/gone.ts', status: S.DELETED }, { path: 'v8/mixed.txt', status: S.UNTRACKED }],
      [{ path: 'v8/u.txt', status: S.UNTRACKED }]);
    expect(rows).toEqual([
      { path: 'v8/a.ts', status: 'M' }, { path: 'v8/gone.ts', status: 'D' }, { path: 'v8/mixed.txt', status: 'U' },
      { path: 'v8/n2.ts', oldPath: 'v8/o2.ts', status: 'R' }, { path: 'v8/new.ts', status: 'A' }, { path: 'v8/u.txt', status: 'U' },
    ]);
  });
  it('added in the index then deleted in the tree is nothing vs HEAD; ignored files never show', () =>
    expect(workFiles([{ path: 'x', status: S.INDEX_ADDED }], [{ path: 'x', status: S.DELETED }, { path: 'i', status: S.IGNORED }], [])).toEqual([]));
  it('renamed in the index then deleted in the tree: the old path is deleted vs HEAD', () =>
    expect(workFiles([{ path: 'new', oldPath: 'old', status: S.INDEX_RENAMED }], [{ path: 'new', status: S.DELETED }], [])).toEqual([{ path: 'old', status: 'D' }]));
  it('git rm --cached (still on disk) is the tracked file vs HEAD, not a deletion', () => {
    expect(workFiles([{ path: 'f', status: S.INDEX_DELETED }], [], [{ path: 'f', status: S.UNTRACKED }])).toEqual([{ path: 'f', status: 'M' }]);
    expect(workFiles([{ path: 'f', status: S.INDEX_DELETED }], [{ path: 'f', status: S.UNTRACKED }], [])).toEqual([{ path: 'f', status: 'M' }]);
  });
  it('the card carries no seat and caps its rows', () => {
    const files = Array.from({ length: 205 }, (_, i) => ({ path: `f${String(i).padStart(3, '0')}`, status: 'M' as const }));
    const card = uncommittedCard(files, null, new Date('2026-09-25T07:00:00Z'));
    expect(Object.keys(card).sort()).toEqual(['at', 'files', 'more', 'scope', 'scoped', 'total']);
    expect([card.scoped, card.scope]).toEqual([null, null]);
    expect([card.files.length, card.more, card.total]).toEqual([200, 5, 205]);
    expect(sameRows(card, uncommittedCard(files))).toBe(true);
    expect(sameRows(card, null)).toBe(false);
  });
});

// -- the view -----------------------------------------------------------------------------------------
const card = (sha: string, at: string, o: Partial<CommitCard> = {}): CommitCard => ({
  type: 'commit', sha: sha.repeat(40).slice(0, 40), at, subject: `subject ${sha}`, tickets: ['s-0123456789'], attribution: 'trailer',
  seat: 'engineer.s-0123456789', seatVia: 'trailer', local: true, more: 0,
  files: [{ path: 'v8/a.ts', status: 'M', add: 3, del: 1 }, { path: 'v8/b.png', status: 'A', add: null, del: null }], ...o,
});
function msg(id: string, at: string): HTMLElement {
  const a = document.createElement('article');
  a.className = 'msg';
  a.dataset.id = id;
  const h = document.createElement('header');
  h.className = 'mh';
  const t = document.createElement('time');
  t.className = 'at';
  t.dateTime = at;
  h.append(t);
  a.append(h);
  return a;
}
const order = (list: HTMLElement) => Array.from(list.children).map(n => (n as HTMLElement).dataset.id ?? (n as HTMLElement).dataset.sha!.slice(0, 1));

describe('commit cards (Commits tab) and markers (Chat) (jsdom)', () => {
  it('a card shows seat, subject, sha7; folded it lists no files; the head toggles, Open all posts the multi-diff', () => {
    const posted: unknown[] = [];
    const toggles: boolean[] = [];
    const el = commitCardEl(card('c', '2026-09-25T07:00:00Z'), m => posted.push(m), false, o => toggles.push(o));
    expect(el.querySelector('.cm-seat')!.textContent).toBe('engineer.s-0123456789');
    expect(el.querySelector('.cm-sha')!.textContent).toBe('ccccccc');
    expect(el.querySelector('.cm-subject')!.textContent).toBe('subject c');
    expect(el.querySelector('.cm-head')!.getAttribute('aria-expanded')).toBe('false');
    expect(el.querySelectorAll('.cf').length).toBe(0);
    (el.querySelector('.cm-head') as HTMLButtonElement).click();
    expect(toggles).toEqual([true]);
    (el.querySelector('.cm-open') as HTMLButtonElement).click();
    expect(posted).toEqual([{ type: 'openDiff', sha: 'c'.repeat(40) }]);
  });
  it('expanded: files with +/-; a file posts its diff', () => {
    const posted: unknown[] = [];
    const el = commitCardEl(card('c', '2026-09-25T07:00:00Z'), m => posted.push(m), true, () => {}, 'C13 tabs');
    expect(el.querySelector('.cm-head')!.getAttribute('aria-expanded')).toBe('true');
    expect(el.querySelector('.cm-story')!.textContent).toBe('C13 tabs');
    expect(Array.from(el.querySelectorAll('.cf')).map(b => b.textContent)).toEqual(['Mv8/a.ts+3−1', 'Av8/b.pngbinary']);
    (el.querySelectorAll('.cf')[0] as HTMLButtonElement).click();
    expect(posted).toEqual([{ type: 'openDiff', sha: 'c'.repeat(40), path: 'v8/a.ts' }]);
  });
  it('agent text is text: a subject with markup creates no element (card and marker)', () => {
    const c = card('d', '2026-09-25T07:00:00Z', { subject: '<img src=x onerror=alert(1)>' });
    const el = commitCardEl(c, () => {}, true, () => {});
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.cm-subject')!.textContent).toBe('<img src=x onerror=alert(1)>');
    const m = markerEl(c, () => {});
    expect(m.querySelector('img')).toBeNull();
    expect(m.querySelector('.cmark-subject')!.textContent).toBe('<img src=x onerror=alert(1)>');
  });
  it('a marker is one line (sha7 + subject) that jumps to its commit', () => {
    const jumps: string[] = [];
    const m = markerEl(card('e', '2026-09-25T07:00:00Z'), s => jumps.push(s));
    expect(m.textContent).toBe('⎇eeeeeeesubject e');
    m.click();
    expect(jumps).toEqual(['e'.repeat(40)]);
  });
  it("markers interleave with messages by time, only for the thread's own commits, and survive an older-page prepend", () => {
    const list = document.createElement('div');
    list.append(msg('m1', '2026-09-25T07:00:00Z'), msg('m3', '2026-09-25T09:00:00Z'));
    const commits = [card('b', '2026-09-25T10:00:00Z', { thread: true }), card('s', '2026-09-25T09:30:00Z', { thread: false }), card('a', '2026-09-25T08:00:00Z', { thread: true })];
    renderMarkers(commits, list, () => {});
    expect(order(list)).toEqual(['m1', 'a', 'm3', 'b']);
    insertByTime(list, markerEl(card('e', '2026-09-25T06:00:00Z'), () => {}));
    expect(order(list)).toEqual(['e', 'm1', 'a', 'm3', 'b']);
    list.prepend(msg('m0', '2026-09-25T05:00:00Z'));
    list.prepend(list.querySelector('[data-sha^="a"]')!); // out of place, as a prepend leaves it
    placeMarkers(list);
    expect(order(list)).toEqual(['m0', 'e', 'm1', 'a', 'm3', 'b']);
    expect(list.querySelectorAll('.commit').length).toBe(0); // full cards left the chat
  });
});
