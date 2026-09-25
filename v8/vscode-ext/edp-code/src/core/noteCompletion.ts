// C20 (owner m-5a9111ce12 "quote doesnt allow mentions or hashtags"; architect m-be79dbaa17): @ and # completion in
// VS Code's native comment boxes (the inline "Comment for chat" box on code, markdown source and diffs), as the
// composer does it: @ lists the board people and live seats (the host's labelled rows, filterPeople), # lists
// workspace paths (the C11 index; a file or folder inserts its `path` token, a folder's second row lists inside it). The
// provider is registered for the `comment` document scheme (the GitHub PR extension's route). Pure: no vscode import.
import type { PathHit, PersonRow } from './chatProtocol';
import { activeMention } from './mentions';
import { activeHashTag, pathToken } from './paths';
import { filterPeople } from './people';
import { activeRef, kindLabel, refToken, type RefRow } from './boardRefs';

/** The @ or # token the caret is completing on this line: where it starts and what was typed after it. */
export type NoteToken = { kind: '@' | '#' | '$'; start: number; query: string };

export function noteToken(line: string, caret: number): NoteToken | null {
  const m = activeMention(line, caret);
  if (m) return { kind: '@', start: m.start, query: m.query };
  const h = activeHashTag(line, caret);
  if (h) return { kind: '#', start: h.start, query: h.query };
  const r = activeRef(line, caret); // C24: $ board objects
  return r ? { kind: '$', start: r.start, query: r.query } : null;
}

/** One completion row: what the list shows, what replaces the token, the detail line. `kind`: a person, a file, a
 *  folder's token, or `descend` (inside a folder: the provider opens the list again). */
export type NoteCompletionRow = { label: string; insert: string; detail: string; kind: 'person' | 'file' | 'folder' | 'descend' | 'ref' };

/** C24: a board object inserts `$<id> (<title>) `; the detail names its kind and title. */
export function refRows(rows: RefRow[]): NoteCompletionRow[] {
  return rows.map(r => ({ label: `$${r.id}`, insert: refToken(r), detail: `${kindLabel(r.kind)} · ${r.title}${r.group === 'board' ? ' (other work)' : ''}`, kind: 'ref' as const }));
}

export function mentionRows(people: PersonRow[], query: string): NoteCompletionRow[] {
  return filterPeople(people, query).map(p => ({ label: `@${p.handle}`, insert: `@${p.handle} `, detail: p.detail, kind: 'person' as const }));
}

/** A file inserts its token; a folder has two rows, as the composer's Enter and Tab: insert the folder's token, or
 *  go inside it (`#path/`, the list opens again on that level). */
export function pathRows(hits: PathHit[]): NoteCompletionRow[] {
  return hits.flatMap((h): NoteCompletionRow[] => h.kind === 'folder'
    ? [{ label: `${h.path}/`, insert: pathToken(h), detail: 'folder', kind: 'folder' },
      { label: `${h.path}/…`, insert: `#${h.path}/`, detail: 'list inside this folder', kind: 'descend' }]
    : [{ label: h.path, insert: pathToken(h), detail: 'file', kind: 'file' }]);
}
