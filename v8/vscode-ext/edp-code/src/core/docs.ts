// The Docs tab's data (C16 s-579fa02cca; design-10b21760d9 §14.2, §14.4): the picked scope's linked docs, each
// with its type, version and status, and why it is in the list. A scope is the C14 ticket set (an epic with every
// ticket of it, a story with its tasks); each ticket contributes its design_ref, its doc links (uses_strategy,
// uses_domain, evidence_for, designed_by) and the docs its criteria cite as evidence. Pure: no vscode import; the
// host reads the board and hands the rows here.
import { DOC_ID } from './docUri';

/** Links that put a doc in a scope's list (produced/blocks/extends are not a ticket's reading). */
export const DOC_RELATIONS = ['designed_by', 'uses_strategy', 'uses_domain', 'evidence_for'] as const;
export type DocRelation = (typeof DOC_RELATIONS)[number];

/** The board's doc summary (`GET /v1/docs` rows, or a full `GET /v1/docs/{id}`), only the fields read here. */
export type DocMeta = { id: string; doc_type: string; title: string; version: number; status: string; proposes?: string | null;
  /** the ticket the doc belongs to (a design: its epic) */
  scope?: string | null };

/** What one scope ticket says about docs. */
export type TicketDocs = {
  id: string; title: string; design_ref?: string | null;
  links: readonly { to_id: string; relation: string }[];
  criteria: readonly { id: string; evidence_ref?: string | null }[];
};

export type DocWhy = { kind: 'design' | 'strategy' | 'domain' | 'evidence'; ticketId: string; ticketTitle: string };
export type DocRow = {
  id: string; title: string; docType: string; version: number; status: string; proposes: string | null;
  why: DocWhy[];
  /** the ticket whose design_ref this doc is (the design gate's source), else null */
  designOf: string | null;
};
/** The Docs tab for one scope. `error`: the list could not be read (the last good rows stay). */
export type DocsState = { scope: string; docs: DocRow[]; loading: boolean; error: string | null };

/** List order: the design first, then the strategy layers, domain, reports, notes, anything else. */
const TYPE_ORDER = ['design', 'strategy_hl', 'strategy_ll', 'domain', 'report', 'note'];
const rank = (t: string) => { const i = TYPE_ORDER.indexOf(t); return i < 0 ? TYPE_ORDER.length : i; };
const WHY_OF: Record<DocRelation, DocWhy['kind']> = { designed_by: 'design', uses_strategy: 'strategy', uses_domain: 'domain', evidence_for: 'evidence' };

/** Every doc id the scope names, each with why; ids that are not doc ids (an artifact, a URL) are skipped. */
export function scopeDocIds(tickets: readonly TicketDocs[]): Map<string, { why: DocWhy[]; designOf: string | null }> {
  const out = new Map<string, { why: DocWhy[]; designOf: string | null }>();
  const add = (docId: string | null | undefined, kind: DocWhy['kind'], t: TicketDocs) => {
    if (typeof docId !== 'string' || !DOC_ID.test(docId)) return;
    let e = out.get(docId);
    if (!e) out.set(docId, (e = { why: [], designOf: null }));
    if (kind === 'design' && t.design_ref === docId && !e.designOf) e.designOf = t.id;
    if (!e.why.some(w => w.kind === kind && w.ticketId === t.id)) e.why.push({ kind, ticketId: t.id, ticketTitle: t.title });
  };
  for (const t of tickets) {
    add(t.design_ref, 'design', t);
    for (const l of t.links ?? []) if ((DOC_RELATIONS as readonly string[]).includes(l.relation)) add(l.to_id, WHY_OF[l.relation as DocRelation], t);
    for (const c of t.criteria ?? []) add(c.evidence_ref, 'evidence', t);
  }
  return out;
}

/** The rows: every named doc the board described, ordered by type then title. A named doc with no meta (not
 *  readable) is left out rather than guessed. */
export function scopeDocs(tickets: readonly TicketDocs[], meta: ReadonlyMap<string, DocMeta>): DocRow[] {
  const rows: DocRow[] = [];
  for (const [id, e] of scopeDocIds(tickets)) {
    const m = meta.get(id);
    if (!m || !Number.isSafeInteger(m.version) || m.version < 1) continue;
    rows.push({ id, title: String(m.title ?? id), docType: String(m.doc_type ?? 'doc'), version: m.version, status: String(m.status ?? ''),
      proposes: typeof m.proposes === 'string' ? m.proposes : null, why: e.why, designOf: e.designOf });
  }
  return rows.sort((a, b) => rank(a.docType) - rank(b.docType) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
}

/** "design of C16 …", "evidence for C15 …; strategy of the epic" */
export function whyText(why: readonly DocWhy[], scopeId: string): string {
  const word = { design: 'design of', strategy: 'strategy for', domain: 'domain for', evidence: 'evidence for' } as const;
  return why.map(w => `${word[w.kind]} ${w.ticketId === scopeId ? 'this scope' : w.ticketTitle}`).join('; ');
}

/** A proposed knowledge doc the owner rules on in the reader (design §14.2): strategy_hl/ll only. */
export const RESOLVABLE = new Set(['strategy_hl', 'strategy_ll']);
export const canResolve = (d: { docType: string; status: string }, role: string | null | undefined) =>
  RESOLVABLE.has(d.docType) && d.status === 'proposed' && role === 'owner';

export function docsBadge(d: DocsState | null | undefined): { text: string; aria: string } | null {
  // the badge counts what the owner rules on in the reader: proposed strategy docs (a design's review is an Inbox gate)
  const n = d?.docs.filter(x => x.status === 'proposed' && RESOLVABLE.has(x.docType)).length ?? 0;
  return n ? { text: String(n), aria: `${n} proposed doc${n === 1 ? '' : 's'} to review` } : null;
}
