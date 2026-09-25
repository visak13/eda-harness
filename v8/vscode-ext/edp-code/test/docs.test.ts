// C16 s-579fa02cca: the Docs tab's rows (core/docs.ts) and its inbound intents.
import { describe, expect, it } from 'vitest';
import { parseInbound } from '../src/core/chatProtocol';
import { canResolve, docsBadge, scopeDocIds, scopeDocs, whyText, type DocMeta, type TicketDocs } from '../src/core/docs';

const EPIC = 'epic-0000000001', S1 = 's-0000000001', S2 = 's-0000000002';
const DESIGN = 'design-aaaaaaaaaa', LL = 'strategyll-bbbbbbbbbb', HL = 'strategyhl-cccccccccc', REP = 'report-dddddddddd', DOM = 'domain-eeeeeeeeee';
const meta = (id: string, doc_type: string, version = 1, status = 'active', title = id): DocMeta => ({ id, doc_type, title, version, status });
const tickets: TicketDocs[] = [
  { id: EPIC, title: 'Epic', design_ref: DESIGN, links: [{ to_id: LL, relation: 'uses_strategy' }, { to_id: 'art-0123456789', relation: 'produced' }], criteria: [] },
  { id: S1, title: 'C16', design_ref: DESIGN, links: [{ to_id: LL, relation: 'uses_strategy' }, { to_id: DOM, relation: 'uses_domain' }, { to_id: S2, relation: 'blocks' }],
    criteria: [{ id: 'c-1', evidence_ref: REP }, { id: 'c-2', evidence_ref: 'https://x' }, { id: 'c-3', evidence_ref: null }] },
  { id: S2, title: 'C17', links: [{ to_id: HL, relation: 'evidence_for' }], criteria: [{ id: 'c-4', evidence_ref: REP }] },
];

describe('scopeDocIds / scopeDocs', () => {
  it('collects design_ref, doc links and criteria evidence; skips artifacts, URLs, blocks links', () => {
    const ids = scopeDocIds(tickets);
    expect([...ids.keys()].sort()).toEqual([DESIGN, DOM, LL, REP, HL].sort());
    expect(ids.get(DESIGN)!.designOf).toBe(EPIC);
    expect(ids.get(REP)!.why.map(w => w.ticketId)).toEqual([S1, S2]);
    expect(ids.get(LL)!.why).toHaveLength(2); // once per ticket, not per link
  });
  it('rows are ordered design, strategy_hl, strategy_ll, domain, report; a doc the board did not describe is left out', () => {
    const m = new Map([meta(DESIGN, 'design', 12, 'proposed', 'The design'), meta(LL, 'strategy_ll', 1), meta(HL, 'strategy_hl', 3, 'proposed'), meta(REP, 'report', 2)].map(x => [x.id, x]));
    const rows = scopeDocs(tickets, m);
    expect(rows.map(r => r.id)).toEqual([DESIGN, HL, LL, REP]);
    expect(rows[0]).toMatchObject({ title: 'The design', docType: 'design', version: 12, status: 'proposed', designOf: EPIC });
  });
  it('a meta with a bad version is dropped, never guessed', () => {
    expect(scopeDocs(tickets, new Map([[DESIGN, meta(DESIGN, 'design', 0)]]))).toEqual([]);
  });
  it('whyText names this scope and other tickets', () => {
    const ids = scopeDocIds(tickets);
    expect(whyText(ids.get(REP)!.why, S1)).toBe('evidence for this scope; evidence for C17');
    expect(whyText(ids.get(DESIGN)!.why, EPIC)).toBe('design of this scope; design of C16');
  });
});

describe('canResolve and the badge', () => {
  it('only a proposed strategy_hl/ll, only for the owner', () => {
    expect(canResolve({ docType: 'strategy_ll', status: 'proposed' }, 'owner')).toBe(true);
    expect(canResolve({ docType: 'strategy_hl', status: 'proposed' }, 'owner')).toBe(true);
    expect(canResolve({ docType: 'strategy_ll', status: 'active' }, 'owner')).toBe(false);
    expect(canResolve({ docType: 'design', status: 'proposed' }, 'owner')).toBe(false);
    expect(canResolve({ docType: 'strategy_ll', status: 'proposed' }, 'engineer')).toBe(false);
  });
  it('counts proposals', () => {
    expect(docsBadge(null)).toBeNull();
    const d = (status: string, docType = 'strategy_ll') => ({ id: LL, title: '', docType, version: 1, status, proposes: null, why: [], designOf: null });
    expect(docsBadge({ scope: EPIC, docs: [d('proposed'), d('active'), d('proposed', 'design')], loading: false, error: null })).toEqual({ text: '1', aria: '1 proposed doc to review' });
  });
});

describe('Docs intents (parseInbound)', () => {
  it('docsOpen / docsCompare take a doc id only; docsRefresh has no fields', () => {
    expect(parseInbound({ v: 1, type: 'docsOpen', id: DESIGN, extra: 'x' })).toEqual({ v: 1, type: 'docsOpen', id: DESIGN });
    expect(parseInbound({ v: 1, type: 'docsCompare', id: LL })).toEqual({ v: 1, type: 'docsCompare', id: LL });
    expect(parseInbound({ v: 1, type: 'docsRefresh' })).toEqual({ v: 1, type: 'docsRefresh' });
    expect(parseInbound({ v: 1, type: 'docsOpen', id: '../etc' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'docsOpen', id: 'Design-aaaaaaaaaa' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'docsOpen' })).toBeNull();
  });
});
