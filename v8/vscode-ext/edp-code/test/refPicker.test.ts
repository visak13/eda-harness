// @vitest-environment jsdom
// C24 (s-5d1b171d57): the $ picker in the chat webview (composer + quote note boxes), the $<id> chips, the host's rows
// (RefSource: the open epic's tree first, then the board's open items), the inbound gates and the comment-box completion.
import { beforeEach, describe, expect, it } from 'vitest';
import { bodyFragment, refFragment } from '../webview/render';
import { onRefClick, RefPicker } from '../webview/refPicker';
import { NoteCompletion } from '../webview/noteComplete';
import { parseInbound } from '../src/core/chatProtocol';
import { parseReaderInbound } from '../src/core/reader';
import { noteToken, refRows } from '../src/core/noteCompletion';
import { RefSource, type RefBoard } from '../src/core/refSource';
import type { RefRow } from '../src/core/boardRefs';

Element.prototype.scrollIntoView ??= function () {}; // jsdom has no layout
type Sent = { type: string; [k: string]: unknown };

const EPIC = 'epic-52edacd059';
const rows: RefRow[] = [
  { id: 's-5d1b171d57', kind: 'story', title: 'C24 $-references', group: 'scope' },
  { id: 'design-10b21760d9', kind: 'design', title: 'EDP chat design', group: 'scope' },
  { id: 'dec-bf6aab8b73', kind: 'decision', title: 'C3 no longer waits', group: 'scope' },
  { id: 'epic-91fcd3b370', kind: 'epic', title: 'Code tab', group: 'board' },
];

function field(value: string): HTMLTextAreaElement {
  const ta = document.createElement('textarea');
  document.body.append(ta);
  ta.value = value;
  ta.setSelectionRange(value.length, value.length);
  return ta;
}
const key = (k: string) => new KeyboardEvent('keydown', { key: k, cancelable: true });

describe('RefPicker (the composer)', () => {
  let sent: Sent[];
  let status: HTMLElement;
  beforeEach(() => { sent = []; status = document.createElement('div'); document.body.replaceChildren(); });

  it("'$C2' asks the host; its rows open the list; arrows move; Enter inserts '$<id> (<title>) '", () => {
    const ta = field('see $C2');
    let accepted = 0;
    const p = new RefPicker(ta, m => sent.push(m), status, () => accepted++);
    p.update();
    expect(sent).toEqual([{ type: 'findRefs', q: 'C2', seq: expect.any(Number) }]);
    const seq = sent[0].seq as number;
    p.onRefs({ type: 'refs', v: 1, seq: seq - 1, items: rows }); // a stale answer is dropped
    expect(p.isOpen).toBe(false);
    p.onRefs({ type: 'refs', v: 1, seq, items: rows });
    expect(p.isOpen).toBe(true);
    const opts = [...p.list.querySelectorAll('[role=option]')];
    expect(opts.map(o => (o as HTMLElement).dataset.ref)).toEqual(rows.map(r => r.id));
    expect(opts[0].textContent).toBe('story $s-5d1b171d57C24 $-references');
    expect(opts[3].classList.contains('other')).toBe(true);
    expect(ta.getAttribute('aria-activedescendant')).toBe('ref-0');
    expect(status.textContent).toBe('4 board objects');
    expect(p.onKey(key('ArrowDown'))).toBe(true);
    expect(ta.getAttribute('aria-activedescendant')).toBe('ref-1');
    expect(p.onKey(key('Enter'))).toBe(true);
    expect(ta.value).toBe('see $design-10b21760d9 (EDP chat design) ');
    expect(p.isOpen).toBe(false);
    expect(accepted).toBe(1);
    expect(p.onKey(key('Enter'))).toBe(false); // closed: Enter is the composer's again
  });

  it('Tab picks; Escape closes, keeps the text and stays closed on the same word', () => {
    const ta = field('$de');
    const p = new RefPicker(ta, m => sent.push(m), status, () => {});
    p.update();
    p.onRefs({ type: 'refs', v: 1, seq: sent[0].seq as number, items: rows });
    expect(p.onKey(key('Escape'))).toBe(true);
    expect(p.isOpen).toBe(false);
    expect(ta.value).toBe('$de');
    p.update();
    expect(sent).toHaveLength(1); // not asked again for the dismissed word
    ta.value = '$dec'; ta.setSelectionRange(4, 4);
    p.update();
    p.onRefs({ type: 'refs', v: 1, seq: sent[1].seq as number, items: rows.slice(2) });
    expect(p.onKey(key('Tab'))).toBe(true);
    expect(ta.value).toBe('$dec-bf6aab8b73 (C3 no longer waits) ');
  });

  it("'$5' and '$env:X' never ask; the host's malformed rows are dropped", () => {
    for (const v of ['costs $5', '$env:X', '$env:', 'a$b', '`$code`']) {
      const p = new RefPicker(field(v), m => sent.push(m), status, () => {});
      p.update();
      expect(p.isOpen).toBe(false);
    }
    expect(sent).toEqual([]);
    const p = new RefPicker(field('$x'), m => sent.push(m), status, () => {});
    p.update();
    p.onRefs({ type: 'refs', v: 1, seq: sent[0].seq as number, items: [{ id: 'm-0f44bb36dd', kind: 'story', title: 'x', group: 'scope' }] as never });
    expect(p.isOpen).toBe(false);
    expect(status.textContent).toBe('No matching board objects');
  });
});

describe('RefPicker second-opinion fixes (20260925T194748Z-c11490bb)', () => {
  beforeEach(() => { document.body.replaceChildren(); });

  it("the old query's rows are not pickable once the query moved: '$des' rows, then '$dec' + Enter before the answer", () => {
    const sent: Sent[] = [];
    const ta = field('$des');
    const p = new RefPicker(ta, m => sent.push(m), document.createElement('div'), () => {});
    p.update();
    p.onRefs({ type: 'refs', v: 1, seq: sent[0].seq as number, items: [rows[1]] });
    expect(p.isOpen).toBe(true);
    ta.value = '$dec'; ta.setSelectionRange(4, 4);
    p.update();
    expect(p.isOpen).toBe(false);
    expect(p.onKey(key('Enter'))).toBe(false);
    expect(ta.value).toBe('$dec');
    p.onRefs({ type: 'refs', v: 1, seq: sent[1].seq as number, items: [rows[2]] });
    expect(p.onKey(key('Enter'))).toBe(true);
    expect(ta.value).toBe('$dec-bf6aab8b73 (C3 no longer waits) ');
  });

  it("closing leaves the @ list's links alone: '$s @o' with the people list open keeps its aria state", () => {
    const ta = field('$s @o');
    ta.setAttribute('aria-controls', 'people');
    const sent: Sent[] = [];
    const p = new RefPicker(ta, m => sent.push(m), document.createElement('div'), () => {});
    ta.setSelectionRange(2, 2);
    p.update();
    p.onRefs({ type: 'refs', v: 1, seq: sent[0].seq as number, items: rows });
    expect(ta.getAttribute('aria-controls')).toBe('refs');
    // the caret moves after '@o': the people picker takes the field, then the $ picker closes
    ta.setSelectionRange(5, 5);
    ta.setAttribute('aria-controls', 'people');
    ta.setAttribute('aria-activedescendant', 'p-0');
    p.update();
    expect(p.isOpen).toBe(false);
    expect(ta.getAttribute('aria-controls')).toBe('people');
    expect(ta.getAttribute('aria-activedescendant')).toBe('p-0');
    // closed while it owned them: aria-controls goes back to the people list
    ta.setSelectionRange(2, 2);
    p.update();
    p.onRefs({ type: 'refs', v: 1, seq: sent[1].seq as number, items: rows });
    p.onKey(key('Escape'));
    expect(ta.getAttribute('aria-controls')).toBe('people');
    expect(ta.hasAttribute('aria-activedescendant')).toBe(false);
  });
});

describe('NoteCompletion (quote note boxes) has the $ list', () => {
  it('a note box asks, shows and picks with the same keys; the box never sees a picked Enter', () => {
    document.body.replaceChildren();
    const sent: Sent[] = [];
    const status = document.createElement('div');
    const nc = new NoteCompletion(() => [], m => sent.push(m as Sent), status, 'qn');
    const host = document.createElement('div');
    const note = document.createElement('textarea');
    host.append(note);
    document.body.append(host);
    nc.attach(note, host);
    let boxEnter = 0;
    note.addEventListener('keydown', e => { if (e.key === 'Enter') boxEnter++; });
    note.value = 'per $C3'; note.setSelectionRange(7, 7);
    note.dispatchEvent(new Event('input'));
    const ask = sent.find(m => m.type === 'findRefs')!;
    expect(ask.q).toBe('C3');
    nc.onRefs({ type: 'refs', v: 1, seq: ask.seq as number, items: rows.slice(2, 3) });
    expect(host.querySelector('#qn-refs')?.hasAttribute('hidden')).toBe(false);
    note.dispatchEvent(key('Enter'));
    expect(note.value).toBe('per $dec-bf6aab8b73 (C3 no longer waits) ');
    expect(boxEnter).toBe(0);
  });
});

describe('$<id> chips', () => {
  it('a message body renders chips outside code, beside @mentions', () => {
    const d = document.createElement('div');
    d.append(bodyFragment(document, 'ask @owner about $s-5d1b171d57 (C24 refs) and $dec-bf6aab8b73; `$epic-52edacd059` costs $5', new Set(['owner'])));
    const chips = [...d.querySelectorAll<HTMLButtonElement>('button.ref-chip')];
    expect(chips.map(c => [c.dataset.ref, c.dataset.kind, c.textContent])).toEqual([
      ['s-5d1b171d57', 'story', 'story · C24 refs'], ['dec-bf6aab8b73', 'decision', '$dec-bf6aab8b73']]);
    expect(d.querySelector('.mention.known')?.textContent).toBe('@owner');
    expect(d.querySelector('code')?.textContent).toBe('$epic-52edacd059');
  });

  it("a quote's note renders chips; a click posts openRef", () => {
    const root = document.createElement('div');
    root.append(refFragment(document, 'see $design-10b21760d9 (EDP chat design) first'));
    const sent: Sent[] = [];
    onRefClick(root, m => sent.push(m));
    root.querySelector<HTMLButtonElement>('.ref-chip')!.click();
    expect(sent).toEqual([{ type: 'openRef', id: 'design-10b21760d9' }]);
    expect(root.textContent).toBe('see design · EDP chat design first');
  });
});

describe('inbound gates', () => {
  it('findRefs: a word after $ and a seq; openRef: a referenceable id', () => {
    expect(parseInbound({ v: 1, type: 'findRefs', q: 'C2', seq: 4 })).toEqual({ v: 1, type: 'findRefs', q: 'C2', seq: 4 });
    for (const q of ['', '5x', 'env:X', 'a b', 'x'.repeat(200)]) expect(parseInbound({ v: 1, type: 'findRefs', q, seq: 1 })).toBeNull();
    expect(parseInbound({ v: 1, type: 'findRefs', q: 'C2', seq: -1 })).toBeNull();
    expect(parseInbound({ v: 1, type: 'openRef', id: 'dec-bf6aab8b73' })).toEqual({ v: 1, type: 'openRef', id: 'dec-bf6aab8b73' });
    for (const id of ['m-0f44bb36dd', 'note-23c452b368', '../x', 's-5d1b171d57x']) expect(parseInbound({ v: 1, type: 'openRef', id })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'findRefs', q: 'des', seq: 2 })).toEqual({ v: 1, type: 'findRefs', q: 'des', seq: 2 });
    expect(parseReaderInbound({ v: 1, type: 'openRef', id: 'epic-52edacd059' })).toEqual({ v: 1, type: 'openRef', id: 'epic-52edacd059' });
    expect(parseReaderInbound({ v: 1, type: 'openRef', id: 'art-123' })).toBeNull();
  });
});

describe('comment boxes (native Comments API) complete $ too', () => {
  it('noteToken finds $, rows insert the token', () => {
    expect(noteToken('see $C2', 7)).toEqual({ kind: '$', start: 4, query: 'C2' });
    expect(noteToken('costs $5', 8)).toBeNull();
    expect(noteToken('$env:X', 6)).toBeNull();
    expect(refRows(rows.slice(0, 1))).toEqual([{ label: '$s-5d1b171d57', insert: '$s-5d1b171d57 (C24 $-references) ', detail: 'story · C24 $-references', kind: 'ref' }]);
    expect(refRows(rows.slice(3))[0].detail).toBe('epic · Code tab (other work)');
  });
});

describe('RefSource (the host rows)', () => {
  function fake(over: Partial<RefBoard> = {}) {
    const calls: string[] = [];
    const b: RefBoard = {
      ticket: async id => { calls.push(`ticket ${id}`); return { id, kind: 'epic', title: 'EDP chat in VS Code', status: 'in_progress', assignee: null }; },
      tickets: async q => { calls.push(`tickets ${JSON.stringify(q)}`); return [
        { id: 's-5d1b171d57', kind: 'story', title: 'C24 $-references', status: 'in_progress', assignee: null },
        { id: 's-93ddb7fd1a', kind: 'story', title: 'C23 notes', status: 'in_review', assignee: null }]; },
      docsOf: async s => { calls.push(`docs ${s}`); return [{ id: 'design-10b21760d9', title: 'EDP chat design', doc_type: 'design' }, { id: 'note-23c452b368', title: 'C24 plan', doc_type: 'note' }]; },
      scopeDecisions: async s => { calls.push(`decisions ${s}`); return { scope: s, epic: s, decisions: [{ id: 'dec-bf6aab8b73', text: 'C2 ruling', status: 'live' }] } as never; },
      find: async q => { calls.push(`find ${q}`); return [{ type: 'ticket', id: 's-0000000001', title: 'C2 elsewhere', status: 'ready' }, { type: 'ticket', id: 's-5d1b171d57', title: 'dup', status: 'ready' }]; },
      epics: async () => { calls.push('epics'); return [{ id: 'epic-91fcd3b370', title: 'Code tab C2', status: 'in_progress' }]; },
      ...over,
    };
    return { b, calls };
  }

  it('ranks the open epic tree first, then the board; reads the scope once a minute', async () => {
    let now = 0;
    const { b, calls } = fake();
    const src = new RefSource(() => b, () => now);
    const out = await src.rows(EPIC, 'C2');
    expect(out.map(r => [r.id, r.group])).toEqual([['s-5d1b171d57', 'scope'], ['s-93ddb7fd1a', 'scope'], ['dec-bf6aab8b73', 'scope'],
      ['s-0000000001', 'board'], ['epic-91fcd3b370', 'board']]);
    expect(calls).toContain(`tickets {"epic_id":"${EPIC}"}`);
    const n = calls.filter(c => c.startsWith('tickets')).length;
    await src.rows(EPIC, 'C24');
    expect(calls.filter(c => c.startsWith('tickets')).length).toBe(n); // cached
    now = 61_000;
    await src.rows(EPIC, 'C24');
    expect(calls.filter(c => c.startsWith('tickets')).length).toBe(n + 1);
  });

  it('a one-letter query does not search; no epic means board rows only; a refused read is an empty list', async () => {
    const { b, calls } = fake({ scopeDecisions: async () => { throw new Error('403 forbidden'); }, find: async () => { throw new Error('down'); } });
    const src = new RefSource(() => b);
    await src.rows(EPIC, 'C');
    expect(calls.some(c => c.startsWith('find'))).toBe(false);
    const out = await src.rows(EPIC, 'C2');
    expect(out.map(r => r.id)).toEqual(['s-5d1b171d57', 's-93ddb7fd1a', 'epic-91fcd3b370']);
    expect((await src.rows(null, 'Code')).map(r => r.id)).toEqual(['epic-91fcd3b370']);
  });
});
