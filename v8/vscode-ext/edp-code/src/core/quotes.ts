// C20 s-29f052c40e (design-10b21760d9 v12 §14.5, §14.7): quote + note from code, a board doc (the EDP reader, its
// markdown source or a version diff) and a chat message, collected per thread as a draft and sent as ONE message's
// ordered `quotes[]` (C18, edp8/quotes.py). The host builds every quote here from what it read itself (the document,
// the doc version, the message in its store); the view names a draft only by key, so a quote the host did not build
// never reaches the board. The board verifies each one and answers a 422 naming `quotes[i]`. Pure: no vscode import.
import { randomBytes } from 'node:crypto';
import { truncateUtf8, type Anchor } from './anchor';
import { MESSAGE_ID, QUOTE_KEY, TICKET_ID, type QuoteChip } from './chatProtocol';
import { DOC_ID } from './docUri';
import { contextOf, displayPassage, linesOf, locateInSource } from './quoteMatch';
import { docLabel, headingAt } from './quoteLabel';
import { at } from './render';

/** the board's caps (edp8/quotes.py): quotes per message, passage bytes, note characters */
export const QUOTES_MAX = 20;
export const PASSAGE_MAX_B = 4096;
export const NOTE_MAX = 2000;
/** a chip shows at most this much of its passage (the web's 160) */
export const CHIP_TEXT_MAX = 160;

/** One quote as `POST /v1/messages` takes it (C18 `QuoteIn`). */
export type QuoteIn = {
  source: 'doc' | 'message' | 'code';
  id?: string; version?: number;
  locator?: { line_start?: number; line_end?: number; char_start?: number; char_end?: number };
  text?: string;
  context?: { before: string; after: string };
  note?: string;
  code?: Anchor;
};

/** Where a draft's inline marker lives: a text document (a code file, a doc's markdown source or a diff side) and
 *  its 1-based inclusive lines. Null: the draft came from the reader or a chat message (their own views mark it). */
export type DraftWhere = { uri: string; line_start: number; line_end: number } | null;

/** One draft in a thread's tray: the quote the host built, the label its chip shows, where its marker is. */
export type Draft = { key: string; quote: QuoteIn; label: string; where: DraftWhere };

export const newKey = () => `q-${randomBytes(6).toString('hex')}`;

const cleanNote = (note: string | undefined) => {
  const n = (note ?? '').slice(0, NOTE_MAX);
  return n.trim() ? n : undefined;
};

/** A passage over the board's byte cap is cut on a code point: a prefix of the passage still occurs in its source
 *  (whitespace-normalised), so the board still verifies it. */
const capped = (text: string) => truncateUtf8(text, PASSAGE_MAX_B).text;

// -- builders -------------------------------------------------------------------------------------------
/** A code quote: the S5 anchor (repo-relative path, commit, dirty, snippet capped at 4096 B, its sha). */
export function codeDraft(anchor: Anchor, note: string | undefined, where: DraftWhere): Draft {
  return { key: newKey(), quote: { source: 'code', code: anchor, note: cleanNote(note) }, label: at(anchor), where };
}

/** A doc quote from lines of that version's markdown SOURCE (a text editor on `edp-doc:`, or a diff side): the
 *  selected text is already verbatim source. `selected` empty: the whole lines. */
export function docSourceDraft(i: { id: string; version: number; body: string; line_start: number; line_end: number; selected: string; note?: string; where: DraftWhere }): Draft | { error: string } {
  if (!DOC_ID.test(i.id) || !Number.isSafeInteger(i.version) || i.version < 1) return { error: 'Not a board doc version.' };
  const lines = i.body.replace(/\r\n/g, '\n').split('\n');
  if (i.line_start < 1 || i.line_end < i.line_start || i.line_end > lines.length) return { error: `Lines ${i.line_start}-${i.line_end} are outside ${i.id} v${i.version}.` };
  const region = lines.slice(i.line_start - 1, i.line_end).join('\n');
  const text = capped(i.selected.trim() ? i.selected : region);
  if (!text.trim()) return { error: 'Select some text to quote (the lines are blank).' };
  return docDraft(i.id, i.version, lines, i.line_start, i.line_end, text, i.note, i.where);
}

/** A doc quote from the READER: `from`..`to` are the source lines of the blocks the selection touched (the reader's
 *  data-ls/data-le stamps) and `selected` is the rendered text. It is mapped back to the verbatim markdown inside
 *  those lines (`before`: the rendered text of the same blocks before the selection, to pick a repeated passage);
 *  when it cannot be mapped the whole lines are quoted. */
export function docReaderDraft(i: { id: string; version: number; body: string; from: number; to: number; selected: string; before?: string; note?: string }): Draft | { error: string } {
  if (!DOC_ID.test(i.id) || !Number.isSafeInteger(i.version) || i.version < 1) return { error: 'Not a board doc version.' };
  const lines = i.body.replace(/\r\n/g, '\n').split('\n');
  if (i.from < 1 || i.to < i.from || i.to > lines.length) return { error: `Lines ${i.from}-${i.to} are outside ${i.id} v${i.version}.` };
  const region = lines.slice(i.from - 1, i.to).join('\n');
  const span = i.selected.trim() ? locateInSource(region, i.selected, i.before ?? '') : null;
  let a = i.from, b = i.to, text = region;
  if (span) {
    const l = linesOf(region, span);
    a = i.from + l.line_start - 1;
    b = i.from + l.line_end - 1;
    text = span.text;
  }
  text = capped(text);
  if (!text.trim()) return { error: 'Select some text to quote.' };
  return docDraft(i.id, i.version, lines, a, b, text, i.note, null);
}

function docDraft(id: string, version: number, lines: string[], a: number, b: number, text: string, note: string | undefined, where: DraftWhere): Draft {
  const body = lines.join('\n');
  const ctx = contextOf(body, a, b);
  const quote: QuoteIn = { source: 'doc', id, version, locator: { line_start: a, line_end: b }, text, note: cleanNote(note) };
  if (ctx.before || ctx.after) quote.context = ctx;
  return { key: newKey(), quote, label: docLabel(id, version, headingAt(lines, a), a, b), where };
}

/** Code points in `s[0:i)` (UTF-16 index -> the board's Python str index). */
export const codePoints = (s: string, i: number) => Array.from(s.slice(0, i)).length;

/** A message quote: the rendered selection mapped back to the verbatim markdown of the message the host holds,
 *  located by a character range in CODE POINTS (the board slices its Python str). */
export function messageDraft(m: { id: string; text: string; created_by: string }, selected: string, before: string, note?: string): Draft | { error: string } {
  if (!MESSAGE_ID.test(m.id)) return { error: 'Not a board message.' };
  const span = locateInSource(m.text, selected, before);
  if (!span) return { error: 'Could not find that passage in the message; select it again.' };
  const text = capped(span.text);
  const end = span.start + text.length;
  return {
    key: newKey(), where: null, label: `${m.id} (${m.created_by})`,
    quote: { source: 'message', id: m.id, locator: { char_start: codePoints(m.text, span.start), char_end: codePoints(m.text, end) }, text, note: cleanNote(note) },
  };
}

// -- the chip the view shows ----------------------------------------------------------------------------
export function passageOf(q: QuoteIn): string {
  return q.source === 'code' ? q.code?.snippet ?? '' : q.text ?? '';
}

export function clip(s: string, n: number): string {
  const cps = Array.from(s.replace(/\s+/g, ' ').trim());
  return cps.length > n ? cps.slice(0, n - 1).join('') + '…' : cps.join('');
}

export function chipOf(d: Draft, invalid: string | null = null): QuoteChip {
  const q = d.quote;
  return { key: d.key, source: q.source, label: d.label, passage: clip(q.source === 'code' ? passageOf(q) : displayPassage(passageOf(q)), CHIP_TEXT_MAX),
    note: q.note ?? '', ...(invalid === d.key ? { invalid: true } : {}) };
}

// -- the tray: per thread, ordered ----------------------------------------------------------------------
export type TrayData = Record<string, Draft[]>;

export class Tray {
  private by = new Map<string, Draft[]>();

  constructor(data: TrayData = {}) { for (const [k, v] of Object.entries(data)) if (v.length) this.by.set(k, v); }

  list(ticketId: string | null | undefined): Draft[] { return (ticketId && this.by.get(ticketId)) || []; }
  all(): Draft[] { return [...this.by.values()].flat(); }
  threads(): string[] { return [...this.by.keys()]; }
  find(key: string): { ticketId: string; draft: Draft } | null {
    for (const [t, ds] of this.by) { const d = ds.find(x => x.key === key); if (d) return { ticketId: t, draft: d }; }
    return null;
  }

  /** Adds to the end; false when the thread already holds the board's maximum. */
  add(ticketId: string, d: Draft): boolean {
    const ds = this.list(ticketId);
    if (ds.length >= QUOTES_MAX) return false;
    this.by.set(ticketId, [...ds, d]);
    return true;
  }

  drop(ticketId: string, key: string): boolean {
    const ds = this.list(ticketId);
    const next = ds.filter(d => d.key !== key);
    this.set(ticketId, next);
    return next.length !== ds.length;
  }

  move(ticketId: string, key: string, by: -1 | 1): boolean {
    const ds = [...this.list(ticketId)];
    const i = ds.findIndex(d => d.key === key), j = i + by;
    if (i < 0 || j < 0 || j >= ds.length) return false;
    [ds[i], ds[j]] = [ds[j], ds[i]];
    this.set(ticketId, ds);
    return true;
  }

  note(ticketId: string, key: string, note: string): boolean {
    const ds = this.list(ticketId);
    if (!ds.some(d => d.key === key)) return false;
    this.set(ticketId, ds.map(d => (d.key === key ? { ...d, quote: { ...d.quote, note: cleanNote(note) } } : d)));
    return true;
  }

  /** A send went: drop the drafts it carried (ones added meanwhile stay). */
  sent(ticketId: string, keys: readonly string[]): Draft[] {
    const gone = this.list(ticketId).filter(d => keys.includes(d.key));
    this.set(ticketId, this.list(ticketId).filter(d => !keys.includes(d.key)));
    return gone;
  }

  clear(): Draft[] { const all = this.all(); this.by.clear(); return all; }

  data(): TrayData { return Object.fromEntries(this.by); }

  private set(ticketId: string, ds: Draft[]) { if (ds.length) this.by.set(ticketId, ds); else this.by.delete(ticketId); }
}

/** The quotes a send names, in the order it names them: every key must be a draft of that thread. */
export function quotesForSend(held: readonly Draft[], keys: readonly string[]): { quotes: QuoteIn[]; keys: string[] } | { error: string } {
  if (new Set(keys).size !== keys.length) return { error: 'Not sent: a quote is listed twice.' };
  const out: QuoteIn[] = [];
  for (const k of keys) {
    const d = held.find(x => x.key === k);
    if (!d) return { error: 'Not sent: the quotes changed; check them and send again.' };
    out.push(d.quote);
  }
  return { quotes: out, keys: [...keys] };
}

/** The board names a refused quote `quotes[i]: …`: the key of that quote, or null. */
export function refusedKey(message: string | undefined, keys: readonly string[]): string | null {
  const m = /^quotes\[(\d+)\]/.exec(message ?? '');
  return m ? keys[Number(m[1])] ?? null : null;
}

// -- restore (workspaceState is untrusted: an older build's shape, or nothing) ----------------------------
const isInt = (x: unknown, min = 1) => typeof x === 'number' && Number.isSafeInteger(x) && x >= min;
const str = (x: unknown, max: number) => typeof x === 'string' && x.length <= max;

function validAnchor(a: unknown): a is Anchor {
  if (!a || typeof a !== 'object') return false;
  const c = a as Record<string, unknown>;
  return str(c.repo_root, 1024) && str(c.path, 1024) && isInt(c.line_start) && isInt(c.line_end) && (c.commit === null || str(c.commit, 64))
    && typeof c.dirty === 'boolean' && str(c.snippet, 8192) && str(c.snippet_sha, 64);
}

function validQuote(q: unknown): q is QuoteIn {
  if (!q || typeof q !== 'object') return false;
  const r = q as Record<string, unknown>;
  if (r.note !== undefined && !str(r.note, NOTE_MAX)) return false;
  if (r.source === 'code') return validAnchor(r.code);
  if (!str(r.text, 8192) || !(r.text as string).trim()) return false;
  const lo = (r.locator ?? {}) as Record<string, unknown>;
  if (r.source === 'doc') return typeof r.id === 'string' && DOC_ID.test(r.id) && isInt(r.version) && isInt(lo.line_start) && isInt(lo.line_end);
  if (r.source === 'message') return typeof r.id === 'string' && MESSAGE_ID.test(r.id) && isInt(lo.char_start, 0) && isInt(lo.char_end, 0);
  return false;
}

export function restoreTray(raw: unknown): TrayData {
  const out: TrayData = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const [t, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!TICKET_ID.test(t) || !Array.isArray(v)) continue;
    const ds = v.filter((d): d is Draft => {
      if (!d || typeof d !== 'object') return false;
      const x = d as Record<string, unknown>;
      const w = x.where as Record<string, unknown> | null | undefined;
      const whereOk = w === null || w === undefined || (str(w.uri, 4096) && isInt(w.line_start) && isInt(w.line_end));
      return typeof x.key === 'string' && QUOTE_KEY.test(x.key) && str(x.label, 400) && whereOk && validQuote(x.quote);
    }).map(d => ({ ...d, where: d.where ?? null })).slice(0, QUOTES_MAX);
    if (ds.length) out[t] = ds;
  }
  return out;
}
