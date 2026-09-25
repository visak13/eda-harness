// C22 s-3b86872bf0: Reply in the chat webview, as the board UI's thread does (Conversation.tsx / Composer.tsx): a
// Reply on a message sets the composer's reply target (its author becomes `to`, which the viewer may change), the
// send carries `reply_to`, and a reply shows its parent's excerpt. The target lives per thread in the webview's own
// state (it survives the view being hidden); whatever getState returns is untrusted, so it is checked here. Pure.
import { MESSAGE_ID, TICKET_ID } from './chatProtocol';

/** the reply bar and a reply's parent line show at most this many characters of the parent (the web's 160) */
export const EXCERPT_MAX = 160;
/** at most this many threads keep an unsent reply target (the most recently set) */
export const REPLIES_MAX = 50;

/** What the reply bar needs when the parent is no longer among the loaded messages, and the To the viewer chose
 *  for it ('' = the thread; it starts as the parent's author) */
export type ReplyRef = { id: string; by: string; excerpt: string; to: string };

/** One line of a message: whitespace collapsed, cut on a code point with an ellipsis. */
export function excerpt(text: string, max = EXCERPT_MAX): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  const cps = Array.from(flat);
  return cps.length <= max ? flat : cps.slice(0, max - 1).join('').trimEnd() + '…';
}

export const replyRef = (m: { id: string; created_by: string; text: string }): ReplyRef =>
  ({ id: m.id, by: m.created_by, excerpt: excerpt(m.text), to: m.created_by });

/** The saved reply targets by thread; a malformed entry is dropped. */
export function restoreReplies(raw: unknown): Record<string, ReplyRef> {
  const out: Record<string, ReplyRef> = {};
  if (!raw || typeof raw !== 'object') return out;
  const kept = Object.entries(raw as Record<string, unknown>).filter(([k, v]) => {
    if (!TICKET_ID.test(k) || !v || typeof v !== 'object') return false;
    const r = v as Record<string, unknown>;
    return typeof r.id === 'string' && MESSAGE_ID.test(r.id) && typeof r.by === 'string' && r.by.length > 0 && r.by.length <= 128
      && typeof r.excerpt === 'string' && r.excerpt.length <= EXCERPT_MAX * 2 && typeof r.to === 'string' && r.to.length <= 128;
  });
  for (const [k, v] of kept.slice(-REPLIES_MAX)) { const r = v as ReplyRef; out[k] = { id: r.id, by: r.by, excerpt: r.excerpt, to: r.to }; }
  return out;
}

