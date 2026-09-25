// C20 s-29f052c40e (design-10b21760d9 v12 §14.5, §14.7) in the chat webview: the composer's quote chips (the host's
// draft tray for the open thread: reorder, note, remove; a send names them by key in this order), the quote cards a
// message shows above its text (passage, source link, note; the board UI's C19 card shape), and Quote + note on a
// selection inside a message (a button by the selection, or Ctrl+Alt+Q). Everything is set with textContent.
import type { ChatMessage, QuoteChip, QuoteView, ViewToHost } from '../src/core/chatProtocol';
import { QUOTE_NOTE_MAX } from '../src/core/chatProtocol';
import { isSendKey, sendChord } from '../src/core/composerKeys';
import { quoteSourceLabel } from '../src/core/quoteLabel';
import { displayPassage } from '../src/core/quoteMatch';
import { at } from '../src/core/render';
import type { NoteCompletion } from './noteComplete';

type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
type Post = (m: Intent) => void;

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const button = (cls: string, text: string, title: string) => {
  const b = el('button', cls, text);
  b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
  return b;
};
const chord = () => sendChord(navigator.platform || navigator.userAgent);

/** Ctrl+Alt+Q (architect m-db0d013529; never Ctrl+Shift+Q, which quits Firefox). */
export const isQuoteKey = (e: KeyboardEvent) => e.ctrlKey && e.altKey && !e.shiftKey && !e.metaKey && (e.key === 'q' || e.key === 'Q' || e.code === 'KeyQ');

// -- cards --------------------------------------------------------------------------------------------------
/** A message's quotes as cards, above its text; the source link opens the doc version at the lines in the reader,
 *  the code at the lines, or the quoted message (scrolled to). */
export function quoteCards(m: ChatMessage, post: Post): HTMLElement | null {
  const qs = m.quotes ?? [];
  if (!qs.length) return null;
  const box = el('div', 'quote-cards');
  box.setAttribute('aria-label', `${qs.length} ${qs.length === 1 ? 'quote' : 'quotes'}`);
  qs.forEach((q, i) => box.append(card(m, q, i, post)));
  return box;
}

function card(m: ChatMessage, q: QuoteView, i: number, post: Post): HTMLElement {
  const f = el('figure', 'quote-card');
  f.dataset.source = q.source;
  const label = quoteSourceLabel(q);
  if (q.source === 'code' && q.code) {
    const lines = (q.code.snippet || q.text).split('\n');
    const pre = el('pre', 'qc-code', lines.slice(0, 12).join('\n') + (lines.length > 12 ? `\n… ${lines.length - 12} more lines` : ''));
    f.append(pre);
  } else {
    const bq = el('blockquote', 'qc-passage', displayPassage(q.text));
    bq.title = q.text;
    f.append(bq);
  }
  const cap = el('figcaption', 'qc-foot');
  const link = button('qc-source', `${q.source === 'doc' ? '📄' : q.source === 'code' ? '⟨⟩' : '↩'} ${q.source === 'code' && q.code ? at(q.code) : label}`,
    q.source === 'doc' ? `Open ${label} in the reader` : q.source === 'code' ? `Open ${label}` : `Show ${q.id}`);
  link.addEventListener('click', () => post({ type: 'openQuote', messageId: m.id, index: i }));
  cap.append(link);
  f.append(cap);
  if (q.note) {
    const n = el('p', 'qc-note');
    n.append(el('span', 'qc-note-label', 'Note'), document.createTextNode(` ${q.note}`));
    f.append(n);
  }
  return f;
}

// -- chips ----------------------------------------------------------------------------------------------------
/** The open thread's draft quotes in the composer. */
export class QuoteChips {
  readonly box = el('ol', 'quote-chips');
  /** a note typed and not yet posted, with the thread it was typed in (a thread switch must not re-address it) */
  private noteTimers = new Map<string, { t: ReturnType<typeof setTimeout>; ticket: string | null }>();
  private rows: QuoteChip[] = [];
  private ticket: string | null = null;

  /** `complete`: @ and # completion on the note fields (C20, owner m-5a9111ce12) */
  constructor(private post: Post, private status: HTMLElement, private complete?: NoteCompletion) {
    this.box.id = 'quote-chips';
    this.box.setAttribute('aria-label', 'Quotes sent with this message, in order');
    this.box.hidden = true;
  }

  get keys(): string[] { return this.rows.map(r => r.key); }
  get count(): number { return this.rows.length; }

  /** Show `rows` for `ticket`; a note being typed keeps its caret. */
  render(ticket: string | null, rows: QuoteChip[]): void {
    const active = document.activeElement as HTMLInputElement | null;
    let typing = active?.classList?.contains('qchip-note') ? { key: active.dataset.key, s: active.selectionStart, e: active.selectionEnd, v: active.value } : null;
    if (ticket !== this.ticket) { this.flush(); typing = null; } // another thread's rows: post the old thread's notes first
    this.ticket = ticket;
    this.rows = rows;
    this.box.replaceChildren(...rows.map((r, i) => this.chip(r, i)));
    this.box.hidden = !rows.length;
    if (typing?.key) {
      const again = this.box.querySelector<HTMLInputElement>(`.qchip-note[data-key="${CSS.escape(typing.key)}"]`);
      if (again) { if (this.noteTimers.has(typing.key)) again.value = typing.v; again.focus(); again.setSelectionRange(typing.s, typing.e); }
    }
  }

  private chip(r: QuoteChip, i: number): HTMLElement {
    const li = el('li', `qchip${r.invalid ? ' invalid' : ''}`);
    li.dataset.key = r.key;
    li.dataset.source = r.source;
    const head = el('div', 'qchip-head');
    const label = el('code', 'qchip-label', r.label);
    label.title = r.label;
    const n = this.rows.length;
    const up = button('qchip-up', '↑', `Move quote ${i + 1} up`);
    up.disabled = i === 0;
    up.addEventListener('click', () => this.act({ type: 'quoteMove', key: r.key, by: -1 }, `Moved quote ${i + 1} up`));
    const down = button('qchip-down', '↓', `Move quote ${i + 1} down`);
    down.disabled = i === n - 1;
    down.addEventListener('click', () => this.act({ type: 'quoteMove', key: r.key, by: 1 }, `Moved quote ${i + 1} down`));
    const x = button('qchip-remove', '×', `Remove quote ${i + 1} (${r.label})`);
    x.addEventListener('click', () => this.act({ type: 'quoteDrop', key: r.key }, `Removed quote ${r.label}`));
    head.append(el('span', 'qchip-src', r.source), label, up, down, x);
    const text = el('p', 'qchip-text', r.passage);
    const note = el('input', 'qchip-note');
    note.type = 'text';
    note.value = r.note;
    note.maxLength = QUOTE_NOTE_MAX;
    note.placeholder = 'Note on this passage (optional)';
    note.dataset.key = r.key;
    note.setAttribute('aria-label', `Note on quote ${i + 1}`);
    this.complete?.attach(note, this.box.parentElement ?? this.box, () => note.dispatchEvent(new Event('input')));
    note.addEventListener('input', () => {
      const ticket = this.ticket;
      clearTimeout(this.noteTimers.get(r.key)?.t);
      this.noteTimers.set(r.key, { t: setTimeout(() => this.flushNote(r.key, note.value), 300), ticket });
    });
    note.addEventListener('blur', () => { if (this.noteTimers.has(r.key)) this.flushNote(r.key, note.value); });
    li.append(head, text, note);
    if (r.invalid) li.append(el('p', 'qchip-bad', 'The board refused this quote on the last send: its source changed or cannot be read. Remove it, or quote it again.'));
    return li;
  }

  /** Notes typed and not yet posted go now (before a send). */
  flush(): void {
    for (const key of [...this.noteTimers.keys()]) {
      const inp = this.box.querySelector<HTMLInputElement>(`.qchip-note[data-key="${CSS.escape(key)}"]`);
      if (inp) this.flushNote(key, inp.value);
    }
  }

  private flushNote(key: string, note: string): void {
    const pending = this.noteTimers.get(key);
    clearTimeout(pending?.t);
    this.noteTimers.delete(key);
    const ticketId = pending ? pending.ticket : this.ticket;
    if (ticketId) this.post({ type: 'quoteNote', ticketId, key, note });
  }

  private act(m: { type: 'quoteMove'; key: string; by: -1 | 1 } | { type: 'quoteDrop'; key: string }, said: string): void {
    if (!this.ticket) return;
    this.flush();
    this.post({ ...m, ticketId: this.ticket });
    this.status.textContent = said;
  }
}

// -- Quote + note on a message selection ----------------------------------------------------------------------
type Picked = { messageId: string; text: string; before: string; rect: DOMRect };

/** The selection, when it lies inside ONE message body of `list`: its message, text and the body's text before it. */
function picked(list: HTMLElement): Picked | null {
  const s = document.getSelection();
  if (!s || s.rangeCount === 0 || s.isCollapsed) return null;
  const r = s.getRangeAt(0);
  const bodyOf = (n: Node) => (n instanceof Element ? n : n.parentElement)?.closest('.msg > .body') ?? null;
  const body = bodyOf(r.startContainer);
  if (!body || body !== bodyOf(r.endContainer) || !list.contains(body)) return null;
  const id = (body.parentElement as HTMLElement | null)?.dataset.id;
  const text = s.toString();
  if (!id || !text.trim()) return null;
  const pre = document.createRange();
  pre.setStart(body, 0);
  pre.setEnd(r.startContainer, r.startOffset);
  return { messageId: id, text, before: pre.toString(), rect: r.getBoundingClientRect() };
}

export class MessageQuoter {
  private btn = button('quote-sel', '❝ Quote', `Quote this passage in the reply (Ctrl+Alt+Q)`);
  private pop = el('div', 'quote-pop');
  private note = el('textarea', 'quote-pop-note');
  private sel: Picked | null = null;
  private timer?: ReturnType<typeof setTimeout>;

  constructor(private list: HTMLElement, private ticket: () => string | null, private post: Post, private status: HTMLElement,
    complete?: NoteCompletion) {
    this.btn.id = 'quote-selection';
    this.btn.hidden = true;
    this.btn.addEventListener('mousedown', e => e.preventDefault()); // keep the selection
    this.btn.addEventListener('click', () => this.open());
    this.pop.id = 'quote-pop';
    this.pop.hidden = true;
    this.pop.setAttribute('role', 'dialog');
    this.pop.setAttribute('aria-label', 'Quote with a note');
    this.note.id = 'quote-pop-note';
    this.note.rows = 2;
    this.note.maxLength = QUOTE_NOTE_MAX;
    this.note.placeholder = `Note on this passage (optional) · ${chord()} adds`;
    this.note.setAttribute('aria-label', 'Note on the quoted passage');
    const add = button('quote-pop-add', 'Add to chat', `Add the passage and note to the composer (${chord()})`);
    add.id = 'quote-pop-add';
    add.addEventListener('click', () => this.add());
    const cancel = button('quote-pop-cancel', 'Cancel', 'Cancel (Escape)');
    cancel.addEventListener('click', () => this.close());
    const acts = el('div', 'quote-pop-acts');
    acts.append(add, cancel);
    this.pop.append(el('div', 'quote-pop-text'), this.note, acts);
    complete?.attach(this.note, this.pop); // before the note's own keys: a pick's Enter/Escape stops there
    this.note.addEventListener('keydown', e => {
      if (e.isComposing || e.keyCode === 229) return;
      if (isSendKey(e)) { e.preventDefault(); this.add(); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); }
    });
    document.body.append(this.btn, this.pop);
    document.addEventListener('selectionchange', () => { clearTimeout(this.timer); this.timer = setTimeout(() => this.track(), 120); });
    // Ctrl+Alt+Q: only with a selection in a message, never while typing (on an AltGr layout the chord types @)
    document.addEventListener('keydown', e => {
      if (!isQuoteKey(e)) return;
      const a = document.activeElement;
      if (a instanceof HTMLTextAreaElement || a instanceof HTMLInputElement || a instanceof HTMLSelectElement) return;
      if (!picked(this.list)) return;
      e.preventDefault();
      this.track();
      this.open();
    });
  }

  private track(): void {
    if (!this.pop.hidden) return;
    const p = picked(this.list);
    this.btn.hidden = !p;
    if (!p) return;
    this.btn.style.top = `${Math.max(0, Math.min(window.innerHeight - 28, p.rect.bottom + 4))}px`;
    this.btn.style.left = `${Math.max(0, Math.min(window.innerWidth - 90, p.rect.left))}px`;
  }

  /** Open the note box on the current selection (captured now: focusing the note box clears it). */
  open(): void {
    const p = picked(this.list);
    if (!p) return;
    this.sel = p;
    this.btn.hidden = true;
    (this.pop.firstChild as HTMLElement).textContent = `“${p.text.replace(/\s+/g, ' ').trim().slice(0, 160)}”`;
    this.note.value = '';
    this.pop.style.top = `${Math.max(0, Math.min(window.innerHeight - 140, p.rect.bottom + 4))}px`;
    this.pop.hidden = false;
    this.note.focus();
  }

  private add(): void {
    const t = this.ticket();
    if (!this.sel || !t) return this.close();
    this.post({ type: 'quoteMessage', ticketId: t, messageId: this.sel.messageId, text: this.sel.text, before: this.sel.before, note: this.note.value });
    this.status.textContent = 'Adding the quote to the composer…';
    this.close();
  }

  close(): void {
    this.pop.hidden = true;
    this.sel = null;
    this.btn.hidden = true;
  }
}
