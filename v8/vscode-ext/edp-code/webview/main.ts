// The chat webview (design-10b21760d9 §4.1; strategyll-1a201146c8, -86c5b5068f, -5e3ecdb625). It holds
// no credentials and makes no network call: it renders what the host posts and posts intents back.
// Everything that is not a message body is set with textContent. View-local UI (drafts, kind) lives in
// setState; board data is always re-sent by the host on `ready`.
import type { ChatMessage, ChatState, FeedStatus, HostToView, PersonRow, SendKind, StoryRow, ViewToHost } from '../src/core/chatProtocol';
import { SEND_KINDS, TEXT_MAX } from '../src/core/chatProtocol';
import { activeMention } from '../src/core/mentions';
import { accessibleName, filterPeople } from '../src/core/people';
import { at } from '../src/core/render';
import { bodyFragment } from './render';
import { appendCommits, appendUnlinked, commitCount, placeCards, renderCommits, renderUncommitted, renderUnlinked, uncommittedLabel, unlinkedLabel } from './cards';
import { restoreLocal } from '../src/core/viewState';

declare function acquireVsCodeApi(): { postMessage(m: unknown): void; getState(): unknown; setState(s: unknown): void };
const vscode = acquireVsCodeApi();

// drafts, kind and what is folded (C9): per viewer, in the webview state only, never on the board
const local = restoreLocal(vscode.getState());
const persist = () => vscode.setState(local);

let state: ChatState | null = null;
/** the thread a send is in flight for: its answer (sent / sendFailed) names the same ticket */
let pendingTicket: string | null = null;
type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
const post = (m: Intent) => vscode.postMessage({ v: 1, ...m });

// -- DOM ---------------------------------------------------------------------------------------------
const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

/** the composer starts at 2 lines and grows with its text to 8, then scrolls (C9) */
const MIN_ROWS = 2;
const MAX_ROWS = 8;

const app = document.getElementById('app')!;
// C9: ONE header line: [‹ epic] [picker: open thread ▾] [status] [@architect] [Stories ▾] [feed dot]
const header = el('header', 'hdr');
header.setAttribute('aria-label', 'Thread');
const back = el('button', 'crumb epic');
back.id = 'crumb-epic';
back.type = 'button';
const sep = el('span', 'sep', '›');
sep.setAttribute('aria-hidden', 'true');
const pickBtn = el('button', 'pick');
pickBtn.id = 'pick';
pickBtn.type = 'button';
const pickText = el('span', 'pick-text', 'Pick a ticket or epic…');
const cur = el('span', 'crumb current');
cur.id = 'crumb-current';
const caret = el('span', 'caret', '▾');
caret.setAttribute('aria-hidden', 'true');
pickBtn.append(pickText, cur, caret);
const tStatus = el('span', 'tstatus');
tStatus.id = 'ticket-status';
const arch = el('span', 'arch');
arch.id = 'architect';
const storiesBtn = el('button', 'stories-btn');
storiesBtn.id = 'stories-toggle';
storiesBtn.type = 'button';
storiesBtn.setAttribute('aria-haspopup', 'true');
storiesBtn.setAttribute('aria-controls', 'stories');
storiesBtn.setAttribute('aria-expanded', 'false');
const feedDot = el('span', 'feed');
feedDot.id = 'feed-status';
feedDot.setAttribute('role', 'status');
header.append(back, sep, pickBtn, tStatus, arch, storiesBtn, feedDot);

// the Stories dropdown (replaces the C3 strip): every story thread, with unread and commit counts
const strip = el('div', 'stories');
strip.id = 'stories';
strip.setAttribute('role', 'list');
strip.setAttribute('aria-label', 'Stories');
strip.hidden = true;
header.append(strip);

// the folded bands: chips that expand in place, collapsed by default (per viewer, webview state)
const bands = el('div', 'bands');
bands.id = 'bands';
const ucChip = el('button', 'band-chip');
ucChip.id = 'uncommitted-toggle';
ucChip.type = 'button';
ucChip.setAttribute('aria-controls', 'uncommitted');
const ulChip = el('button', 'band-chip');
ulChip.id = 'unlinked-toggle';
ulChip.type = 'button';
ulChip.setAttribute('aria-controls', 'unlinked');
bands.append(ucChip, ulChip);
const notice = el('div', 'notice');
notice.id = 'notice';

const timeline = el('div', 'timeline');
timeline.id = 'timeline';
timeline.setAttribute('role', 'log');
timeline.setAttribute('aria-label', 'Messages');
const olderBtn = el('button', 'older', 'Load older messages');
olderBtn.id = 'older';
const list = el('div', 'items');
timeline.append(olderBtn, list);

// C9: one composer box: the chip, a text area that starts at 2 lines and grows to 8, and a toolbar with
// kind/to and Send. `#composer-tools` is the empty slot C11 (#-tag) and C12 (attach) add buttons to.
const composer = el('form', 'composer');
composer.id = 'composer-form';
const cbox = el('div', 'cbox');
const kindSel = el('select');
kindSel.id = 'kind';
kindSel.title = 'Kind';
kindSel.setAttribute('aria-label', 'Kind');
for (const k of SEND_KINDS) kindSel.append(new Option(k, k));
const toSel = el('select');
toSel.id = 'to';
toSel.title = 'To (optional): mentions wake people either way';
toSel.setAttribute('aria-label', 'To (optional)');
const ta = el('textarea');
ta.id = 'composer';
ta.rows = MIN_ROWS;
ta.placeholder = 'Message… @ to mention · Enter sends, Shift+Enter newline';
ta.setAttribute('aria-label', 'Message');
ta.setAttribute('aria-autocomplete', 'list');
ta.setAttribute('aria-controls', 'people');
ta.setAttribute('aria-describedby', 'ac-status');
const peopleList = el('ul', 'people');
peopleList.id = 'people';
peopleList.setAttribute('role', 'listbox');
peopleList.setAttribute('aria-label', 'People');
peopleList.hidden = true;
const acStatus = el('div', 'sr-only');
acStatus.id = 'ac-status';
acStatus.setAttribute('aria-live', 'polite');
const tools = el('div', 'ctools');
tools.setAttribute('role', 'toolbar');
tools.setAttribute('aria-label', 'Message options');
const toolSlot = el('span', 'tool-slot');
toolSlot.id = 'composer-tools';
const sendBtn = el('button', 'send', 'Send');
sendBtn.id = 'send';
sendBtn.type = 'submit';
sendBtn.title = 'Send (Enter)';
tools.append(toolSlot, kindSel, toSel, el('span', 'spacer'), sendBtn);
const sendErr = el('div', 'send-error');
sendErr.id = 'send-error';
sendErr.setAttribute('role', 'alert');
// the code chip a Tag selection puts here (C4): display only; the host holds the anchor
const chipBox = el('div', 'chip');
chipBox.id = 'code-chip';
chipBox.setAttribute('role', 'group');
chipBox.setAttribute('aria-label', 'Tagged lines, sent with this message');
chipBox.hidden = true;
cbox.append(chipBox, ta, tools);
composer.append(peopleList, cbox, acStatus, sendErr);

// what the chips expand to, in place above the thread (bounded, scrolls)
const pinned = el('div', 'pinned');
pinned.id = 'pinned';
const uncommittedBox = el('section', 'uncommitted');
uncommittedBox.id = 'uncommitted';
uncommittedBox.setAttribute('aria-label', 'Uncommitted changes');
const unlinkedBox = el('section', 'unlinked-box');
unlinkedBox.id = 'unlinked';
unlinkedBox.setAttribute('aria-label', 'Unlinked commits');
pinned.append(uncommittedBox, unlinkedBox);

app.append(header, bands, notice, pinned, timeline, composer);

// -- rendering ---------------------------------------------------------------------------------------
const FEED_LABEL: Record<FeedStatus, string> = {
  connecting: 'connecting…', live: 'live', reconnecting: 'reconnecting…', polling: 'polling', 'signed-out': 'signed out', stopped: 'stopped',
};

function setFeed(s: FeedStatus) {
  feedDot.textContent = FEED_LABEL[s];
  feedDot.dataset.status = s;
}

const known = () => new Set((state?.people ?? []).flatMap(p => [p.handle, p.id]).concat(state?.me ? [state.me.handle, state.me.id] : []));

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const same = new Date().toDateString() === d.toDateString();
  return same ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function messageEl(m: ChatMessage, k: ReadonlySet<string>): HTMLElement {
  const a = el('article', `msg kind-${m.kind}`);
  a.dataset.id = m.id;
  a.setAttribute('aria-label', `${m.created_by}, ${m.kind}`);
  const h = el('header', 'mh');
  h.append(el('span', 'by', m.created_by), el('span', 'kind', m.kind));
  if (m.to) h.append(el('span', 'to', `→ ${m.to}`));
  const t = el('time', 'at', fmtTime(m.created_at));
  t.dateTime = m.created_at;
  const open = el('button', 'board-link', '↗');
  open.title = 'Open on the board';
  open.setAttribute('aria-label', 'Open on the board');
  open.addEventListener('click', () => post({ type: 'openBoard', ticketId: m.ticket_id, messageId: m.id }));
  h.append(t, open);
  const body = el('div', 'body');
  body.append(bodyFragment(document, m.text, k));
  a.append(h, body);
  if (m.code_context) a.append(codeCard(m));
  return a;
}

function codeCard(m: ChatMessage): HTMLElement {
  const c = m.code_context!;
  const b = el('button', 'code-card');
  b.type = 'button';
  b.title = `Open ${c.path} at lines ${c.line_start}-${c.line_end}`;
  const head = el('span', 'cc-head', at(c));
  const lines = c.snippet.split('\n');
  const pre = el('pre', 'cc-snippet', lines.slice(0, 12).join('\n') + (lines.length > 12 ? `\n… ${lines.length - 12} more lines` : ''));
  b.append(head, pre);
  b.addEventListener('click', () => post({ type: 'openCode', messageId: m.id }));
  return b;
}

function nearBottom() { return timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 40; }
function toBottom() { timeline.scrollTop = timeline.scrollHeight; }

function renderItems(items: ChatMessage[]) {
  const k = known();
  list.replaceChildren(...items.map(m => messageEl(m, k)));
  if (!items.length) list.append(el('p', 'empty', state?.ticket ? 'No messages on this thread yet.' : ''));
}

function storyEl(s: StoryRow, open: string | undefined): HTMLElement {
  const b = el('button', `story${s.id === open ? ' active' : ''}`);
  b.type = 'button';
  b.setAttribute('role', 'listitem');
  b.dataset.id = s.id;
  b.title = `${s.id} · ${s.title}`;
  b.append(el('span', 'st-title', s.title), el('span', `st-status status-${s.status}`, s.status));
  if (s.unread > 0) {
    const u = el('span', 'st-unread', s.unread > 99 ? '99+' : String(s.unread));
    u.setAttribute('aria-label', `${s.unread} new`);
    b.append(u);
  }
  if (s.commits) b.append(commitCount(s.commits));
  b.addEventListener('click', () => post({ type: 'pickTicket', id: s.id }));
  return b;
}

function renderStories() {
  const s = state!;
  strip.replaceChildren(...s.stories.map(x => storyEl(x, s.ticket?.id)));
  const show = !!s.epic && s.stories.length > 0;
  storiesBtn.hidden = !show;
  if (!show) setStoriesOpen(false);
  const unread = s.stories.reduce((n, x) => n + x.unread, 0);
  storiesBtn.replaceChildren(el('span', 'sb-label', `Stories ${s.stories.length}`));
  if (unread) {
    const u = el('span', 'st-unread', unread > 99 ? '99+' : String(unread));
    storiesBtn.append(u);
  }
  storiesBtn.append(el('span', 'caret', '▾'));
  storiesBtn.title = `${s.stories.length} stories${unread ? `, ${unread} new messages` : ''}: open a story thread`;
  storiesBtn.setAttribute('aria-label', storiesBtn.title);
}

function setStoriesOpen(open: boolean, focus = false) {
  strip.hidden = !open;
  storiesBtn.setAttribute('aria-expanded', String(open));
  if (open && focus) strip.querySelector<HTMLElement>('.story')?.focus();
}

/** The one-line header: the breadcrumb back to the epic, the picker (it names the open thread), the
 *  thread's status and the epic's architect. The id/kind live in tooltips. */
function renderHeader() {
  const s = state!;
  const t = s.ticket;
  const inStory = !!(t && s.epic && s.epic.id !== t.id);
  back.hidden = sep.hidden = !inStory;
  if (inStory) {
    back.textContent = s.epic!.title;
    back.title = `Back to the epic thread: ${s.epic!.title} (${s.epic!.id})`;
  }
  pickText.hidden = !!t;
  cur.hidden = !t;
  cur.textContent = t?.title ?? '';
  if (t) cur.setAttribute('aria-current', 'page'); else cur.removeAttribute('aria-current');
  pickBtn.title = t ? `${t.title}
${t.kind} ${t.id} · ${t.status}${s.epic ? ` · architect ${s.architect ? '@' + s.architect : 'none live'}` : ''}
Click to open another thread` : 'Pick a ticket or epic';
  tStatus.hidden = !t;
  tStatus.textContent = t?.status ?? '';
  tStatus.dataset.status = t?.status ?? '';
  tStatus.title = t ? `Status: ${t.status}` : '';
  arch.hidden = !s.epic;
  arch.textContent = s.epic ? (s.architect ? `@${s.architect}` : 'no architect') : '';
  arch.title = s.epic ? `Architect: ${s.architect ? '@' + s.architect : 'none live'}` : '';
  arch.setAttribute('aria-label', arch.title);
}

/** The chips row and what it expands to. Both collapsed unless this viewer opened them. */
function renderBands() {
  const s = state!;
  bands.hidden = !s.ticket;
  const uc = uncommittedLabel(s.uncommitted);
  ucChip.textContent = uc.text;
  ucChip.setAttribute('aria-label', uc.aria);
  ucChip.title = `${uc.aria}. Click to ${local.fold.uncommitted ? 'fold' : 'expand'}.`;
  ucChip.setAttribute('aria-expanded', String(local.fold.uncommitted));
  ucChip.dataset.dirty = String((s.uncommitted?.total ?? 0) > 0);
  uncommittedBox.hidden = !s.ticket || !local.fold.uncommitted;
  if (!uncommittedBox.hidden) renderUncommitted(uncommittedBox, s.uncommitted, local.fold.allSeats, post, all => {
    local.fold.allSeats = all;
    persist();
    renderBands();
    uncommittedBox.querySelector<HTMLElement>('#uncommitted-all')?.focus();
  });
  const epicOpen = s.ticket?.kind === 'epic';
  ulChip.hidden = !epicOpen;
  const ul = unlinkedLabel(s);
  ulChip.textContent = ul.text;
  ulChip.setAttribute('aria-label', ul.aria);
  ulChip.title = `${ul.aria}. Click to ${local.fold.unlinked ? 'fold' : 'expand'}.`;
  ulChip.setAttribute('aria-expanded', String(local.fold.unlinked));
  unlinkedBox.hidden = !epicOpen || !local.fold.unlinked;
  if (!unlinkedBox.hidden) renderUnlinked(unlinkedBox, s, post);
}

/** 2 lines empty, one more per line of text, 8 at most; then it scrolls. */
function grow() {
  const cs = getComputedStyle(ta);
  const line = parseFloat(cs.lineHeight) || 18;
  const pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
  ta.style.height = 'auto';
  const max = line * MAX_ROWS + pad;
  const h = Math.max(line * MIN_ROWS + pad, Math.min(ta.scrollHeight, max));
  ta.style.height = `${Math.ceil(h)}px`;
  ta.style.overflowY = ta.scrollHeight > max + 1 ? 'auto' : 'hidden';
}

function renderTo() {
  const cur = toSel.value;
  toSel.replaceChildren(new Option('to: thread', ''));
  for (const p of state?.people ?? []) toSel.append(new Option(`to: ${p.handle} (${p.type === 'human' ? 'human' : p.role})`, p.id));
  toSel.value = [...toSel.options].some(o => o.value === cur) ? cur : '';
}

const PLACEHOLDER = ta.placeholder;
function renderChip() {
  const c = state?.ticket ? state.chip : null;
  chipBox.replaceChildren();
  chipBox.hidden = !c;
  ta.placeholder = c ? 'Add a note about the tagged lines… @ to mention' : PLACEHOLDER;
  // a screen reader hears the chip whenever it lands in the composer (C4 review #4)
  ta.setAttribute('aria-describedby', c ? 'ac-status code-chip-label' : 'ac-status');
  if (!c) return;
  const head = el('div', 'chip-head');
  const label = el('code', 'chip-label', c.label);
  label.id = 'code-chip-label';
  const meta = el('span', 'chip-meta', `${c.lines} ${c.lines === 1 ? 'line' : 'lines'}${c.truncated ? ' · snippet truncated to 4096 B' : ''}`);
  const x = el('button', 'chip-remove', '×');
  x.type = 'button';
  x.id = 'code-chip-remove';
  x.title = 'Remove the tagged lines';
  x.setAttribute('aria-label', `Remove the tagged lines ${c.label}`);
  x.addEventListener('click', () => dropChip());
  head.append(label, meta, x);
  chipBox.append(head, el('pre', 'chip-preview', c.preview));
}

function dropChip() {
  const s = state;
  if (!s?.ticket || !s.chip) return;
  const label = s.chip.label;
  post({ type: 'dropCode', ticketId: s.ticket.id, chipId: s.chip.id });
  s.chip = null;
  renderChip();
  acStatus.textContent = `Removed the tagged lines ${label}`;
  ta.focus();
}

function renderAll() {
  const s = state!;
  renderHeader();
  setFeed(s.feed);
  notice.replaceChildren();
  notice.hidden = !s.notice;
  if (s.notice) {
    notice.append(el('span', '', s.notice));
    if (s.feed === 'signed-out') {
      const b = el('button', 'signin', 'Sign in');
      b.addEventListener('click', () => post({ type: 'signIn' }));
      notice.append(b);
    }
  }
  renderStories();
  renderTo();
  olderBtn.hidden = !s.hasOlder;
  olderBtn.disabled = false;
  sendBtn.disabled = pendingTicket !== null;
  renderItems(s.items);
  renderCommits(s, list, post);
  renderBands();
  composer.hidden = !s.ticket;
  renderChip();
  ta.value = s.ticket ? local.drafts[s.ticket.id] ?? '' : '';
  kindSel.value = local.kind;
  grow();
  timeline.setAttribute('aria-live', 'off'); // the initial state is not announced
  toBottom();
}

// -- autocomplete (WAI-ARIA listbox half; strategyll-86c5b5068f §1) ------------------------------------
let acItems: PersonRow[] = [];
let acActive = 0;
let acRange: { start: number; end: number } | null = null;

function acClose() {
  peopleList.hidden = true;
  ta.removeAttribute('aria-activedescendant');
  acItems = [];
  acRange = null;
}

function acRender() {
  peopleList.replaceChildren(...acItems.map((p, i) => {
    const li = el('li', `opt${i === acActive ? ' active' : ''}`);
    li.id = `p-${i}`;
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', String(i === acActive));
    li.setAttribute('aria-label', accessibleName(p));
    li.dataset.handle = p.handle;
    li.append(el('span', 'h', `@${p.handle}`), el('span', `d ${p.type}`, p.detail));
    li.addEventListener('mousedown', e => { e.preventDefault(); acActive = i; acAccept(); });
    return li;
  }));
  ta.setAttribute('aria-activedescendant', `p-${acActive}`);
  peopleList.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
}

function acUpdate() {
  const caret = ta.selectionStart ?? ta.value.length;
  const m = ta.selectionStart === ta.selectionEnd ? activeMention(ta.value, caret) : undefined;
  if (!m || !state) return acClose();
  const items = filterPeople(state.people, m.query);
  if (!items.length) return acClose();
  const wasOpen = !peopleList.hidden;
  acItems = items;
  acRange = { start: m.start, end: caret };
  if (!wasOpen || acActive >= items.length) acActive = 0;
  peopleList.hidden = false;
  acRender();
  acStatus.textContent = `${items.length} ${items.length === 1 ? 'person' : 'people'}`;
}

function acAccept() {
  const p = acItems[acActive];
  if (!p || !acRange) return acClose();
  const ins = `@${p.handle} `;
  const v = ta.value;
  ta.value = v.slice(0, acRange.start) + ins + v.slice(acRange.end);
  const c = acRange.start + ins.length;
  ta.setSelectionRange(c, c);
  acClose();
  saveDraft();
  grow();
  ta.focus();
}

function saveDraft() {
  if (!state?.ticket) return;
  if (ta.value) local.drafts[state.ticket.id] = ta.value; else delete local.drafts[state.ticket.id];
  persist();
}

ta.addEventListener('input', () => { saveDraft(); grow(); acUpdate(); sendErr.textContent = ''; });
ta.addEventListener('click', acUpdate);
ta.addEventListener('blur', () => setTimeout(acClose, 0));
ta.addEventListener('keydown', e => {
  if (e.isComposing || e.keyCode === 229) return; // IME: never send or pick mid-composition
  const open = !peopleList.hidden && acItems.length > 0;
  if (open) {
    if (e.key === 'ArrowDown') { e.preventDefault(); acActive = (acActive + 1) % acItems.length; acRender(); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); acActive = (acActive - 1 + acItems.length) % acItems.length; acRender(); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); acAccept(); return; }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); acClose(); return; }
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
ta.addEventListener('keyup', e => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) acUpdate(); });

function send() {
  if (pendingTicket || !state?.ticket) return;
  const text = ta.value;
  if (!text.trim()) { if (state.chip) sendErr.textContent = 'Add a note about the tagged lines.'; return; }
  if (text.length > TEXT_MAX) { sendErr.textContent = `Too long: ${text.length} of ${TEXT_MAX} characters.`; return; }
  pendingTicket = state.ticket.id;
  sendBtn.disabled = true;
  sendErr.textContent = '';
  post({ type: 'send', ticketId: pendingTicket, text, kind: kindSel.value as SendKind, ...(toSel.value ? { to: toSel.value } : {}),
    ...(state.chip ? { chipId: state.chip.id } : {}) });
}

composer.addEventListener('submit', e => { e.preventDefault(); send(); });
kindSel.addEventListener('change', () => { local.kind = kindSel.value as SendKind; persist(); });
pickBtn.addEventListener('click', () => post({ type: 'pickTicket' }));
back.addEventListener('click', () => { if (state?.epic) post({ type: 'pickTicket', id: state.epic.id }); });
storiesBtn.addEventListener('click', e => { e.stopPropagation(); setStoriesOpen(strip.hidden === true, e.detail === 0); });
strip.addEventListener('click', e => { if ((e.target as HTMLElement).closest('.story')) setStoriesOpen(false); });
strip.addEventListener('keydown', e => {
  const rows = [...strip.querySelectorAll<HTMLElement>('.story')];
  const i = rows.indexOf(document.activeElement as HTMLElement);
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setStoriesOpen(false); storiesBtn.focus(); }
  else if (e.key === 'ArrowDown' && rows.length) { e.preventDefault(); rows[(i + 1) % rows.length].focus(); }
  else if (e.key === 'ArrowUp' && rows.length) { e.preventDefault(); rows[(i - 1 + rows.length) % rows.length].focus(); }
});
// focus leaving the dropdown (Tab / Shift+Tab) closes it, unless it went back to its own toggle
strip.addEventListener('focusout', e => { const to = e.relatedTarget as Node | null; if (to && !strip.contains(to) && to !== storiesBtn) setStoriesOpen(false); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !strip.hidden) { e.preventDefault(); setStoriesOpen(false); storiesBtn.focus(); } });
document.addEventListener('click', e => { if (!strip.hidden && !strip.contains(e.target as Node)) setStoriesOpen(false); });
ucChip.addEventListener('click', () => { local.fold.uncommitted = !local.fold.uncommitted; persist(); if (state) renderBands(); });
ulChip.addEventListener('click', () => { local.fold.unlinked = !local.fold.unlinked; persist(); if (state) renderBands(); });
olderBtn.addEventListener('click', () => { olderBtn.disabled = true; post({ type: 'loadOlder' }); });

// -- host messages -----------------------------------------------------------------------------------
window.addEventListener('message', (ev: MessageEvent) => {
  const m = ev.data as HostToView;
  if (!m || typeof m !== 'object' || m.v !== 1) return;
  switch (m.type) {
    case 'state':
      state = m; // a send in flight stays in flight: its answer still comes
      renderAll();
      break;
    case 'append': {
      if (!state || state.ticket?.id !== m.ticketId) return;
      const have = new Set(state.items.map(i => i.id));
      const fresh = m.items.filter(i => !have.has(i.id));
      if (!fresh.length) return;
      const stick = nearBottom();
      timeline.setAttribute('aria-live', 'polite');
      list.querySelector('.empty')?.remove();
      const k = known();
      for (const i of fresh) {
        // in time order: a late arrival goes before the first message that is newer than it
        const t = Date.parse(i.created_at);
        const idx = state.items.findIndex(x => Date.parse(x.created_at) > t);
        const node = messageEl(i, k);
        if (idx < 0) { state.items.push(i); list.append(node); continue; }
        const next = list.querySelector(`.msg[data-id="${state.items[idx].id}"]`);
        state.items.splice(idx, 0, i);
        if (next) list.insertBefore(node, next); else list.append(node);
      }
      if (stick) toBottom();
      break;
    }
    case 'prepend': {
      if (!state || state.ticket?.id !== m.ticketId) return;
      const have = new Set(state.items.map(i => i.id));
      const fresh = m.items.filter(i => !have.has(i.id));
      state.items.unshift(...fresh);
      state.hasOlder = m.hasOlder;
      olderBtn.hidden = !m.hasOlder;
      olderBtn.disabled = false;
      const h0 = timeline.scrollHeight;
      timeline.setAttribute('aria-live', 'off');
      const k = known();
      list.prepend(...fresh.map(i => messageEl(i, k)));
      placeCards(list);
      timeline.scrollTop += timeline.scrollHeight - h0;
      break;
    }
    case 'commits': {
      if (!state || state.ticket?.id !== m.ticketId) return;
      const stick = nearBottom();
      timeline.setAttribute('aria-live', 'polite');
      list.querySelector('.empty')?.remove();
      appendCommits(state, m.items, list, post);
      if (appendUnlinked(state, m.unlinked)) renderBands();
      if (stick) toBottom();
      break;
    }
    case 'uncommitted':
      if (!state) return;
      state.uncommitted = m.card;
      renderBands();
      break;
    case 'stories':
      if (!state) return;
      state.stories = m.stories;
      renderStories();
      break;
    case 'feed':
      if (state) state.feed = m.status;
      setFeed(m.status);
      break;
    case 'sent':
      if (m.ticketId !== pendingTicket) return;
      pendingTicket = null;
      sendBtn.disabled = false;
      delete local.drafts[m.ticketId];
      persist();
      if (state?.ticket?.id === m.ticketId) { ta.value = ''; grow(); }
      break;
    case 'sendFailed':
      if (pendingTicket && m.ticketId !== pendingTicket) return;
      pendingTicket = null;
      sendBtn.disabled = false;
      if (state?.ticket?.id === m.ticketId) sendErr.textContent = m.text; // the draft stays in the composer
      break;
    case 'insertCode':
      if (!state || state.ticket?.id !== m.ticketId) return; // the host re-sends it in the next state
      state.chip = m.chip;
      renderChip();
      if (m.chip && m.focus) {
        acStatus.textContent = `Tagged lines ${m.chip.label} will be sent with this message`;
        ta.focus(); const c = ta.value.length; ta.setSelectionRange(c, c);
      }
      break;
    case 'error':
      olderBtn.disabled = false;
      notice.hidden = false;
      notice.replaceChildren(el('span', 'err', m.text));
      break;
  }
});

post({ type: 'ready' });
