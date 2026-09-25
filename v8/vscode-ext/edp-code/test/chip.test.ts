// C4 (s-a34658f02f): the Tag selection route, the composer chip, and the protocol's chip rules.
import { describe, expect, it } from 'vitest';
import { buildAnchor } from '../src/core/anchor';
import { CHIP_ID, parseInbound } from '../src/core/chatProtocol';
import { chipForSend, chipView, newChip, PREVIEW_LINES } from '../src/core/chip';
import { render } from '../src/core/render';
import { tagRoute } from '../src/core/tagRoute';

const lines = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`);
const anchorOf = (startLine: number, endLine: number, dirty = false) => buildAnchor({
  repoRoot: 'c:\\repo', fsPath: 'c:\\repo\\src\\a.py', lines, commit: '0123456789abcdef0123456789abcdef01234567', dirty,
  sel: { startLine, startChar: 0, endLine, endChar: 3, isEmpty: false },
});

describe('tagRoute', () => {
  it('chat view never resolved in this window: the S5 palette chain, whatever else is true', () => {
    expect(tagRoute({ chatResolved: false, threadOpen: false })).toBe('palette');
    expect(tagRoute({ chatResolved: false, threadOpen: true })).toBe('palette');
  });
  it('chat view resolved with a thread open: the chip goes straight into its composer', () => {
    expect(tagRoute({ chatResolved: true, threadOpen: true })).toBe('chip');
  });
  it('chat view resolved but no thread open: the thread picker first, then the chip', () => {
    expect(tagRoute({ chatResolved: true, threadOpen: false })).toBe('pickThenChip');
  });
});

describe('chip', () => {
  it('has a well-formed, fresh id per tag', () => {
    const { anchor } = anchorOf(2, 4);
    const a = newChip(anchor, false), b = newChip(anchor, false);
    expect(a.id).toMatch(CHIP_ID);
    expect(b.id).not.toBe(a.id);
  });

  it('shows the S5 anchor line, the line count and a bounded preview; never the repo root', () => {
    const { anchor, truncated } = anchorOf(0, 9, true);
    const v = chipView(newChip(anchor, truncated));
    expect(v.label).toBe('src/a.py:L1-10 @0123456[dirty]');
    expect(v.lines).toBe(10);
    expect(v.truncated).toBe(false);
    expect(v.preview.split('\n')).toHaveLength(PREVIEW_LINES + 1);
    expect(v.preview).toMatch(/… 4 more lines$/);
    expect(JSON.stringify(v)).not.toContain('repo');
    expect(Object.keys(v).sort()).toEqual(['id', 'label', 'lines', 'preview', 'truncated']);
  });

  it('a short snippet previews whole', () => {
    const { anchor } = anchorOf(2, 3);
    expect(chipView(newChip(anchor, false)).preview).toBe('line 3\nline 4');
  });

  it('the sent text is the note plus the S5 rendered anchor line', () => {
    const { anchor } = anchorOf(2, 4);
    expect(render(anchor, '  why is this here? ', false)).toBe('why is this here?\n\n`src/a.py:L3-5 @0123456`');
  });
});

describe('chipForSend', () => {
  const { anchor } = anchorOf(2, 4);
  const held = newChip(anchor, false);
  it('no chip id: a plain send, even while the host holds a chip (the user removed it)', () => {
    expect(chipForSend(held, undefined)).toEqual({ chip: null });
    expect(chipForSend(undefined, undefined)).toEqual({ chip: null });
  });
  it('the held chip id: sends that anchor', () => {
    expect(chipForSend(held, held.id)).toEqual({ chip: held });
  });
  it('an id the host does not hold (replaced by a newer tag, or dropped) is refused', () => {
    expect(chipForSend(held, 'k-000000000000')).toHaveProperty('error');
    expect(chipForSend(undefined, held.id)).toHaveProperty('error');
  });
});

describe('parseInbound: chip fields', () => {
  const base = { v: 1, type: 'send', ticketId: 's-a34658f02f', text: 'look', kind: 'note' };
  it('send carries a well-formed chipId', () => {
    expect(parseInbound({ ...base, chipId: 'k-0123456789ab' })).toEqual({ ...base, chipId: 'k-0123456789ab' });
  });
  it('a malformed chipId drops the send', () => {
    for (const chipId of ['', 'k-1', 'K-0123456789AB', 'k-0123456789ab/..', 42, null]) expect(parseInbound({ ...base, chipId })).toBeNull();
  });
  it('the view cannot smuggle a code_context or an anchor into a send: extra keys are not copied', () => {
    const m = parseInbound({ ...base, code_context: { repo_root: 'C:\\', path: 'x' }, codeContext: {}, anchor: {} });
    expect(m).toEqual(base);
  });
  it('dropCode needs a ticket id and a chip id', () => {
    expect(parseInbound({ v: 1, type: 'dropCode', ticketId: 's-a34658f02f', chipId: 'k-0123456789ab' }))
      .toEqual({ v: 1, type: 'dropCode', ticketId: 's-a34658f02f', chipId: 'k-0123456789ab' });
    expect(parseInbound({ v: 1, type: 'dropCode', ticketId: 's-a34658f02f' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'dropCode', chipId: 'k-0123456789ab' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'dropCode', ticketId: 'x', chipId: 'k-0123456789ab' })).toBeNull();
  });
});
