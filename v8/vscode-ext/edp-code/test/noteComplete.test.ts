// @vitest-environment jsdom
// C20 (owner m-5a9111ce12): the quote note boxes in the webviews get the composer's @ and # pickers. A key a list
// takes (Enter, Escape) never reaches the box's own handler (Ctrl+Enter adds, Escape cancels).
import { describe, expect, it } from 'vitest';
import type { PersonRow } from '../src/core/chatProtocol';
import { parseReaderInbound } from '../src/core/reader';
import { NoteCompletion } from '../webview/noteComplete';

Element.prototype.scrollIntoView ??= function () {}; // jsdom has none

const rows: PersonRow[] = [{ id: 'architect.epic-1', handle: 'architect.epic-1', type: 'agent', role: 'architect', seat_ticket: 'epic-1',
  seat_title: 'E', seat_state: null, rank: 1, detail: 'architect · epic-1 · E' }];

function setup() {
  const host = document.createElement('div');
  const note = document.createElement('textarea');
  host.append(note);
  document.body.append(host);
  const asked: { type: string; q: string; seq: number }[] = [];
  const own: string[] = [];
  let changed = 0;
  const nc = new NoteCompletion(() => rows, m => asked.push(m), document.createElement('div'), 'qn');
  nc.attach(note, host, () => changed++);
  note.addEventListener('keydown', e => own.push(e.key)); // the box's own handler, added after attach
  const type = (v: string) => { note.focus(); note.value = v; note.setSelectionRange(v.length, v.length); note.dispatchEvent(new Event('input')); };
  const key = (k: string) => note.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
  return { host, note, nc, asked, own, type, key, changed: () => changed };
}

describe('NoteCompletion', () => {
  it('@ lists people in the box host; Enter picks and never reaches the box handler', () => {
    const t = setup();
    t.type('see @arch');
    const list = t.host.querySelector('#qn-people') as HTMLUListElement;
    expect(list.hidden).toBe(false);
    expect(list.querySelectorAll('li')[0].textContent).toContain('@architect.epic-1');
    t.key('Enter');
    expect(t.note.value).toBe('see @architect.epic-1 ');
    expect(t.own).toEqual([]);
    expect(t.changed()).toBe(1);
    expect(list.hidden).toBe(true);
    t.key('Enter'); // the list is closed: the box sees its keys again
    expect(t.own).toEqual(['Enter']);
  });

  it('# asks the host and inserts the path token from its answer; a stale seq is dropped', () => {
    const t = setup();
    t.type('look at #READ');
    expect(t.asked.at(-1)).toMatchObject({ type: 'findPaths', q: 'READ' });
    const seq = t.asked.at(-1)!.seq;
    t.nc.onPaths({ type: 'paths', v: 1, seq: seq - 1, items: [{ path: 'old.md', kind: 'file' }] });
    expect(t.nc.isOpen).toBe(false);
    t.nc.onPaths({ type: 'paths', v: 1, seq, items: [{ path: 'v8/README.md', kind: 'file' }] });
    expect(t.nc.isOpen).toBe(true);
    t.key('Enter');
    expect(t.note.value).toBe('look at `v8/README.md` ');
    expect(t.own).toEqual([]);
  });

  it('Escape closes the list without cancelling the box', () => {
    const t = setup();
    t.type('@');
    expect(t.nc.isOpen).toBe(true);
    t.key('Escape');
    expect(t.nc.isOpen).toBe(false);
    expect(t.own).toEqual([]);
  });

  it('the reader asks for paths through its own checked intent', () => {
    expect(parseReaderInbound({ v: 1, type: 'findPaths', q: 'v8/', seq: 3 })).toEqual({ v: 1, type: 'findPaths', q: 'v8/', seq: 3 });
    expect(parseReaderInbound({ v: 1, type: 'findPaths', q: 'a`b', seq: 3 })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'findPaths', q: 'a', seq: -1 })).toBeNull();
  });
});
