// ONE mention-tokeniser contract shared with the board (board._mention_handles; adversary round 2
// #6, 2026-09-10): an `@handle` addresses someone only when it is outside inline/fenced code and
// not the domain half of an e-mail. tests/fixtures/mention_cases.json (repo root) is the contract
// both sides are tested against.

const CODE_SPAN = /```[\s\S]*?```|`[^`\n]*`/g;

/** Text with code spans/fences blanked (same length, so offsets stay valid). */
export function stripCode(text: string): string {
  return text.replace(CODE_SPAN, (m) => " ".repeat(m.length));
}

/** Every @handle token in `text`, in order, code and e-mail interiors excluded; trailing
 *  punctuation is not part of the handle. Unknown handles are returned too — the caller decides. */
export function mentionTokens(text: string): string[] {
  const out: string[] = [];
  const re = /(^|[^\w.@-])@([A-Za-z0-9][\w.-]*)/g;
  let m: RegExpExecArray | null;
  const clean = stripCode(text);
  while ((m = re.exec(clean)) !== null) {
    const tok = m[2].replace(/[.,;:!?]+$/, "");
    if (tok) out.push(tok);
  }
  return out;
}

/** The known handles `text` mentions (handle or id match), deduplicated, in order. */
export function mentionedHandles(text: string, people: { handle: string; id: string }[]): string[] {
  const out: string[] = [];
  for (const tok of mentionTokens(text)) {
    const hit = people.find((p) => p.handle === tok || p.id === tok);
    if (hit && !out.includes(hit.handle)) out.push(hit.handle);
  }
  return out;
}

/** C23: the text the wake preview resolves for a draft whose quotes carry notes. The board reads the text and
 *  each note on its own, so a fence left open in one source is closed here before joining; otherwise it would
 *  swallow the next source's @mentions in the preview while delivery still notifies them. */
export function previewMentionText(text: string, notes: (string | null | undefined)[]): string {
  const close = (s: string) => ((s.match(/```/g)?.length ?? 0) % 2 ? `${s}\n\`\`\`` : s);
  return [text, ...notes.filter((n): n is string => Boolean(n))].map(close).join("\n\n");
}
