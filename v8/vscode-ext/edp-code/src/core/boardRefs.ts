// C24 (s-5d1b171d57, owner m-0f727b0c57 'why cant we use $ for board objects?'): `$` references board objects,
// `@` people and `#` files. The same rules as the SPA's web/src/components/boardRefs.ts, tested against the one
// fixture tests/fixtures/ref_cases.json both read (trigger: `$` at a word start + a letter, never `$5` or
// `$env:X`, never in code; rows: this epic's tree first, then the board's open items; insert `$<id> (<label>) `;
// render `$<id>` outside code as a chip). Pure: no vscode import.
import { stripCode } from './mentions';
export type RefKind = 'epic' | 'story' | 'task' | 'design' | 'strategy_hl' | 'strategy_ll' | 'report' | 'decision';

export interface RefRow {
  id: string;
  kind: RefKind;
  title: string;
  /** 'scope' = this epic's tree, 'board' = the board's other open items */
  group: 'scope' | 'board';
}

const PREFIX: [string, RefKind][] = [
  ['epic-', 'epic'], ['s-', 'story'], ['t-', 'task'], ['design-', 'design'], ['strategyhl-', 'strategy_hl'],
  ['strategyll-', 'strategy_ll'], ['report-', 'report'], ['dec-', 'decision'],
];

/** A referenceable board id: one of the eight prefixes plus the board's 10 hex digits. */
export const REF_ID = /^(?:epic|s|t|design|strategyhl|strategyll|report|dec)-[0-9a-f]{10}$/;

/** The kind an id names, from its prefix (null: not a referenceable id). */
export function refKind(id: string): RefKind | null {
  if (!REF_ID.test(id)) return null;
  return PREFIX.find(([p]) => id.startsWith(p))?.[1] ?? null;
}

/** Short kind label for a picker row / chip. */
export function kindLabel(k: RefKind): string {
  return { epic: 'epic', story: 'story', task: 'task', design: 'design', strategy_hl: 'hl', strategy_ll: 'll', report: 'report', decision: 'decision' }[k];
}

/** The `$` token under the caret, or null. `start` is the offset of the `$`, `query` what follows it. */
export function activeRef(text: string, caret: number): { start: number; query: string } | null {
  const left = stripCode(text).slice(0, caret);
  const m = /(^|[\s(["'])\$([A-Za-z][\w-]*)$/.exec(left);
  if (!m) return null;
  // `$env:X` — the word is followed by a ':' (the caret sits after it, or the text right of it has one)
  if (text.charAt(caret) === ':') return null;
  return { start: caret - m[2].length - 1, query: m[2] };
}

function score(q: string, r: RefRow): number {
  const id = r.id.toLowerCase();
  const title = r.title.toLowerCase();
  if (id.startsWith(q)) return 0;
  if (title.startsWith(q)) return 1;
  if (new RegExp(`(^|[^a-z0-9])${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(title)) return 2;
  if (title.includes(q) || id.includes(q)) return 3;
  return -1;
}

/** The picker rows for `query`: scope rows first, then the board's; inside a group the best match
 *  first (id prefix, title start, title word start, substring), board rows already in scope dropped. */
export function rankRefs(query: string, scope: RefRow[], board: RefRow[], cap = 12): RefRow[] {
  const q = query.toLowerCase();
  const seen = new Set<string>();
  const out: RefRow[] = [];
  for (const [group, rows] of [['scope', scope], ['board', board]] as const) {
    const hits: { r: RefRow; s: number; i: number }[] = [];
    rows.forEach((r, i) => {
      if (seen.has(r.id)) return;
      const s = score(q, r);
      if (s >= 0) { hits.push({ r: { ...r, group }, s, i }); seen.add(r.id); }
    });
    hits.sort((a, b) => a.s - b.s || a.i - b.i);
    out.push(...hits.map((h) => h.r));
  }
  return out.slice(0, cap);
}

/** The label that rides in the text after the id: one line, no parens (they delimit it), `@` neutralised
 *  so a title never mentions anyone, at most 60 characters. */
export function refLabel(title: string): string {
  const one = title.replace(/[()]/g, '').replace(/@/g, '＠').replace(/\s+/g, ' ').trim();
  return one.length > 60 ? `${one.slice(0, 59).trimEnd()}…` : one;
}

/** What the picker inserts for a row. */
export function refToken(r: Pick<RefRow, 'id' | 'title'>): string {
  const label = refLabel(r.title);
  return label ? `$${r.id} (${label}) ` : `$${r.id} `;
}

export type RefPart = string | { id: string; kind: RefKind; label: string | null };

const REF_IN_TEXT = /(^|[^\w$])\$((?:epic|s|t|design|strategyhl|strategyll|report|dec)-[0-9a-f]{10})(?![\w-])(?: \(([^()\n]{1,80})\))?/g;

/** Split plain text (no code in it) into text and `$<id>` references (with their ` (label)`). */
export function splitRefs(text: string): RefPart[] {
  const out: RefPart[] = [];
  let at = 0;
  REF_IN_TEXT.lastIndex = 0;
  for (let m = REF_IN_TEXT.exec(text); m; m = REF_IN_TEXT.exec(text)) {
    const start = m.index + m[1].length;
    if (start > at) out.push(text.slice(at, start));
    out.push({ id: m[2], kind: refKind(m[2])!, label: m[3] ?? null });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

/** The ids a text references, code excluded, deduplicated, in order. */
export function refIds(text: string): string[] {
  const ids: string[] = [];
  for (const p of splitRefs(stripCode(text))) if (typeof p !== 'string' && !ids.includes(p.id)) ids.push(p.id);
  return ids;
}

const OPEN = new Set(['drafted', 'designed', 'signed_off', 'ready', 'in_progress', 'in_review', 'blocked']);
const DOC_KINDS = new Set<RefKind>(['design', 'strategy_hl', 'strategy_ll', 'report']);

/** Rows from the scope reads: the epic's tickets, its docs and its decisions (live only). */
export function scopeRows(
  tickets: { id: string; title: string }[],
  docs: { id: string; title: string; doc_type?: string }[],
  decisions: { id: string; text: string; status?: string }[],
): RefRow[] {
  const out: RefRow[] = [];
  for (const t of tickets) { const k = refKind(t.id); if (k) out.push({ id: t.id, kind: k, title: t.title, group: 'scope' }); }
  for (const d of docs) { const k = refKind(d.id); if (k && DOC_KINDS.has(k)) out.push({ id: d.id, kind: k, title: d.title, group: 'scope' }); }
  for (const d of decisions) if ((d.status ?? 'live') === 'live' && refKind(d.id)) out.push({ id: d.id, kind: 'decision', title: d.text, group: 'scope' });
  return out;
}

/** Rows from `/v1/find` hits and open epics: open tickets, the four doc kinds, decisions. */
export function boardRows(
  hits: { type: string; id: string; title?: string; status?: string; snippet?: string }[],
  epics: { id: string; title: string; status?: string }[] = [],
): RefRow[] {
  const out: RefRow[] = [];
  for (const e of epics) if (!e.status || OPEN.has(e.status)) out.push({ id: e.id, kind: 'epic', title: e.title, group: 'board' });
  for (const h of hits) {
    const k = refKind(h.id);
    if (!k) continue;
    if (h.type === 'ticket' && h.status && !OPEN.has(h.status)) continue;
    const title = h.title ?? (h.snippet ?? '').replace(/[[\]]/g, '');
    out.push({ id: h.id, kind: k, title, group: 'board' });
  }
  return out;
}

/** The host's answer rows are data from the board: keep only well-formed ones, cut long titles. */
export function cleanRows(raw: unknown): RefRow[] {
  if (!Array.isArray(raw)) return [];
  const out: RefRow[] = [];
  for (const r of raw.slice(0, 50)) {
    if (!r || typeof r !== 'object') continue;
    const { id, title, group } = r as Record<string, unknown>;
    const kind = typeof id === 'string' ? refKind(id) : null;
    if (!kind || typeof title !== 'string' || (group !== 'scope' && group !== 'board')) continue;
    out.push({ id: id as string, kind, title: title.slice(0, 300), group });
  }
  return out;
}
