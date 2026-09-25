// The ONE mention-tokeniser contract shared with the board (board._mention_handles) and the SPA
// (web/src/components/mentions.ts): an `@handle` addresses someone only outside inline/fenced code
// and not as an e-mail's domain half. Tested against tests/fixtures/mention_cases.json, the file
// the board and the SPA pass too, so the three cannot drift (design-10b21760d9 §4.2).

const CODE_SPAN = /```[\s\S]*?```|`[^`\n]*`/g;

/** Text with code spans/fences blanked (same length, so offsets stay valid). */
export function stripCode(text: string): string {
  return text.replace(CODE_SPAN, m => ' '.repeat(m.length));
}

export type MentionSpan = { handle: string; start: number; end: number };

/** Every @handle token with its offsets (`start` is the `@`), code and e-mail interiors excluded;
 *  trailing punctuation is not part of the handle. */
export function mentionSpans(text: string): MentionSpan[] {
  const out: MentionSpan[] = [];
  const re = /(^|[^\w.@-])@([A-Za-z0-9][\w.-]*)/g;
  const clean = stripCode(text);
  let m: RegExpExecArray | null;
  while ((m = re.exec(clean)) !== null) {
    const tok = m[2].replace(/[.,;:!?]+$/, '');
    if (!tok) continue;
    const start = m.index + m[1].length;
    out.push({ handle: tok, start, end: start + 1 + tok.length });
  }
  return out;
}

export const mentionTokens = (text: string): string[] => mentionSpans(text).map(s => s.handle);

/** The known handles `text` mentions (handle or id match), deduplicated, in order. */
export function mentionedHandles(text: string, people: { handle: string; id: string }[]): string[] {
  const out: string[] = [];
  for (const tok of mentionTokens(text)) {
    const hit = people.find(p => p.handle === tok || p.id === tok);
    if (hit && !out.includes(hit.handle)) out.push(hit.handle);
  }
  return out;
}

/** The @-query the caret sits in, for the autocomplete: `@` at a position the tokeniser would accept
 *  (start of text or after a non-handle character, outside code), and the partial handle typed so far
 *  (possibly empty). Undefined = the caret is not in a mention. */
export function activeMention(text: string, caret: number): { start: number; query: string } | undefined {
  const before = stripCode(text.slice(0, caret));
  const m = /(^|[^\w.@-])@([\w.-]*)$/.exec(before);
  if (!m) return undefined;
  const start = caret - m[2].length - 1;
  // the caret may sit inside a code span that closes after it: judge the `@` against the whole text
  if (stripCode(text)[start] !== '@') return undefined;
  if (m[2] && !/^[A-Za-z0-9]/.test(m[2])) return undefined;
  return { start, query: m[2] };
}
