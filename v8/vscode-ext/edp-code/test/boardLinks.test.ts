import { describe, it, expect } from 'vitest';
import { boardTicketUrl, isEpicId } from '../src/core/boardLinks';

// C10: every open-on-board link (chat panel, badge, tag) goes through boardTicketUrl.
describe('boardTicketUrl', () => {
  it.each([
    ['http://127.0.0.1:9400', 'epic-52edacd059', undefined, undefined, 'http://127.0.0.1:9400/ui/epic/epic-52edacd059'],
    ['http://127.0.0.1:9400/', 'epic-52edacd059', 'm-66f8eeedc4', undefined, 'http://127.0.0.1:9400/ui/epic/epic-52edacd059#m-66f8eeedc4'],
    ['https://msi.tail884b19.ts.net//', 's-e1cec79882', undefined, undefined, 'https://msi.tail884b19.ts.net/ui/ticket/s-e1cec79882'],
    ['http://h:1', 's-e1cec79882', 'm-1', undefined, 'http://h:1/ui/ticket/s-e1cec79882#m-1'],
    ['http://h:1', 't-3e246b5e32', null, undefined, 'http://h:1/ui/ticket/t-3e246b5e32'],
    ['http://h:1', 'x-1', undefined, 'epic', 'http://h:1/ui/epic/x-1'],
    ['http://h:1', 'epic-1', undefined, 'story', 'http://h:1/ui/ticket/epic-1'],
    ['http://h:1', 'a b', 'm/1', undefined, 'http://h:1/ui/ticket/a%20b#m%2F1'],
  ])('%s + %s (#%s, kind %s) → %s', (base, id, mid, kind, want) => {
    expect(boardTicketUrl(base, id, mid, kind)).toBe(want);
  });

  it('kind wins over the id prefix; the prefix decides when kind is unknown', () => {
    expect(isEpicId('epic-1')).toBe(true);
    expect(isEpicId('epic-1', null)).toBe(true);
    expect(isEpicId('s-1')).toBe(false);
    expect(isEpicId('s-1', 'epic')).toBe(true);
    expect(isEpicId('epic-1', 'task')).toBe(false);
  });
});
