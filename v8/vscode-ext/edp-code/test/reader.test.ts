// C16 s-579fa02cca: the reader's inbound gate and the writes it builds from the host's panel state.
import { describe, expect, it } from 'vitest';
import { approveReason, compareChoices, decideBody, decideProblem, diffPair, parseReaderInbound, readerComments, SELECTION_MAX, SIGNOFF_TIP, type ReaderDoc, type ReaderGate } from '../src/core/reader';

const doc: ReaderDoc = { id: 'design-aaaaaaaaaa', title: 'D', docType: 'design', status: 'proposed', version: 12, versions: [1, 11, 12], current: 12, body: '# D', proposes: null, resolution: null };
const gate: ReaderGate = { ticketId: 'epic-0000000001', ticketTitle: 'E', gateEventId: 'ev-1', canApprove: true, canReview: true, currentVersion: 12 };

describe('parseReaderInbound', () => {
  it('known types only, v:1 only', () => {
    for (const t of ['ready', 'compare', 'source', 'fullScreen', 'refresh', 'approve', 'openProposalDiff']) expect(parseReaderInbound({ v: 1, type: t, x: 1 })).toEqual({ v: 1, type: t });
    expect(parseReaderInbound({ v: 2, type: 'ready' })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'fetch' })).toBeNull();
    expect(parseReaderInbound(null)).toBeNull();
  });
  it('pickVersion needs a positive integer', () => {
    expect(parseReaderInbound({ v: 1, type: 'pickVersion', version: 11 })).toEqual({ v: 1, type: 'pickVersion', version: 11 });
    for (const version of [0, -1, 1.5, '11', null]) expect(parseReaderInbound({ v: 1, type: 'pickVersion', version })).toBeNull();
  });
  it('requestChanges needs non-blank feedback within the cap; resolve needs a boolean', () => {
    expect(parseReaderInbound({ v: 1, type: 'requestChanges', feedback: 'fix §3' })).toEqual({ v: 1, type: 'requestChanges', feedback: 'fix §3' });
    expect(parseReaderInbound({ v: 1, type: 'requestChanges', feedback: '  ' })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'requestChanges', feedback: 'x'.repeat(16_385) })).toBeNull();
    expect(parseReaderInbound({ v: 1, type: 'resolve', approve: false })).toEqual({ v: 1, type: 'resolve', approve: false });
    expect(parseReaderInbound({ v: 1, type: 'resolve', approve: 'yes' })).toBeNull();
  });
  it('openLink: http(s) only', () => {
    expect(parseReaderInbound({ v: 1, type: 'openLink', href: 'https://example.com/a' })).toEqual({ v: 1, type: 'openLink', href: 'https://example.com/a' });
    for (const href of ['javascript:alert(1)', 'command:workbench.action.quit', 'file:///c:/x', 'not a url']) expect(parseReaderInbound({ v: 1, type: 'openLink', href })).toBeNull();
  });
  it('selection: 1-based inclusive lines, from 0 clears, text capped', () => {
    expect(parseReaderInbound({ v: 1, type: 'selection', from: 3, to: 5, text: 'abc' })).toEqual({ v: 1, type: 'selection', from: 3, to: 5, text: 'abc' });
    expect(parseReaderInbound({ v: 1, type: 'selection', from: 0, to: 9, text: 'x' })).toEqual({ v: 1, type: 'selection', from: 0, to: 0, text: '' });
    expect(parseReaderInbound({ v: 1, type: 'selection', from: 5, to: 3, text: '' })).toBeNull();
    expect((parseReaderInbound({ v: 1, type: 'selection', from: 1, to: 1, text: 'y'.repeat(9000) }) as { text: string }).text).toHaveLength(SELECTION_MAX);
  });
});

describe('the design decision', () => {
  it('reviewed_version is the version shown; approve sends no feedback', () => {
    expect(decideBody(doc, gate, 'approve', 'ignored', 'k1')).toEqual({ ticket_id: gate.ticketId, gate_event_id: 'ev-1', decision: 'approve',
      design_ref: doc.id, reviewed_version: 12, feedback: '', idempotency_key: 'k1' });
    expect(decideBody({ ...doc, version: 11 }, gate, 'request_changes', 'fix', 'k2')).toMatchObject({ reviewed_version: 11, feedback: 'fix', decision: 'request_changes' });
  });
  it('problems: no gate, closed gate, an older version, blank feedback', () => {
    expect(decideProblem(doc, null, 'approve', '')).toMatch(/no design review/);
    expect(decideProblem(doc, { ...gate, canApprove: false, gateEventId: null }, 'approve', '')).toMatch(/not open/);
    expect(decideProblem({ ...doc, version: 11 }, { ...gate, canApprove: false }, 'approve', '')).toBe('You are reading v11; the design is now v12. Open v12 to review it.');
    expect(decideProblem(doc, gate, 'request_changes', ' ')).toMatch(/needs feedback/);
    expect(decideProblem(doc, gate, 'approve', '')).toBeNull();
    expect(decideProblem(doc, gate, 'request_changes', 'fix §2')).toBeNull();
  });
});

describe('compare and comments', () => {
  it('compareChoices: every other version, newest first; diffPair puts the older left', () => {
    expect(compareChoices([1, 11, 12], 12)).toEqual([11, 1]);
    expect(compareChoices([3], 3)).toEqual([]);
    expect(diffPair(12, 11)).toEqual([11, 12]);
    expect(diffPair(2, 9)).toEqual([2, 9]);
  });
  it('readerComments shapes the board rows and skips malformed ones', () => {
    const rows = readerComments([
      { id: 'm-1', created_by: 'owner', created_at: '2026-09-25T10:00:00Z', kind: 'note', text: '[design v12] tighten §3', via: 'review', document_context: { design_ref: doc.id, reviewed_version: 12 } },
      { id: 'm-2', created_by: 'arch', kind: 'answer', text: 'quoted', via: 'quote' },
      { nope: true }, null,
    ]);
    expect(rows).toEqual([
      { id: 'm-1', by: 'owner', at: '2026-09-25T10:00:00Z', kind: 'note', text: '[design v12] tighten §3', via: 'review', version: 12 },
      { id: 'm-2', by: 'arch', at: null, kind: 'answer', text: 'quoted', via: 'quote', version: null },
    ]);
    expect(readerComments({})).toEqual([]);
  });
});

// C22 s-3b86872bf0: a design with no Approve says why in its header
describe('approveReason', () => {
  const at = (v: number): ReaderDoc => ({ ...doc, version: v });
  it('no reason when it is not a design, or when the owner can approve (the actions show as before)', () => {
    expect(approveReason({ ...doc, docType: 'strategy_ll' }, null)).toBeNull();
    expect(approveReason(null, gate)).toBeNull();
    expect(approveReason(doc, gate)).toBeNull();
  });
  it('(a) no sign-off open: says so for the version shown, with the ticket when known', () => {
    expect(approveReason(doc, null)).toEqual({ text: 'No sign-off open on v12', openVersion: null, ticketId: null });
    expect(approveReason(doc, { ...gate, gateEventId: null, canApprove: false }))
      .toEqual({ text: 'No sign-off open on v12 (epic-0000000001)', openVersion: null, ticketId: 'epic-0000000001' });
    expect(approveReason(at(11), { ...gate, gateEventId: null, canApprove: false })?.text).toBe('No sign-off open on v11 (epic-0000000001)');
  });
  it('(b) sign-off open on a newer version: names it and offers to open it', () =>
    expect(approveReason(at(11), { ...gate, canApprove: false }))
      .toEqual({ text: 'Sign-off is open on v12 (epic-0000000001)', openVersion: 12, ticketId: 'epic-0000000001' }));
  it('open on this version but the viewer is not the owner', () =>
    expect(approveReason(doc, { ...gate, canApprove: false, canReview: false })?.text)
      .toBe("Sign-off is open on v12 (epic-0000000001); only the epic's owner approves it"));
  it('open on this version for the owner, yet not approvable (the ticket designs another doc)', () =>
    expect(approveReason(doc, { ...gate, canApprove: false })?.text).toBe('Sign-off open (epic-0000000001) is not for this design'));
  it('the tooltip says a design has no Reject', () => expect(SIGNOFF_TIP).toMatch(/no Reject: Request changes/));
});
