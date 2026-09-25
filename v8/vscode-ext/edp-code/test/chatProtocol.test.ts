import { describe, expect, it } from 'vitest';
import { parseInbound, TEXT_MAX } from '../src/core/chatProtocol';

const people = new Set(['owner', 'architect.epic-52edacd059']);

describe('parseInbound', () => {
  it('accepts each valid type', () => {
    expect(parseInbound({ v: 1, type: 'ready' })).toEqual({ v: 1, type: 'ready' });
    expect(parseInbound({ v: 1, type: 'loadOlder' })).toEqual({ v: 1, type: 'loadOlder' });
    expect(parseInbound({ v: 1, type: 'signIn' })).toEqual({ v: 1, type: 'signIn' });
    expect(parseInbound({ v: 1, type: 'pickTicket' })).toEqual({ v: 1, type: 'pickTicket' });
    expect(parseInbound({ v: 1, type: 'pickTicket', id: 'epic-52edacd059' })).toEqual({ v: 1, type: 'pickTicket', id: 'epic-52edacd059' });
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'hi @owner', kind: 'question', to: 'owner', replyTo: 'm-4d65f13712' }, people))
      .toEqual({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'hi @owner', kind: 'question', to: 'owner', replyTo: 'm-4d65f13712' });
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'note', kind: 'note', to: '' }, people)).toEqual({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'note', kind: 'note' });
    expect(parseInbound({ v: 1, type: 'openCode', messageId: 'm-0123456789' })).toEqual({ v: 1, type: 'openCode', messageId: 'm-0123456789' });
    expect(parseInbound({ v: 1, type: 'openBoard', ticketId: 's-b00dbbcdea', messageId: 'm-0123456789' }))
      .toEqual({ v: 1, type: 'openBoard', ticketId: 's-b00dbbcdea', messageId: 'm-0123456789' });
  });

  it('drops an unknown type, a missing or wrong v, and non-objects', () => {
    expect(parseInbound({ v: 1, type: 'eval', code: 'x' })).toBeNull();
    expect(parseInbound({ type: 'ready' })).toBeNull();
    expect(parseInbound({ v: 2, type: 'ready' })).toBeNull();
    expect(parseInbound('ready')).toBeNull();
    expect(parseInbound(null)).toBeNull();
  });

  it('drops bad ticket and message ids', () => {
    expect(parseInbound({ v: 1, type: 'pickTicket', id: 's-XYZ' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'pickTicket', id: '../etc' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'openCode', messageId: 'm-1' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'openBoard', ticketId: 'x-0123456789' })).toBeNull();
  });

  it('bounds the text: empty, whitespace-only and 32769 chars are refused', () => {
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: '', kind: 'note' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: '   ', kind: 'note' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x'.repeat(TEXT_MAX + 1), kind: 'note' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x'.repeat(TEXT_MAX), kind: 'note' })).not.toBeNull();
  });

  it('refuses a kind outside the enum and a `to` not in the last people list', () => {
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x', kind: 'deviation' }, people)).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x', kind: 'note', to: 'mallory' }, people)).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x', kind: 'note', to: '../owner' }, people)).toBeNull();
  });

  it('refuses a send with no or a bad ticket id', () => {
    expect(parseInbound({ v: 1, type: 'send', text: 'x', kind: 'note' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: 'nope', text: 'x', kind: 'note' })).toBeNull();
  });

  it('ignores extra keys (never spread into a request)', () => {
    const m = parseInbound({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x', kind: 'note', token: 'secret', headers: { 'X-Token': 'y' }, code_context: { path: '../x' } });
    expect(m).toEqual({ v: 1, type: 'send', ticketId: 's-b00dbbcdea', text: 'x', kind: 'note' });
    expect(parseInbound({ v: 1, type: 'openCode', messageId: 'm-0123456789', path: '../../etc/passwd' })).toEqual({ v: 1, type: 'openCode', messageId: 'm-0123456789' });
  });
});

describe('parseInbound: #-tags (C11)', () => {
  it('findPaths: a query and a sequence number', () => {
    expect(parseInbound({ v: 1, type: 'findPaths', q: 'v8/vs', seq: 3 })).toEqual({ v: 1, type: 'findPaths', q: 'v8/vs', seq: 3 });
    expect(parseInbound({ v: 1, type: 'findPaths', q: '', seq: 0 })).toEqual({ v: 1, type: 'findPaths', q: '', seq: 0 });
    expect(parseInbound({ v: 1, type: 'findPaths', q: 'x', seq: -1 })).toBeNull();
    expect(parseInbound({ v: 1, type: 'findPaths', q: 'x', seq: 1.5 })).toBeNull();
    expect(parseInbound({ v: 1, type: 'findPaths', q: 'x' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'findPaths', q: 'a\nb', seq: 1 })).toBeNull();
    expect(parseInbound({ v: 1, type: 'findPaths', q: 'x'.repeat(1025), seq: 1 })).toBeNull();
  });

  it('checkPaths: repo-relative paths only, deduplicated, bounded', () => {
    expect(parseInbound({ v: 1, type: 'checkPaths', paths: ['a/b.ts', 'a', 'a/b.ts'] })).toEqual({ v: 1, type: 'checkPaths', paths: ['a/b.ts', 'a'] });
    for (const bad of ['../x', '/etc/passwd', 'C:/x', 'a\\b', 'a\u0008b', 'a/', 'a`b', '']) {
      expect(parseInbound({ v: 1, type: 'checkPaths', paths: ['ok.ts', bad] })).toBeNull();
    }
    expect(parseInbound({ v: 1, type: 'checkPaths', paths: 'a.ts' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'checkPaths', paths: Array.from({ length: 201 }, (_, i) => `f${i}.ts`) })).toBeNull();
  });

  it('openPath: one repo-relative path, never outside the repo', () => {
    expect(parseInbound({ v: 1, type: 'openPath', path: 'v8/README.md' })).toEqual({ v: 1, type: 'openPath', path: 'v8/README.md' });
    for (const bad of ['../x', '/x', 'C:/x', 'a/../../x', 'a/', undefined, 3]) {
      expect(parseInbound({ v: 1, type: 'openPath', path: bad })).toBeNull();
    }
  });
});
