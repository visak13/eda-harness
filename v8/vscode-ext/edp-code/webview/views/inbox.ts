// The Inbox tab (C15 s-e14d316891; design-10b21760d9 §14.2, §14.4): what waits on the viewer in the picked
// scope only (owner m-db09472a68), answered in place. Sign-offs: the evidence opens in an editor tab, Pass or
// Fail (a Fail needs a note) for the version the row shows. Gates: a ruling box; the design gate links to the
// board's review until C16. Questions: a reply box (an answer to the asker, threaded). Rows come from the host
// and are rows the board says the viewer may act on, so every row has its controls. Enter is a newline and
// Ctrl+Enter sends (C14), for the reply and ruling boxes; a verdict is its own button, never a chord.
// Unsent text is kept per row in webview state; a refusal (the board's words) shows on its row.
import type { ChatState } from '../../src/core/chatProtocol';
import { inboxBadge, writeProblem, type InboxGate, type InboxItem, type InboxQuestion, type InboxSignoff, type InboxVerdict } from '../../src/core/inbox';
import { isSendKey, sendChord } from '../../src/core/composerKeys';
import { bodyFragment } from '../render';
import { action, type Tab, type TabCtx } from '../tabs';

/** rows with a write in flight (their buttons are disabled until the host answers) */
const busy = new Set<string>();
/** per row: the last refusal, shown until the next try */
const errors = new Map<string, string>();
/** the last outcome, announced politely */
let said = '';

const chord = () => sendChord(navigator.platform || navigator.userAgent);
const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const domKey = (key: string) => key.replace(/[^A-Za-z0-9_-]/g, '_');

/** The host settled a write: a done row leaves the list at once (the host's re-read confirms it). */
export function inboxDone(state: ChatState | null, local: TabCtx['local'] | null, m: { key: string; ok: boolean; text: string }): void {
  busy.delete(m.key);
  said = m.text;
  if (m.ok) {
    errors.delete(m.key);
    if (local) delete local.inbox[m.key];
    if (state?.inbox) state.inbox = { ...state.inbox, items: state.inbox.items.filter(i => i.key !== m.key) };
  } else errors.set(m.key, m.text);
}

function fmtTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** A text box whose value is the row's draft; `onSend` runs on the send chord. */
function box(key: string, ctx: TabCtx, label: string, placeholder: string, onSend: (() => void) | null): HTMLTextAreaElement {
  const ta = el('textarea', 'ib-text');
  ta.id = `ib-text-${domKey(key)}`;
  ta.rows = 2;
  ta.value = ctx.local.inbox[key] ?? '';
  ta.placeholder = placeholder;
  ta.setAttribute('aria-label', label);
  ta.addEventListener('input', () => {
    if (ta.value) ctx.local.inbox[key] = ta.value; else delete ctx.local.inbox[key];
    ctx.persist();
  });
  ta.addEventListener('keydown', e => {
    if (e.isComposing || e.keyCode === 229) return;
    if (onSend && isSendKey(e)) { e.preventDefault(); onSend(); } // a plain Enter is a newline
  });
  return ta;
}

function rowShell(i: InboxItem, tag: string, title: string): { row: HTMLElement; err: HTMLElement } {
  const row = el('article', `ib-row ib-${i.type}`);
  row.id = `ib-${domKey(i.key)}`;
  row.dataset.key = i.key;
  row.setAttribute('aria-label', `${tag}: ${title}`);
  const head = el('header', 'ib-head');
  head.append(el('span', 'ib-tag', tag), el('span', 'ib-ticket', title));
  row.append(head);
  const err = el('div', 'ib-error');
  err.setAttribute('role', 'alert');
  err.textContent = errors.get(i.key) ?? '';
  return { row, err };
}

function signoffRow(s: InboxSignoff, ctx: TabCtx, rerender: () => void): HTMLElement {
  const { row, err } = rowShell(s, s.quick ? 'Quick task' : 'Owner sign-off', s.ticketTitle);
  row.title = `${s.ticketId} · criterion ${s.criterionId}`;
  row.append(el('p', 'ib-criterion', s.text));
  const ev = el('button', 'ib-evidence');
  ev.type = 'button';
  ev.id = `ib-open-${domKey(s.key)}`;
  const what = s.evidence.doc ? `${s.evidence.title ?? s.evidence.ref} · ${s.evidence.docType ?? 'doc'} v${s.version}` : s.evidence.ref;
  ev.append(el('span', 'ib-ev-label', 'Open evidence'), el('span', 'ib-ev-what', what));
  ev.title = `Open ${what} in an editor tab`;
  ev.addEventListener('click', () => ctx.post({ type: 'inboxOpen', key: s.key }));
  row.append(ev);
  const note = box(s.key, ctx, `Note for ${s.assignee ?? 'the assignee'} (a Fail needs one)`, 'Note (optional for Pass, needed for Fail); sent to the assignee', null);
  const bar = el('div', 'ib-actions');
  const rule = (verdict: InboxVerdict) => {
    const bad = writeProblem('verdict', note.value, verdict);
    if (bad) { errors.set(s.key, bad); err.textContent = bad; note.focus(); return; }
    busy.add(s.key); errors.delete(s.key);
    ctx.post({ type: 'inboxVerdict', key: s.key, verdict, note: note.value, version: s.version });
    rerender();
  };
  const pass = el('button', 'ib-pass', `Pass v${s.version}`);
  pass.type = 'button';
  pass.id = `ib-pass-${domKey(s.key)}`;
  pass.title = `Pass this criterion on version ${s.version} of the evidence`;
  pass.addEventListener('click', () => rule('pass'));
  const fail = el('button', 'ib-fail', `Fail v${s.version}`);
  fail.type = 'button';
  fail.id = `ib-fail-${domKey(s.key)}`;
  fail.title = `Send it back: fail on version ${s.version}, with your note`;
  fail.addEventListener('click', () => rule('fail'));
  pass.disabled = fail.disabled = busy.has(s.key);
  bar.append(pass, fail);
  row.append(note, bar, err);
  return row;
}

function gateRow(g: InboxGate, ctx: TabCtx, rerender: () => void): HTMLElement {
  const { row, err } = rowShell(g, `${g.gate} gate`, g.ticketTitle ?? g.ticketId);
  row.title = g.ticketId;
  const meta = el('div', 'ib-meta', `opened by ${g.by ?? 'unknown'}${g.at ? ` · ${fmtTime(g.at)}` : ''}`);
  row.append(meta);
  if (g.note) row.append(el('p', 'ib-note', g.note));
  if (g.design) {
    const b = action(`ib-review-${domKey(g.key)}`, 'Review design', 'Open the design review on the board (the editor reader comes with C16)',
      () => ctx.post({ type: 'inboxOpen', key: g.key }));
    const bar = el('div', 'ib-actions');
    bar.append(b);
    row.append(bar, err);
    return row;
  }
  const send = () => {
    const bad = writeProblem('gate', ta.value);
    if (bad) { errors.set(g.key, bad); err.textContent = bad; return; }
    if (busy.has(g.key)) return;
    busy.add(g.key); errors.delete(g.key);
    ctx.post({ type: 'inboxGate', key: g.key, text: ta.value });
    rerender();
  };
  const ta = box(g.key, ctx, `Your ruling on the ${g.gate} gate`, `Your ruling… ${chord()} to send`, send);
  const bar = el('div', 'ib-actions');
  const b = el('button', 'ib-send', 'Answer gate');
  b.type = 'button';
  b.id = `ib-send-${domKey(g.key)}`;
  b.title = `Answer the ${g.gate} gate (${chord()})`;
  b.disabled = busy.has(g.key);
  b.addEventListener('click', send);
  bar.append(b);
  row.append(ta, bar, err);
  return row;
}

function questionRow(q: InboxQuestion, ctx: TabCtx, rerender: () => void): HTMLElement {
  const { row, err } = rowShell(q, q.kind, q.ticketTitle ?? q.ticketId);
  row.title = `${q.ticketId} · ${q.id}`;
  const meta = el('div', 'ib-meta');
  meta.append(el('span', 'by', q.by), el('span', 'ib-role', q.byHuman ? 'person' : q.byRole));
  if (q.at) { const t = el('time', 'at', fmtTime(q.at)); t.dateTime = q.at; meta.append(t); }
  const open = el('button', 'board-link', '↗');
  open.type = 'button';
  open.title = 'Open on the board';
  open.setAttribute('aria-label', 'Open on the board');
  open.addEventListener('click', () => ctx.post({ type: 'openBoard', ticketId: q.ticketId, messageId: q.id }));
  meta.append(open);
  row.append(meta);
  if (q.why) row.append(el('div', 'ib-why', `Why you see it: ${q.why}`));
  const body = el('div', 'body ib-body');
  const known = new Set((ctx.state.people ?? []).flatMap(p => [p.handle, p.id]));
  body.append(bodyFragment(document, q.text, known));
  row.append(body);
  if (q.note) row.append(el('div', 'ib-meta', q.note));
  const send = () => {
    const bad = writeProblem('answer', ta.value);
    if (bad) { errors.set(q.key, bad); err.textContent = bad; return; }
    if (busy.has(q.key)) return;
    busy.add(q.key); errors.delete(q.key);
    ctx.post({ type: 'inboxAnswer', key: q.key, text: ta.value });
    rerender();
  };
  const ta = box(q.key, ctx, `Answer ${q.by}`, `Answer @${q.by}… ${chord()} to send`, send);
  const bar = el('div', 'ib-actions');
  const b = el('button', 'ib-send', 'Reply');
  b.type = 'button';
  b.id = `ib-send-${domKey(q.key)}`;
  b.title = `Send an answer to @${q.by} (${chord()})`;
  b.disabled = busy.has(q.key);
  b.addEventListener('click', send);
  bar.append(b);
  row.append(ta, bar, err);
  return row;
}

function section(id: string, title: string, rows: HTMLElement[]): HTMLElement {
  const s = el('section', 'ib-group');
  s.id = id;
  const h = el('h3', 'ib-group-title');
  h.append(el('span', '', title), el('span', 'group-count', String(rows.length)));
  s.setAttribute('aria-label', `${title}, ${rows.length}`);
  s.append(h, ...rows);
  return s;
}

export function renderInbox(panel: HTMLElement, ctx: TabCtx): void {
  // keep the caret where the viewer is typing across a re-render (a feed-driven re-read lands mid-word)
  const active = document.activeElement as HTMLElement | null;
  const focusId = active && panel.contains(active) ? active.id : '';
  const sel = active instanceof HTMLTextAreaElement ? [active.selectionStart, active.selectionEnd] as const : null;
  const rerender = () => renderInbox(panel, ctx);
  const inbox = ctx.state.inbox ?? null;
  const kind = ctx.state.ticket?.kind ?? 'ticket';
  const items = inbox?.items ?? [];
  const top = el('div', 'tab-top');
  const sum = el('span', 'tab-sum');
  sum.id = 'inbox-summary';
  sum.textContent = !inbox || (inbox.loading && !items.length) ? 'Reading what waits on you…'
    : items.length ? `${items.length} item${items.length === 1 ? '' : 's'} in this ${kind} wait${items.length === 1 ? 's' : ''} on you`
    : `Nothing in this ${kind} waits on you`;
  top.append(sum, action('inbox-refresh', 'Refresh', 'Read the board again', () => ctx.post({ type: 'inboxRefresh' })));
  const out: HTMLElement[] = [top];
  if (inbox?.error) { const e = el('div', 'ib-error ib-list-error', inbox.error); e.setAttribute('role', 'alert'); out.push(e); }
  const live = el('div', 'sr-only');
  live.id = 'inbox-status';
  live.setAttribute('aria-live', 'polite');
  live.textContent = said;
  out.push(live);
  const signoffs = items.filter((i): i is InboxSignoff => i.type === 'signoff');
  const gates = items.filter((i): i is InboxGate => i.type === 'gate');
  const questions = items.filter((i): i is InboxQuestion => i.type === 'question');
  if (signoffs.length) out.push(section('inbox-signoffs', 'Sign-offs', signoffs.map(s => signoffRow(s, ctx, rerender))));
  if (gates.length) out.push(section('inbox-gates', 'Gates', gates.map(g => gateRow(g, ctx, rerender))));
  if (questions.length) out.push(section('inbox-questions', 'Questions', questions.map(q => questionRow(q, ctx, rerender))));
  panel.replaceChildren(...out);
  if (focusId) {
    const f = panel.querySelector<HTMLElement>(`#${CSS.escape(focusId)}`);
    f?.focus();
    if (f instanceof HTMLTextAreaElement && sel) f.setSelectionRange(sel[0], sel[1]);
  }
}

export const inboxTab: Tab = {
  id: 'inbox',
  label: 'Inbox',
  badge: ctx => inboxBadge(ctx.state.inbox),
  render: renderInbox,
};
