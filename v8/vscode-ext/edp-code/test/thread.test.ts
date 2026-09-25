import { describe, expect, it } from 'vitest';
import { fromMessageRow, ThreadStore, type ThreadRow } from '../src/core/thread';

const T = 's-b00dbbcdea';
const row = (n: number, at: string): ThreadRow => ({ id: `m-${String(n).padStart(10, '0')}`, seq: 100 + n, by: 'owner', to: null, kind: 'note', text: `t${n}`, at, reply_to: null, code_context: null });

describe('ThreadStore', () => {
  it('merges a page and live rows by message id (no duplicates)', () => {
    const s = new ThreadStore(T);
    expect(s.loadPage({ thread: [row(1, '2026-09-25T06:00:00+00:00'), row(2, '2026-09-25T06:01:00+00:00')], thread_total: 2, thread_before: null })).toHaveLength(2);
    const live = fromMessageRow({ id: row(2, '').id, ticket_id: T, created_at: '2026-09-25T06:01:00Z', created_by: 'owner', to: null, kind: 'note', text: 't2', reply_to: null }, 17050);
    expect(s.merge([live])).toEqual([]);
    const live3 = { ...live, id: 'm-0000000003', seq: 17051, created_at: '2026-09-25T06:02:00.5Z' };
    expect(s.merge([live3]).map(m => m.id)).toEqual(['m-0000000003']);
    expect(s.merge([live3])).toEqual([]); // the same event replayed after a reconnect
    expect(s.items.map(m => m.id)).toEqual([row(1, '').id, row(2, '').id, 'm-0000000003']);
  });

  it('sorts out-of-order arrivals by time, whatever the time format', () => {
    const s = new ThreadStore(T);
    s.merge([
      fromMessageRow({ id: 'm-000000000b', ticket_id: T, created_at: '2026-09-25T06:05:00Z', created_by: 'a', to: null, kind: 'note', text: '', reply_to: null }, 9),
      fromMessageRow({ id: 'm-000000000a', ticket_id: T, created_at: '2026-09-25T06:04:59.999+00:00', created_by: 'a', to: null, kind: 'note', text: '', reply_to: null }, 10),
    ]);
    expect(s.items.map(m => m.id)).toEqual(['m-000000000a', 'm-000000000b']);
  });

  it('prepends an older page and tracks the cursor', () => {
    const s = new ThreadStore(T);
    s.loadPage({ thread: [row(5, '2026-09-25T06:05:00+00:00')], thread_total: 3, thread_before: 105 });
    expect(s.before).toBe(105);
    const older = s.loadOlder({ thread: [row(3, '2026-09-25T06:03:00+00:00'), row(4, '2026-09-25T06:04:00+00:00')], thread_total: 3, thread_before: null });
    expect(older.map(m => m.text)).toEqual(['t3', 't4']);
    expect(s.before).toBeNull();
    expect(s.items.map(m => m.text)).toEqual(['t3', 't4', 't5']);
  });

  it('never merges another ticket\'s rows (threads stay separate)', () => {
    const s = new ThreadStore(T);
    const other = fromMessageRow({ id: 'm-0000000009', ticket_id: 'epic-52edacd059', created_at: '2026-09-25T06:05:00Z', created_by: 'a', to: null, kind: 'note', text: '', reply_to: null }, 1);
    expect(s.merge([other])).toEqual([]);
    expect(s.size).toBe(0);
  });
});
