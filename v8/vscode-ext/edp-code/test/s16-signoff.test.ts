// S16 s-ca39f10643 (owner art-1e28857706): an epic's design opened from any scope ticket (the epic, or a story sharing
// its design_ref) resolves the review to the ticket that holds the open design_signoff, so Approve / Request changes
// show and an approval lands on the epic; a refusal from /v1/gates/decide is shown in the reader.
import { expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ warnings: [] as string[] }));
vi.mock('vscode', () => ({
  window: { showWarningMessage: (t: string) => { h.warnings.push(t); }, showErrorMessage: (t: string) => { h.warnings.push(t); } },
  commands: { executeCommand: async () => undefined },
}));

import { BoardError, type DocContext } from '../src/core/api';
import { approveReason, pickReviewContext, reviewSources, type ReaderDoc } from '../src/core/reader';
import { DocReader } from '../src/vscode/reader';

const EPIC = 'epic-7f3d64e6de', S1 = 's-ec73f74ea9', DESIGN = 'design-e963c656f5';
const doc: ReaderDoc = { id: DESIGN, title: 'D', docType: 'design', status: 'active', version: 12, versions: [11, 12], current: 12, body: '# D', proposes: null, resolution: null };
const ctx = (ticket: string, gate: string | null): DocContext => ({ ticket_id: ticket, source_title: ticket, design_ref: DESIGN, reviewed_version: 12,
  current_version: 12, gate_event_id: gate, can_approve: !!gate, can_review: true });

it('S16: a story source is also asked on its epic; an epic or a quick task is asked on itself only', () => {
  expect(reviewSources(S1, { epic_id: EPIC, parent_id: EPIC })).toEqual([S1, EPIC]);
  expect(reviewSources(EPIC, { epic_id: EPIC, parent_id: null })).toEqual([EPIC]);
  expect(reviewSources('s-quick00001', { epic_id: 's-quick00001', parent_id: null })).toEqual(['s-quick00001']);
  expect(reviewSources(S1, undefined)).toEqual([S1]); // the ticket could not be read: the source alone
});

it('S16: the context holding the open sign-off wins; else the first one read', () => {
  expect(pickReviewContext([ctx(S1, null), ctx(EPIC, 'ev-1')])?.ticket_id).toBe(EPIC);
  expect(pickReviewContext([ctx(S1, null), ctx(EPIC, null)])?.ticket_id).toBe(S1);
  expect(pickReviewContext([null, ctx(EPIC, 'ev-1')])?.ticket_id).toBe(EPIC);
  expect(pickReviewContext([])).toBeNull();
});

function reader(board: Record<string, unknown>, source: string) {
  const p: any = { id: DESIGN, version: 12, source, posts: [] as any[], next: () => 1, current: () => true, panel: { title: '' }, state: {} };
  p.post = (m: unknown) => p.posts.push(m);
  const r: any = Object.assign(Object.create(DocReader.prototype), { viewer: 0, panels: new Set([p]), active: null, sources: new Map(), reveals: new Map(),
    board: () => board, onAuthFail: vi.fn(), log() {}, postReveal() {}, set: (pp: any, s: any) => { pp.state = { ...pp.state, ...s }; } });
  return { r, p };
}

function epicBoard(decide: (b: any) => Promise<unknown>) {
  const tickets: Record<string, any> = { [S1]: { id: S1, epic_id: EPIC, parent_id: EPIC, design_ref: DESIGN }, [EPIC]: { id: EPIC, epic_id: EPIC, parent_id: null, design_ref: DESIGN } };
  return {
    ticket: vi.fn(async (id: string) => tickets[id]),
    // the gate is open on the epic only (the board's /v1/docs/{id}/context per source ticket)
    docContext: vi.fn(async (_d: string, source: string) => ctx(source, source === EPIC ? 'ev-signoff' : null)),
    decide: vi.fn(decide),
  };
}

it('S16: opened from S1 (the Docs tab\'s first design_ref holder), the review resolves to the epic and Approve lands there', async () => {
  const board = epicBoard(async () => ({ decision: 'approve' }));
  const { r, p } = reader(board, S1);
  const { gate, error } = await r.gateOf(p, doc, EPIC);
  expect(error).toBeNull();
  expect(gate).toMatchObject({ ticketId: EPIC, gateEventId: 'ev-signoff', canApprove: true, designRef: DESIGN });
  expect(approveReason(doc, gate)).toBeNull(); // no "No sign-off open on v12 (s-ec73f74ea9)": Approve / Request changes show
  p.state = { doc, gate };
  r.load = vi.fn(async () => {});
  await r.approve(p);
  expect(board.decide).toHaveBeenCalledOnce();
  expect(board.decide.mock.calls[0][0]).toMatchObject({ ticket_id: EPIC, gate_event_id: 'ev-signoff', decision: 'approve', design_ref: DESIGN, reviewed_version: 12 });
  expect(p.posts.filter((m: any) => m.type === 'done')).toEqual([{ type: 'done', v: 1, what: 'approve', ok: true, text: `Approved ${DESIGN} v12.` }]);
});

it('S16: opened from the epic itself, it resolves to the epic without asking any story', async () => {
  const board = epicBoard(async () => ({}));
  const { r, p } = reader(board, EPIC);
  const { gate } = await r.gateOf(p, doc, EPIC);
  expect(gate).toMatchObject({ ticketId: EPIC, gateEventId: 'ev-signoff', canApprove: true });
  expect(board.docContext.mock.calls.map(c => c[1])).toEqual([EPIC]);
});

it('S16: with no sign-off open anywhere, the header still names the source (no guess)', async () => {
  const board = { ...epicBoard(async () => ({})), docContext: vi.fn(async (_d: string, source: string) => ctx(source, null)) };
  const { r, p } = reader(board, S1);
  const { gate } = await r.gateOf(p, doc, EPIC);
  expect(gate).toMatchObject({ ticketId: S1, gateEventId: null });
  expect(approveReason(doc, gate)?.text).toBe(`No sign-off open on v12 (${S1})`);
});

it('S16: a refusal from /v1/gates/decide is shown in the reader, verbatim', async () => {
  h.warnings = [];
  const refusal = 'epic epic-7f3d64e6de is not ready for design sign-off: it has no acceptance criteria';
  const board = epicBoard(async () => { throw new BoardError('transition', refusal, 409); });
  const { r, p } = reader(board, S1);
  p.state = { doc, gate: (await r.gateOf(p, doc, EPIC)).gate };
  r.load = vi.fn(async () => {});
  await r.approve(p);
  expect(p.posts.filter((m: any) => m.type === 'done')).toEqual([{ type: 'done', v: 1, what: 'approve', ok: false, text: refusal }]);
  expect(h.warnings).toHaveLength(1);
  expect(h.warnings[0]).toContain(refusal);
  expect(r.onAuthFail).not.toHaveBeenCalled();
});
