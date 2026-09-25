// C22 s-3b86872bf0: Reply in the chat webview: the parent excerpt, the saved reply target and the showMessage intent.
import { describe, expect, it } from 'vitest';
import { parseInbound } from '../src/core/chatProtocol';
import { excerpt, EXCERPT_MAX, replyRef, REPLIES_MAX, restoreReplies } from '../src/core/reply';
import { restoreLocal } from '../src/core/viewState';

describe('excerpt', () => {
  it('one line: whitespace collapsed and trimmed', () => expect(excerpt('  a\n\n b\tc  ')).toBe('a b c'));
  it('short text is kept whole; long text is cut to the cap with an ellipsis', () => {
    expect(excerpt('x'.repeat(EXCERPT_MAX))).toBe('x'.repeat(EXCERPT_MAX));
    const e = excerpt('y'.repeat(EXCERPT_MAX + 1));
    expect(Array.from(e)).toHaveLength(EXCERPT_MAX);
    expect(e.endsWith('…')).toBe(true);
  });
  it('never splits a surrogate pair', () => {
    const e = excerpt('😀'.repeat(EXCERPT_MAX + 5));
    expect(e).toBe('😀'.repeat(EXCERPT_MAX - 1) + '…');
  });
});

describe('replyRef', () => {
  it('the author is the To a reply starts with', () =>
    expect(replyRef({ id: 'm-0123456789', created_by: 'architect.epic-52edacd059', text: 'Two things\nbefore you build' }))
      .toEqual({ id: 'm-0123456789', by: 'architect.epic-52edacd059', excerpt: 'Two things before you build', to: 'architect.epic-52edacd059' }));
});

describe('restoreReplies', () => {
  const ok = { id: 'm-0123456789', by: 'owner', excerpt: 'p', to: '' };
  it('keeps well-formed targets by thread', () => expect(restoreReplies({ 's-0123456789': ok })).toEqual({ 's-0123456789': ok }));
  it('drops bad thread keys, bad ids, missing fields and smuggled fields', () => {
    expect(restoreReplies({ bad: ok, 's-0123456789': { ...ok, id: 'm-XYZ' }, 'epic-0123456789': { id: 'm-0123456789', by: 'owner' } })).toEqual({});
    expect(restoreReplies({ 's-0123456789': { ...ok, evil: 1 } })).toEqual({ 's-0123456789': ok });
    for (const g of [null, 7, 'x', []]) expect(restoreReplies(g)).toEqual({});
  });
  it('keeps the newest REPLIES_MAX', () => {
    const many = Object.fromEntries(Array.from({ length: REPLIES_MAX + 3 }, (_, i) => [`s-${i.toString(16).padStart(10, '0')}`, ok]));
    const r = restoreReplies(many);
    expect(Object.keys(r)).toHaveLength(REPLIES_MAX);
    expect(r['s-0000000000']).toBeUndefined();
  });
  it('a pre-C22 state has none', () => expect(restoreLocal({ v: 1, drafts: {} }).replies).toEqual({}));
});

describe('showMessage (a reply parent not yet loaded)', () => {
  it('accepts a thread id and a message id', () =>
    expect(parseInbound({ v: 1, type: 'showMessage', ticketId: 's-b00dbbcdea', messageId: 'm-0123456789' }))
      .toEqual({ v: 1, type: 'showMessage', ticketId: 's-b00dbbcdea', messageId: 'm-0123456789' }));
  it('drops bad or missing ids', () => {
    expect(parseInbound({ v: 1, type: 'showMessage', ticketId: 's-b00dbbcdea' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'showMessage', ticketId: 'x', messageId: 'm-0123456789' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'showMessage', ticketId: 's-b00dbbcdea', messageId: 'm-0123' })).toBeNull();
  });
  it('a reply send carries replyTo, with a chip and attachments', () =>
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'see', kind: 'answer', to: 'owner', replyTo: 'm-0123456789',
      chipId: 'k-0123456789ab', attachmentIds: ['art-0123456789'] }, new Set(['owner'])))
      .toMatchObject({ replyTo: 'm-0123456789', to: 'owner', chipId: 'k-0123456789ab', attachmentIds: ['art-0123456789'] }));
});
