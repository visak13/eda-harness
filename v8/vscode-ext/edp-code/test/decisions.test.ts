// C17 s-5e83f9d0af: the Decisions tab's rows (core/decisions.ts), its inbound intents, its board calls, and the
// host half (a 403 stays in the tab, writes go through the existing routes with the viewer's reason).
import { describe, expect, it, vi } from 'vitest';
import { boardClient, BoardError, type Board, type Creds } from '../src/core/api';
import { parseInbound, type HostToView } from '../src/core/chatProtocol';
import { decisionRows, decisionsBadge, reasonProblem, rowActions, REASON_MAX, type BoardDecision, type BoardDecisionList } from '../src/core/decisions';
import { DecisionsHost } from '../src/vscode/decisionsTab';

const EPIC = 'epic-0123456789', S1 = 's-0000000001';
const D1 = 'dec-1111111111', D2 = 'dec-2222222222', D3 = 'dec-3333333333', M1 = 'm-aaaaaaaaaa', DOC = 'design-bbbbbbbbbb';
const dec = (id: string, over: Partial<BoardDecision> = {}): BoardDecision => ({
  id, scope: EPIC, text: `rule ${id}`, detail: '', source: null, source_kind: null, source_ticket: null, decided_by: 'architect.x',
  decided_at: '2026-09-25T10:00:00Z', binding: false, status: 'live', replaces: [], withdrawn_reason: '', ...over,
});
const list = (decisions: BoardDecision[], can_manage = true): BoardDecisionList =>
  ({ scope: EPIC, epic: EPIC, decisions, can_manage, counts: { live: 0, withdrawn: 0 } });

describe('decisionRows', () => {
  it('keeps the board order and fields; a message source opens its thread, a doc source the reader', () => {
    const rows = decisionRows(list([
      dec(D1, { binding: true, source: M1, source_kind: 'message', source_ticket: S1, detail: 'why' }),
      dec(D2, { source: DOC, source_kind: 'doc', replaces: [D3, 'bogus'] }),
      dec(D3, { status: 'withdrawn', withdrawn_reason: 'mistaken', source: 'abc1234', source_kind: 'other' }),
    ]));
    expect(rows.map(r => r.id)).toEqual([D1, D2, D3]);
    expect(rows[0]).toMatchObject({ binding: true, detail: 'why', decidedBy: 'architect.x', source: { kind: 'message', id: M1, ticketId: S1 }, sourceText: null });
    expect(rows[1]).toMatchObject({ source: { kind: 'doc', id: DOC }, replaces: [D3] });
    expect(rows[2]).toMatchObject({ status: 'withdrawn', withdrawnReason: 'mistaken', source: null, sourceText: 'abc1234' });
  });
  it('drops malformed ids, unknown statuses (replaced) and a message source without a valid ticket', () => {
    const rows = decisionRows(list([dec('dec-nothex!!!!'), dec(D1, { status: 'replaced' }), dec(D2, { source: M1, source_kind: 'message', source_ticket: '../x' })]));
    expect(rows.map(r => r.id)).toEqual([D2]);
    expect(rows[0].source).toBeNull();
    expect(decisionRows({} as BoardDecisionList)).toEqual([]);
  });
  it('the badge counts live decisions only', () => {
    const rows = decisionRows(list([dec(D1), dec(D2), dec(D3, { status: 'withdrawn' })]));
    expect(decisionsBadge({ scope: EPIC, rows, canManage: false, loading: false, error: null })).toEqual({ text: '2', aria: '2 live decisions' });
    expect(decisionsBadge({ scope: EPIC, rows: rows.slice(2), canManage: false, loading: false, error: null })).toBeNull();
    expect(decisionsBadge(null)).toBeNull();
  });
  it('actions: only a manager, only on a live row', () => {
    const [live, gone] = decisionRows(list([dec(D1), dec(D2, { status: 'withdrawn' })]));
    expect(rowActions(live, true)).toEqual({ withdraw: true, binding: true });
    expect(rowActions(live, false)).toEqual({ withdraw: false, binding: false });
    expect(rowActions(gone, true)).toEqual({ withdraw: false, binding: false });
  });
  it('a withdraw needs a one-line reason within the cap; binding may omit it', () => {
    expect(reasonProblem('withdraw', '  ')).toMatch(/needs a reason/);
    expect(reasonProblem('binding', '')).toBeNull();
    expect(reasonProblem('withdraw', 'a\nb')).toMatch(/one line/);
    expect(reasonProblem('binding', 'x'.repeat(REASON_MAX + 1))).toMatch(/240/);
    expect(reasonProblem('withdraw', 'superseded by the C18 route')).toBeNull();
  });
});

describe('Decisions intents (parseInbound)', () => {
  it('open / withdraw take a decision id; binding a boolean; refresh nothing', () => {
    expect(parseInbound({ v: 1, type: 'decisionOpen', id: D1, scope: 'x' })).toEqual({ v: 1, type: 'decisionOpen', id: D1 });
    expect(parseInbound({ v: 1, type: 'decisionWithdraw', id: D1, reason: 'smuggled' })).toEqual({ v: 1, type: 'decisionWithdraw', id: D1 });
    expect(parseInbound({ v: 1, type: 'decisionBinding', id: D1, binding: false })).toEqual({ v: 1, type: 'decisionBinding', id: D1, binding: false });
    expect(parseInbound({ v: 1, type: 'decisionsRefresh' })).toEqual({ v: 1, type: 'decisionsRefresh' });
  });
  it('refuses a malformed id or a non-boolean flag', () => {
    expect(parseInbound({ v: 1, type: 'decisionOpen', id: 'm-aaaaaaaaaa' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'decisionWithdraw', id: '../dec' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'decisionBinding', id: D1, binding: 'true' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'decisionBinding', id: D1 })).toBeNull();
  });
});

describe('board calls', () => {
  const creds = async (): Promise<Creds> => ({ participant: 'owner', token: 't' });
  const ok = (value: unknown) => new Response(JSON.stringify({ ok: true, value }), { status: 200 });
  const client = () => {
    const f = vi.fn(async (_u: unknown, _i?: RequestInit) => ok({}));
    return { f, c: boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch) };
  };
  const call = (f: ReturnType<typeof client>['f']) => {
    const [u, i] = f.mock.calls[0] as unknown as [URL, RequestInit];
    return { url: String(u), method: i.method, body: i.body ? JSON.parse(i.body as string) : undefined };
  };
  it('lists by scope, withdraws with the reason, sets binding with the flag and reason', async () => {
    let t = client(); await t.c.scopeDecisions(EPIC);
    expect(call(t.f)).toEqual({ url: `http://127.0.0.1:9400/v1/decisions?scope=${EPIC}`, method: 'GET', body: undefined });
    t = client(); await t.c.withdrawDecision(D1, 'mistaken');
    expect(call(t.f)).toEqual({ url: `http://127.0.0.1:9400/v1/decisions/${D1}/withdraw`, method: 'POST', body: { reason: 'mistaken' } });
    t = client(); await t.c.setBinding(D1, true, '');
    expect(call(t.f)).toEqual({ url: `http://127.0.0.1:9400/v1/decisions/${D1}/binding`, method: 'POST', body: { binding: true, reason: '' } });
  });
  it('the C16 reader approve/reject sends the version read as expected_version', async () => {
    let t = client(); await t.c.docResolve('strategyll-cccccccccc', true, 3);
    expect(call(t.f)).toEqual({ url: 'http://127.0.0.1:9400/v1/docs/strategyll-cccccccccc/approve', method: 'POST', body: { expected_version: 3 } });
    t = client(); await t.c.docResolve('strategyll-cccccccccc', false, 2);
    expect(call(t.f)).toMatchObject({ url: 'http://127.0.0.1:9400/v1/docs/strategyll-cccccccccc/reject', body: { expected_version: 2 } });
  });
});

describe('DecisionsHost', () => {
  /** `answer`: what the reason box returns; null = the viewer cancelled it */
  function host(board: Partial<Board>, answer: string | null = 'because') {
    const posts: HostToView[] = [];
    const authFail = vi.fn();
    const open = { message: vi.fn(async () => {}), doc: vi.fn(async () => {}) };
    const h = new DecisionsHost(() => board as Board, () => ({ id: EPIC }), m => posts.push(m), open, authFail, () => {});
    h.ask = vi.fn(async () => answer ?? undefined);
    const last = () => (posts.filter(p => p.type === 'decisions').at(-1) as Extract<HostToView, { type: 'decisions' }>).decisions;
    return { h, posts, authFail, open, last };
  }

  it('a 403 (not a participant) shows in the tab and never signs out', async () => {
    const { h, authFail, last } = host({ scopeDecisions: async () => { throw new BoardError('forbidden', 'owner2 is not a participant of epic-x', 403); } });
    await h.openScope();
    expect(last()).toMatchObject({ loading: false, rows: [], error: expect.stringContaining('not a participant') });
    expect(authFail).not.toHaveBeenCalled();
    h.dispose();
  });
  it('a 403 after a good read drops the rows and the actions (another identity, or access removed)', async () => {
    let refuse = false;
    const t = host({ scopeDecisions: async () => { if (refuse) throw new BoardError('forbidden', 'x is not a participant of epic-y', 403); return list([dec(D1)]); } });
    await t.h.openScope();
    expect(t.last()).toMatchObject({ rows: [{ id: D1 }], canManage: true });
    refuse = true;
    await t.h.refresh();
    expect(t.last()).toMatchObject({ rows: [], canManage: false, error: expect.stringContaining('not a participant') });
    t.h.dispose();
  });
  it('a 401 settles the tab, then the sign-in path', async () => {
    const { h, authFail, last } = host({ scopeDecisions: async () => { throw new BoardError('unauthorized', 'bad token', 401); } });
    await h.openScope();
    expect(last().loading).toBe(false);
    expect(authFail).toHaveBeenCalledOnce();
    h.dispose();
  });
  it('withdraw asks the reason, sends it, re-reads; cancelling sends nothing', async () => {
    let rows = [dec(D1)];
    const withdrawDecision = vi.fn(async () => { rows = [dec(D1, { status: 'withdrawn', withdrawn_reason: 'because' })]; return rows[0]; });
    const t = host({ scopeDecisions: async () => list(rows), withdrawDecision });
    await t.h.openScope();
    await t.h.withdraw(D1);
    expect(withdrawDecision).toHaveBeenCalledWith(D1, 'because');
    expect(t.last()).toMatchObject({ busy: null, notice: { id: D1, ok: true }, rows: [{ status: 'withdrawn' }] });
    const c = host({ scopeDecisions: async () => list([dec(D1)]), withdrawDecision: vi.fn() }, null);
    await c.h.openScope();
    await c.h.withdraw(D1);
    expect((c.h as unknown as { board: () => Board }).board().withdrawDecision).not.toHaveBeenCalled();
    expect(c.last()).toMatchObject({ busy: null, notice: null });
  });
  it('binding flips with the reason; a refusal is the board text on the row', async () => {
    const setBinding = vi.fn().mockRejectedValueOnce(new BoardError('scope', 'engineer may not change a decision binding flag', 400)).mockResolvedValue({});
    const t = host({ scopeDecisions: async () => list([dec(D1)]), setBinding }, '');
    await t.h.openScope();
    await t.h.binding(D1, true);
    expect(setBinding).toHaveBeenLastCalledWith(D1, true, '');
    expect(t.last().notice).toEqual({ id: D1, ok: false, text: 'engineer may not change a decision binding flag' });
    expect(t.authFail).not.toHaveBeenCalled();
    await t.h.binding(D1, true);
    expect(t.last().notice).toMatchObject({ id: D1, ok: true });
  });
  it('no write for a viewer the board did not let manage, nor on a withdrawn row', async () => {
    const withdrawDecision = vi.fn(), setBinding = vi.fn();
    const t = host({ scopeDecisions: async () => list([dec(D1), dec(D2, { status: 'withdrawn' })], false), withdrawDecision, setBinding });
    await t.h.openScope();
    await t.h.withdraw(D1);
    await t.h.binding(D1, true);
    expect(withdrawDecision).not.toHaveBeenCalled();
    expect(setBinding).not.toHaveBeenCalled();
    const m = host({ scopeDecisions: async () => list([dec(D2, { status: 'withdrawn' })]), withdrawDecision });
    await m.h.openScope();
    await m.h.withdraw(D2);
    expect(withdrawDecision).not.toHaveBeenCalled();
  });
  it('a reason answered after a sign-out or identity switch is dropped: nothing sent, nothing settled into the new state', async () => {
    const withdrawDecision = vi.fn(async () => dec(D1)), setBinding = vi.fn(async () => dec(D1));
    const t = host({ scopeDecisions: async () => list([dec(D1)]), withdrawDecision, setBinding });
    await t.h.openScope();
    let answer!: (v: string | undefined) => void;
    t.h.ask = vi.fn(() => new Promise<string | undefined>(r => (answer = r)));
    const w = t.h.withdraw(D1);
    t.h.clear(); // identity B
    await t.h.openScope();
    const n = t.posts.length;
    answer('stale reason');
    await w;
    expect(withdrawDecision).not.toHaveBeenCalled();
    expect(t.posts.length).toBe(n);
    expect(t.last()).toMatchObject({ busy: null, notice: null });
    const b = t.h.binding(D1, true);
    t.h.clear();
    await t.h.openScope();
    answer('');
    await b;
    expect(setBinding).not.toHaveBeenCalled();
    t.h.dispose();
  });
  it('a failed re-read while a write is in flight keeps the write guard: no second write starts', async () => {
    let fail = false, done!: () => void;
    const setBinding = vi.fn(() => new Promise<BoardDecision>(r => (done = () => r(dec(D1)))));
    const withdrawDecision = vi.fn(async () => dec(D2));
    const t = host({ scopeDecisions: async () => { if (fail) throw new BoardError('io', 'board away', 502); return list([dec(D1), dec(D2)]); }, setBinding, withdrawDecision });
    await t.h.openScope();
    const b = t.h.binding(D1, true);
    await vi.waitFor(() => expect(setBinding).toHaveBeenCalled());
    fail = true;
    await t.h.refresh();
    expect(t.last()).toMatchObject({ busy: D1, error: expect.stringContaining('board away') });
    await t.h.withdraw(D2);
    expect(withdrawDecision).not.toHaveBeenCalled();
    fail = false;
    done();
    await b;
    expect(t.last()).toMatchObject({ busy: null, notice: { id: D1, ok: true } });
    t.h.dispose();
  });
  it('a board without the list route (404 or 405) says it may predate C17', async () => {
    for (const status of [404, 405]) {
      const t = host({ scopeDecisions: async () => { throw new BoardError('http', 'Method Not Allowed', status); } });
      await t.h.openScope();
      expect(t.last().error).toContain('may predate C17');
      t.h.dispose();
    }
  });
  it('a row opens its source: the message in its thread, a doc in the reader; unknown ids do nothing', async () => {
    const t = host({ scopeDecisions: async () => list([dec(D1, { source: M1, source_kind: 'message', source_ticket: S1 }), dec(D2, { source: DOC, source_kind: 'doc' })]) });
    await t.h.openScope();
    await t.h.openRow(D1);
    expect(t.open.message).toHaveBeenCalledWith(S1, M1);
    await t.h.openRow(D2);
    expect(t.open.doc).toHaveBeenCalledWith(DOC);
    await t.h.openRow(D3);
    expect(t.open.message).toHaveBeenCalledOnce();
  });
});
