// C15 review fixes (s-e14d316891): the Inbox host half. A read in flight when a write lands cannot bring the
// answered row back; a verdict carries the evidence version the viewer opened, not a newer one the row was
// relabelled to; a 401 settles the tab before the sign-in path; a disposed host schedules nothing.
import { describe, expect, it, vi } from 'vitest';
import type { Board } from '../src/core/api';
import type { HostToView } from '../src/core/chatProtocol';
import { questionKey, signoffKey, type DecisionsHome } from '../src/core/inbox';
import { InboxHost, type InboxScope } from '../src/vscode/inbox';

const STORY = 's-0123456789', M1 = 'm-1111111111', C1 = 'c-1111111111', DOC = 'report-aaaaaaaaaa';
const home = (version: number, withQ = true): DecisionsHome => ({
  signoffs: [{ criterion: { id: C1, text: 'works', evidence_ref: DOC }, ticket: { id: STORY, title: 'S', assignee: null },
    doc: { id: DOC, title: 'r', doc_type: 'report', version } }],
  gates: [],
  questions: withQ ? [{ id: M1, ticket_id: STORY, created_by: 'engineer.x', kind: 'question', text: 'which?' }] : [],
});
const scope: InboxScope = { id: STORY, ids: new Set([STORY]), titles: new Map() };

function host(board: Partial<Board>) {
  const posts: HostToView[] = [];
  const authFail = vi.fn();
  const h = new InboxHost(() => board as Board, () => 'http://b', () => scope, m => posts.push(m), async () => {}, authFail, () => {});
  h.openDoc = async () => {};
  return { h, posts, authFail };
}
const deferred = <T>() => { let resolve!: (v: T) => void; const p = new Promise<T>(r => { resolve = r; }); return { p, resolve }; };

describe('InboxHost', () => {
  it('a read that began before a write landed does not list the answered row again', async () => {
    const reads = [deferred<DecisionsHome>()];
    let n = 0;
    const board = { decisions: vi.fn(() => (n++ === 0 ? Promise.resolve(home(1)) : reads[0].p)), send: vi.fn(async () => ({})) };
    const { h } = host(board as never);
    await h.open();
    expect(h.snapshot(STORY)!.items.map(i => i.key)).toContain(questionKey(M1));
    const stale = h.refresh(); // in flight: its answer still lists the question
    await h.answer(questionKey(M1), 'this one');
    reads[0].resolve(home(1));
    await stale;
    expect(h.snapshot(STORY)!.items.map(i => i.key)).not.toContain(questionKey(M1));
    h.dispose();
  });

  it('a verdict carries the version the viewer opened; the row relabelled since does not upgrade it', async () => {
    let v = 1;
    // the board refuses the stale v1 (the row stays), then takes v2
    const verdict = vi.fn().mockRejectedValueOnce(Object.assign(new Error('you are ruling version 1 but the doc is now v2'), { status: 409 }))
      .mockResolvedValue({});
    const { h, posts } = host({ decisions: async () => home(v), verdict } as never);
    await h.open();
    await h.openRow(signoffKey(C1)); // read v1
    v = 2; await h.refresh(); // the row now says v2
    await h.verdict(signoffKey(C1), 'fail', 'misses p95', 2);
    expect(verdict).toHaveBeenLastCalledWith(expect.objectContaining({ criterion_id: C1, evidence_version: 1 }));
    expect(posts.at(-1)).toMatchObject({ type: 'inboxDone', ok: false, text: expect.stringContaining('now v2') });
    await h.openRow(signoffKey(C1)); // read v2
    await h.verdict(signoffKey(C1), 'fail', 'misses p95', 2);
    expect(verdict).toHaveBeenLastCalledWith(expect.objectContaining({ evidence_version: 2 }));
    h.dispose();
  });

  it('never opened: the version the row shows', async () => {
    const verdict = vi.fn(async () => ({}));
    const { h } = host({ decisions: async () => home(3), verdict } as never);
    await h.open();
    await h.verdict(signoffKey(C1), 'pass', '', 3);
    expect(verdict).toHaveBeenLastCalledWith(expect.objectContaining({ evidence_version: 3 }));
    h.dispose();
  });

  it('a 401 on a fresh scope settles the tab (not loading) before the sign-in path', async () => {
    const { h, posts, authFail } = host({ decisions: async () => { throw Object.assign(new Error('unauthorized'), { status: 401 }); } } as never);
    await h.open();
    expect(authFail).toHaveBeenCalledOnce();
    const last = posts.at(-1) as Extract<HostToView, { type: 'inbox' }>;
    expect(last.type).toBe('inbox');
    expect(last.inbox).toMatchObject({ scope: STORY, loading: false });
    expect(last.inbox!.error).toMatch(/unauthorized/);
  });

  it('a write settling after dispose schedules no read', async () => {
    vi.useFakeTimers();
    try {
      const sent = deferred<unknown>();
      const decisions = vi.fn(async () => home(1));
      const { h } = host({ decisions, send: () => sent.p } as never);
      await h.open();
      const w = h.answer(questionKey(M1), 'x');
      h.dispose();
      sent.resolve({});
      await w;
      const calls = decisions.mock.calls.length;
      await vi.advanceTimersByTimeAsync(2000);
      expect(decisions.mock.calls.length).toBe(calls);
    } finally { vi.useRealTimers(); }
  });
});
