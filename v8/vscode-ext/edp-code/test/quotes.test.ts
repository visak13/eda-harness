// C20 s-29f052c40e: the draft tray's core. The host builds every quote from what it read (a doc version's markdown,
// a message it holds, a code anchor); the view names drafts by key only; a send carries them in tray order; a 422
// `quotes[i]` marks that draft; workspaceState is untrusted on restore.
import { describe, expect, it } from 'vitest';
import type { Anchor } from '../src/core/anchor';
import { parseInbound } from '../src/core/chatProtocol';
import { parseReaderInbound } from '../src/core/reader';
import {
  chipOf, codeDraft, codePoints, docReaderDraft, docSourceDraft, messageDraft, PASSAGE_MAX_B, quotesForSend, QUOTES_MAX,
  refusedKey, restoreTray, Tray, type Draft,
} from '../src/core/quotes';
import { quoteSourceLabel } from '../src/core/quoteLabel';
import { quoteViews } from '../src/core/thread';

const DOC = 'design-10b21760d9', T = 's-29f052c40e', M = 'm-0123456789';
const BODY = ['# Title', '', '## 14.5 Quote + note', '', 'Every quote carries **its note** and a locator.', 'Second line of it.', '', '## 14.7 Tray', 'The tray keeps order.'].join('\n');
const anchor: Anchor = { repo_root: 'C:/r', path: 'src/a.ts', line_start: 3, line_end: 4, commit: 'abc1234', dirty: false, snippet: 'const a = 1;\nconst b = 2;', snippet_sha: 'f'.repeat(64) };

describe('builders', () => {
  it('a code draft carries the anchor and a trimmed-away blank note', () => {
    const d = codeDraft(anchor, '  ', { uri: 'file:///r/src/a.ts', line_start: 3, line_end: 4 });
    expect(d.key).toMatch(/^q-[0-9a-f]{12}$/);
    expect(d.quote).toEqual({ source: 'code', code: anchor, note: undefined });
    expect(d.label).toContain('src/a.ts');
  });

  it('a doc source draft quotes the selection verbatim with the lines, context and the section heading', () => {
    const d = docSourceDraft({ id: DOC, version: 12, body: BODY, line_start: 5, line_end: 5, selected: 'carries **its note**', note: 'why?', where: null }) as Draft;
    expect(d.quote).toMatchObject({ source: 'doc', id: DOC, version: 12, locator: { line_start: 5, line_end: 5 }, text: 'carries **its note**', note: 'why?' });
    expect(d.quote.context?.before).toContain('14.5');
    expect(d.label).toContain('14.5');
  });

  it('a doc source draft with no selection quotes the whole lines; lines outside the version are refused', () => {
    const d = docSourceDraft({ id: DOC, version: 12, body: BODY, line_start: 5, line_end: 6, selected: '', where: null }) as Draft;
    expect(d.quote.text).toBe('Every quote carries **its note** and a locator.\nSecond line of it.');
    expect(docSourceDraft({ id: DOC, version: 12, body: BODY, line_start: 9, line_end: 12, selected: '', where: null })).toHaveProperty('error');
    expect(docSourceDraft({ id: 'nope', version: 12, body: BODY, line_start: 1, line_end: 1, selected: 'x', where: null })).toHaveProperty('error');
  });

  it('a reader draft maps the rendered selection back to its markdown and narrows the lines', () => {
    const d = docReaderDraft({ id: DOC, version: 12, body: BODY, from: 5, to: 6, selected: 'carries its note', before: 'Every quote ' }) as Draft;
    expect(d.quote.text).toBe('carries **its note'); // C19 locateInSource: a verbatim source span (trailing markup is not extended)
    expect(d.quote.locator).toEqual({ line_start: 5, line_end: 5 });
    expect(d.where).toBeNull();
  });

  it('a reader selection that cannot be mapped quotes the whole block lines', () => {
    const d = docReaderDraft({ id: DOC, version: 12, body: BODY, from: 8, to: 9, selected: 'not in the doc at all' }) as Draft;
    expect(d.quote.text).toBe('## 14.7 Tray\nThe tray keeps order.');
    expect(d.quote.locator).toEqual({ line_start: 8, line_end: 9 });
  });

  it('a passage over 4096 bytes is cut on a code point', () => {
    const long = 'é'.repeat(3000);
    const d = docSourceDraft({ id: DOC, version: 1, body: long, line_start: 1, line_end: 1, selected: long, where: null }) as Draft;
    expect(new TextEncoder().encode(d.quote.text!).length).toBeLessThanOrEqual(PASSAGE_MAX_B);
    expect(long.startsWith(d.quote.text!)).toBe(true);
  });

  it('a message draft locates by code points (the board slices a Python str)', () => {
    const m = { id: M, text: '😀 ship the **tray** now', created_by: 'architect.epic-52edacd059' };
    const d = messageDraft(m, 'the tray', '😀 ship ') as Draft;
    expect(d.quote).toMatchObject({ source: 'message', id: M, text: 'the **tray' });
    const { char_start, char_end } = d.quote.locator!;
    expect(Array.from(m.text).slice(char_start!, char_end!).join('')).toBe('the **tray');
    expect(codePoints('😀x', 2)).toBe(1);
    expect(messageDraft(m, 'absent passage', '')).toHaveProperty('error');
    expect(messageDraft({ ...m, id: 'x' }, 'the tray', '')).toHaveProperty('error');
  });

  it('a chip clips the passage and marks the refused draft', () => {
    const d = codeDraft({ ...anchor, snippet: 'x'.repeat(400) }, 'n', null);
    const c = chipOf(d, d.key);
    expect(Array.from(c.passage).length).toBe(160);
    expect(c).toMatchObject({ key: d.key, source: 'code', note: 'n', invalid: true });
    expect(chipOf(d)).not.toHaveProperty('invalid');
  });
});

describe('Tray', () => {
  const mk = () => codeDraft(anchor, '', null);

  it('keeps order per thread; move, note, drop and sent act on keys', () => {
    const t = new Tray();
    const [a, b, c] = [mk(), mk(), mk()];
    t.add(T, a); t.add(T, b); t.add(T, c);
    expect(t.move(T, c.key, -1)).toBe(true);
    expect(t.list(T).map(d => d.key)).toEqual([a.key, c.key, b.key]);
    expect(t.move(T, a.key, -1)).toBe(false);
    expect(t.note(T, b.key, 'later')).toBe(true);
    expect(t.find(b.key)?.draft.quote.note).toBe('later');
    expect(t.drop(T, a.key)).toBe(true);
    expect(t.sent(T, [c.key]).map(d => d.key)).toEqual([c.key]);
    expect(t.list(T).map(d => d.key)).toEqual([b.key]);
    expect(t.list('s-0000000000')).toEqual([]);
  });

  it('refuses past the board maximum and forgets an emptied thread', () => {
    const t = new Tray();
    for (let i = 0; i < QUOTES_MAX; i++) expect(t.add(T, mk())).toBe(true);
    expect(t.add(T, mk())).toBe(false);
    for (const d of t.list(T)) t.drop(T, d.key);
    expect(t.threads()).toEqual([]);
    expect(t.data()).toEqual({});
  });

  it('quotesForSend follows the named order and refuses an unknown or repeated key', () => {
    const [a, b] = [mk(), mk()];
    expect(quotesForSend([a, b], [b.key, a.key])).toEqual({ quotes: [b.quote, a.quote], keys: [b.key, a.key] });
    expect(quotesForSend([a], [a.key, 'q-000000000000'])).toHaveProperty('error');
    expect(quotesForSend([a], [a.key, a.key])).toHaveProperty('error');
  });

  it('refusedKey reads the board index', () => {
    expect(refusedKey('quotes[1]: text not found at lines 5-5', ['q-a', 'q-b'])).toBe('q-b');
    expect(refusedKey('quotes[7]: x', ['q-a'])).toBeNull();
    expect(refusedKey('text too long', ['q-a'])).toBeNull();
  });

  it('restoreTray keeps valid drafts only', () => {
    const good = codeDraft(anchor, 'n', { uri: 'file:///a', line_start: 1, line_end: 2 });
    const doc = docSourceDraft({ id: DOC, version: 12, body: BODY, line_start: 5, line_end: 5, selected: 'its note', where: null }) as Draft;
    const raw = {
      [T]: [good, doc, { ...good, key: 'bad' }, { ...doc, quote: { ...doc.quote, id: '../x' } }, { ...good, quote: { source: 'eval' } }, null],
      'not-a-ticket': [good],
      's-1111111111': 'x',
    };
    expect(restoreTray(raw)).toEqual({ [T]: [good, doc] });
    expect(restoreTray(null)).toEqual({});
    expect(restoreTray('x')).toEqual({});
  });
});

describe('protocol', () => {
  const K = 'q-0123456789ab';
  it('a send may carry only quotes; quote keys are bounded, distinct and well-formed', () => {
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: '', kind: 'note', quoteKeys: [K] })).toEqual({ v: 1, type: 'send', ticketId: T, text: '', kind: 'note', quoteKeys: [K] });
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: '', kind: 'note', quoteKeys: [] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: 'x', kind: 'note', quoteKeys: [K, K] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: 'x', kind: 'note', quoteKeys: ['k'] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: 'x', kind: 'note', quoteKeys: Array.from({ length: 21 }, (_, i) => `q-${String(i).padStart(12, '0')}`) })).toBeNull();
  });

  it('parses the quote intents and drops malformed ones', () => {
    expect(parseInbound({ v: 1, type: 'quoteMessage', ticketId: T, messageId: M, text: 'x', before: '', note: 'n' })).toEqual({ v: 1, type: 'quoteMessage', ticketId: T, messageId: M, text: 'x', before: '', note: 'n' });
    expect(parseInbound({ v: 1, type: 'quoteMessage', ticketId: T, messageId: M, text: '  ' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'quoteMessage', ticketId: T, messageId: M, text: 'x', note: 'n'.repeat(2001) })).toBeNull();
    expect(parseInbound({ v: 1, type: 'quoteNote', ticketId: T, key: K, note: '' })).toEqual({ v: 1, type: 'quoteNote', ticketId: T, key: K, note: '' });
    expect(parseInbound({ v: 1, type: 'quoteMove', ticketId: T, key: K, by: 1 })).toEqual({ v: 1, type: 'quoteMove', ticketId: T, key: K, by: 1 });
    expect(parseInbound({ v: 1, type: 'quoteMove', ticketId: T, key: K, by: 2 })).toBeNull();
    expect(parseInbound({ v: 1, type: 'quoteDrop', ticketId: T, key: K })).toEqual({ v: 1, type: 'quoteDrop', ticketId: T, key: K });
    expect(parseInbound({ v: 1, type: 'quoteDrop', ticketId: T, key: 'x' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'openQuote', messageId: M, index: 2 })).toEqual({ v: 1, type: 'openQuote', messageId: M, index: 2 });
    expect(parseInbound({ v: 1, type: 'openQuote', messageId: M, index: -1 })).toBeNull();
  });

  it('the reader posts addQuote with bounded fields', () => {
    expect(parseReaderInbound({ v: 1, type: 'addQuote', from: 5, to: 6, text: 'x', before: '', note: '' })).toEqual({ v: 1, type: 'addQuote', from: 5, to: 6, text: 'x', before: '', note: '' });
    expect(parseReaderInbound({ v: 1, type: 'addQuote', from: 6, to: 5, text: 'x' })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'addQuote', from: 1, to: 1, text: ' ' })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'addQuote', from: 1, to: 1, text: 'x', note: 'n'.repeat(2001) })).toBeNull();
  });

  it('thread rows keep the board quotes, dropping malformed ones', () => {
    const q = quoteViews([
      { source: 'doc', id: DOC, version: 12, text: 'p', note: 'n', locator: { heading: '14.5 Quote + note', line_start: 5, line_end: 5 } },
      { source: 'code', text: 's', code: { repo_root: 'C:/r', path: 'a.ts', line_start: 1, line_end: 2, commit: null, dirty: true, snippet: 's', snippet_sha: 'x' } },
      { source: 'message', id: M, author: 'owner', text: 'm', locator: { char_start: 0, char_end: 1 } },
      { source: 'eval', text: 'x' }, { source: 'doc' }, null,
    ]);
    expect(q.map(x => x.source)).toEqual(['doc', 'code', 'message']);
    expect(q[1].code).toMatchObject({ path: 'a.ts', dirty: true });
    expect(quoteSourceLabel(q[0])).toContain('14.5');
    expect(quoteViews('x')).toEqual([]);
  });
});

describe('package.json (architect m-db0d013529)', () => {
  it('binds Ctrl+Alt+Q only in quotable editors with a selection, and nothing to Ctrl+Shift+Q', async () => {
    const pkg = JSON.parse((await import('node:fs')).readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
    const kb = pkg.contributes.keybindings as { command: string; key: string; when: string }[];
    expect(kb.some(k => /ctrl\+shift\+q/i.test(k.key))).toBe(false);
    const q = kb.filter(k => k.command.startsWith('edp.quote.'));
    expect(q).toEqual([{ command: 'edp.quote.comment', key: 'ctrl+alt+q', when: 'editorTextFocus && editorHasSelection && (resourceScheme == file || resourceScheme == edp-doc)' }]);
  });
});
