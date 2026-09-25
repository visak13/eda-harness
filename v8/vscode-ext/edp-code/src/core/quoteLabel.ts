// C20 s-29f052c40e: how a quote names its source, the same words in the chip, the card and the board UI (C19
// QuoteCard.quoteSourceLabel) and in what agents read (edp8/quotes.py source_line). Pure: the webview bundles it.
import type { QuoteView } from './chatProtocol';

const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const FENCE = /^\s{0,3}(```|~~~)/;

/** The nearest markdown heading at or above 1-based `line`, ignoring `#` lines inside code fences (heading_at). */
export function headingAt(lines: readonly string[], line: number): string | null {
  let found: string | null = null, fence: string | null = null;
  for (const ln of lines.slice(0, line)) {
    const f = FENCE.exec(ln);
    if (f) { fence = fence === null ? f[1] : f[1] === fence ? null : fence; continue; }
    const m = fence ? null : HEADING.exec(ln);
    if (m && m[2]) found = m[2];
  }
  return found;
}

/** `§14.5` for a numbered heading, else `§<heading>` clipped (section_label). */
export function sectionLabel(heading: string | null | undefined): string {
  if (!heading) return '';
  const m = /^(\d+(?:\.\d+)*)\.?(?:\s|$)/.exec(heading);
  return `§${m ? m[1] : heading.length <= 60 ? heading : `${heading.slice(0, 59)}…`}`;
}

const lineLabel = (a: number, b: number) => `L${a}${b > a ? `-${b}` : ''}`;

export function docLabel(id: string, version: number, heading: string | null, a: number, b: number): string {
  return [`${id} v${version}`, sectionLabel(heading), lineLabel(a, b)].filter(Boolean).join(' ');
}

/** A stored quote's source, as its card names it: `design-… v12 §14.5 L41-43`, `m-… (author)`, `path:L3-9`. */
export function quoteSourceLabel(q: QuoteView): string {
  if (q.source === 'doc') {
    const lo = q.locator ?? {};
    return lo.line_start ? docLabel(q.id ?? '', q.version ?? 0, lo.heading ?? null, lo.line_start, lo.line_end ?? lo.line_start)
      : [`${q.id} v${q.version}`, sectionLabel(lo.heading)].filter(Boolean).join(' ');
  }
  if (q.source === 'message') return `${q.id}${q.author ? ` (${q.author})` : ''}`;
  return q.code ? `${q.code.path}:${lineLabel(q.code.line_start, q.code.line_end)}` : 'code';
}
