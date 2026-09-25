import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { activeMention, mentionedHandles, mentionSpans } from '../src/core/mentions';

// the shared contract the board (tests/test_mentions_contract.py) and the SPA (mentions.test.ts) pass too
const fixture = JSON.parse(readFileSync(resolve(import.meta.dirname, '../../../tests/fixtures/mention_cases.json'), 'utf8')) as
  { handles: string[]; cases: { text: string; expect: string[] }[] };
const people = fixture.handles.map(h => ({ handle: h, id: h }));

describe('mentions: tests/fixtures/mention_cases.json', () => {
  it('has cases', () => expect(fixture.cases.length).toBeGreaterThan(5));
  for (const c of fixture.cases) {
    it(JSON.stringify(c.text), () => expect(mentionedHandles(c.text, people)).toEqual(c.expect));
  }
});

describe('mentionSpans / activeMention', () => {
  it('spans cover exactly @handle', () => {
    const t = 'ping @alice, and @bob.';
    expect(mentionSpans(t).map(s => t.slice(s.start, s.end))).toEqual(['@alice', '@bob']);
  });

  it('finds the @-query at the caret, empty right after @', () => {
    expect(activeMention('hi @arch', 8)).toEqual({ start: 3, query: 'arch' });
    expect(activeMention('@', 1)).toEqual({ start: 0, query: '' });
    expect(activeMention('two @a and @eng', 15)).toEqual({ start: 11, query: 'eng' });
  });

  it('no query inside code, after an e-mail local part, or after a space', () => {
    expect(activeMention('`@bob`', 5)).toBeUndefined();
    expect(activeMention('mail alice@bo', 13)).toBeUndefined();
    expect(activeMention('@bob done', 9)).toBeUndefined();
  });
});
