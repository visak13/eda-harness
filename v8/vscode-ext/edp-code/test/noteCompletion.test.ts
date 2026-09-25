// C20 (owner m-5a9111ce12; architect m-be79dbaa17): the @ and # completion of VS Code's native comment boxes
// (the `comment`-scheme provider in vscode/quotes.ts builds its items from these rows).
import { describe, expect, it } from 'vitest';
import type { PersonRow } from '../src/core/chatProtocol';
import { mentionRows, noteToken, pathRows } from '../src/core/noteCompletion';

const person = (handle: string, role: string, rank: number): PersonRow => ({ id: handle, handle, type: role === 'human' ? 'human' : 'agent', role,
  seat_ticket: null, seat_title: null, seat_state: null, rank, detail: `${role} detail` });
const people = [person('owner', 'human', 2), person('architect.epic-52edacd059', 'architect', 1), person('qa.epic-1', 'qa', 3)];

describe('noteToken', () => {
  it('finds the @ or # the caret is completing, like the composer', () => {
    expect(noteToken('ask @arc', 8)).toEqual({ kind: '@', start: 4, query: 'arc' });
    expect(noteToken('@', 1)).toEqual({ kind: '@', start: 0, query: '' });
    expect(noteToken('see #v8/web', 11)).toEqual({ kind: '#', start: 4, query: 'v8/web' });
    expect(noteToken('mail a@b', 8)).toBeNull(); // an e-mail is not a mention
    expect(noteToken('C#', 2)).toBeNull(); // a # after a word is not a tag
    expect(noteToken('plain words', 5)).toBeNull();
  });
});

describe('mentionRows', () => {
  it('lists people by the composer rules (handle prefix or role), inserting @handle and a space', () => {
    expect(mentionRows(people, 'arch')).toEqual([{ label: '@architect.epic-52edacd059', insert: '@architect.epic-52edacd059 ', detail: 'architect detail', kind: 'person' }]);
    expect(mentionRows(people, 'qa').map(r => r.label)).toEqual(['@qa.epic-1']);
    expect(mentionRows(people, '').map(r => r.label)).toEqual(['@architect.epic-52edacd059', '@owner', '@qa.epic-1']);
    expect(mentionRows(people, 'zzz')).toEqual([]);
  });
});

describe('pathRows', () => {
  it('a file inserts its token; a folder inserts its token or lists inside it', () => {
    expect(pathRows([{ path: 'v8/web', kind: 'folder' }, { path: 'v8/README.md', kind: 'file' }])).toEqual([
      { label: 'v8/web/', insert: '`v8/web/` ', detail: 'folder', kind: 'folder' },
      { label: 'v8/web/…', insert: '#v8/web/', detail: 'list inside this folder', kind: 'descend' },
      { label: 'v8/README.md', insert: '`v8/README.md` ', detail: 'file', kind: 'file' },
    ]);
  });
});
