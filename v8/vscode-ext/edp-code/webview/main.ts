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
import { applyKinds, forgetMisses, markPaths, onPathClick, PathPicker } from './pathTags';
import { commitCount, insertByTime, markerEl, mergeCommits, mergeUnlinked, placeMarkers, renderMarkers } from './cards';
import { markSeen, restoreLocal } from '../src/core/viewState';
import { initAttach } from './attach';
import { TabBar, type TabCtx } from './tabs';
import { TABS } from './registry';
import { inboxDone } from './views/inbox';
import { isSendKey, sendChord } from '../src/core/composerKeys';
import { excerpt, replyRef, type ReplyRef } from '../src/core/reply';
import { MessageQuoter, QuoteChips, quoteCards } from './quotes';

declare function acquireVsCodeApi(): { postMessage(m: unknown): void; getState(): unknown; setState(s: unknown): void };
const vscode = acquireVsCodeApi();

// drafts, kind, the active tab, what is folded and the commits seen (C9, C13): per viewer, in the webview
// state only, never on the board
const local = restoreLocal(vscode.getState());
const persist = () => vscode.setState(local);

let state: ChatState | null = null;
/** the thread a send is in flight for: its answer (sent / sendFailed) names the same ticket */
let pendingTicket: string | null = null;
/** C22: the reply target that send carried; its `sent` clears only that target, never one set while it was in flight */
let pendingReply: ReplyRef | null = null;
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
// C14 (owner m-db09472a68): the board UI's chord; Enter is a newline
ta.placeholder = `Message… @ to mention, # for a file or folder · ${sendChord(navigator.platform || navigator.userAgent)} to send`;
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
sendBtn.title = `Send (${sendChord(navigator.platform || navigator.userAgent)})`;
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
// C22: "Replying to @author: excerpt ×" above the text; × or Escape stops replying
const replyBar = el('div', 'reply-bar');
replyBar.id = 'reply-bar';
replyBar.setAttribute('role', 'group');
replyBar.setAttribute('aria-label', 'Replying to');
replyBar.hidden = true;
// C20: the draft quotes (quote + note from code, docs and messages) above the text, in send order
const quoteChips = new QuoteChips(m => post(m), acStatus);
cbox.append(replyBar, quoteChips.box, chipBox, ta, tools);
composer.append(peopleList, cbox, acStatus, sendErr);

// C11: the # picker (files and folders) beside the @ list, and its button in C9's tool slot
const pathPicker = new PathPicker(ta, m => post(m), acStatus, () => { saveDraft(); grow(); });
composer.prepend(pathPicker.list);
const hashBtn = el('button', 'tool hash', '#');
hashBtn.id = 'tag-path';
hashBtn.type = 'button';
hashBtn.title = 'Tag a file or folder (#)';
hashBtn.setAttribute('aria-label', 'Tag a file or folder');
hashBtn.addEventListener('mousedown', e => e.preventDefault()); // keep the caret where it is
hashBtn.addEventListener('click', () => pathPicker.insertHash());
toolSlot.append(hashBtn);

// C12: attachments: the clip button in the tool slot, drop onto the box, paste into the text, and the staged list
const attach = initAttach({ box: cbox, slot: toolSlot, ta, err: sendErr, status: acStatus, ticket: () => state?.ticket?.id ?? null,
  post: m => post(m), onChange: () => { sendBtn.disabled = pendingTicket !== null || attach.busy(); } });

// C13: the tab bar under the header; every tab's panel fills the rest of the height, so no band competes
// with the thread for it (C9's chips were squeezed to nothing by a long thread: flex-shrink by basis)
// C20: Quote + note on a selection inside a message (a button by the selection, or Ctrl+Alt+Q)
const quoter = new MessageQuoter(list, () => state?.ticket?.id ?? null, m => post(m), acStatus);
let chatUnread = 0;
/** the Chat timeline's scroll when the user left it away from the bottom (null: it follows the bottom) */
let chatScroll: number | null = null;
let focusSha: string | undefined;
const tabs = new TabBar(TABS, local.tab, id => select(id));
tabs.panelOf('chat').append(timeline, composer);
app.append(header, tabs.bar, notice, tabs.panels);

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
  // C22: Reply on every message (shown on hover or focus; always in the tab order)
  const reply = el('button', 'reply', '↩ Reply');
  reply.type = 'button';
  reply.title = `Reply to ${m.created_by}`;
  reply.setAttribute('aria-label', `Reply to ${m.created_by}`);
  reply.addEventListener('click', () => startReply(m));
  const open = el('button', 'board-link', '↗');
  open.title = 'Open on the board';
  open.setAttribute('aria-label', 'Open on the board');
  open.addEventListener('click', () => post({ type: 'openBoard', ticketId: m.ticket_id, messageId: m.id }));
  h.append(t, reply, open);
  const body = el('div', 'body');
  body.append(bodyFragment(document, m.text, k));
  markPaths(body, post); // C11: backticked paths that exist here become links
  a.append(h);
  if (m.reply_to) a.append(parentLine(m));
  const qc = quoteCards(m, post); // C20: the quoted passages sit above the text
  if (qc) a.append(qc);
  a.append(body);
  if (m.code_context) a.append(codeCard(m));
  const atts = attach.render(m); // C12
  if (atts) a.append(atts);
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

// -- replies (C22 s-3b86872bf0) -----------------------------------------------------------------------
/** A reply's parent line: "replying to @author: excerpt". Clicking it shows the parent: scrolled to here when it is
 *  loaded, else the host loads older pages until it is (then answers `focusMessage`). */
function parentLine(m: ChatMessage): HTMLElement {
  const b = el('button', 'reply-quote');
  b.type = 'button';
  b.dataset.parent = m.reply_to!;
  fillParent(b);
  b.addEventListener('click', () => {
    if (!focusMsg(m.reply_to!) && state?.ticket) post({ type: 'showMessage', ticketId: state.ticket.id, messageId: m.reply_to! });
  });
  return b;
}

function fillParent(b: HTMLElement): void {
  const id = b.dataset.parent!;
  const p = state?.items.find(i => i.id === id);
  const who = p ? (p.created_by === state?.me?.id || p.created_by === state?.me?.handle ? 'you' : `@${p.created_by}`) : null;
  b.replaceChildren(el('span', 'rq-who', who ? `↳ replying to ${who}:` : '↳ replying to an earlier message'), el('span', 'rq-text', p ? excerpt(p.text) : 'load it'));
  b.title = p ? `Show the message it replies to (${id})` : `Load older messages until ${id} shows`;
  b.classList.toggle('unloaded', !p);
}

/** Scroll a loaded message into view, mark and focus it; false when it is not in the list. */
function focusMsg(id: string): boolean {
  const node = list.querySelector<HTMLElement>(`.msg[data-id="${CSS.escape(id)}"]`);
  if (!node) return false;
  list.querySelector('.msg.focus-source')?.classList.remove('focus-source');
  node.classList.add('focus-source');
  node.tabIndex = -1;
  node.scrollIntoView({ block: 'center' });
  node.focus({ preventScroll: true });
  return true;
}

const replyOf = () => (state?.ticket ? local.replies[state.ticket.id] ?? null : null);

function startReply(m: ChatMessage): void {
  if (!state?.ticket || m.ticket_id !== state.ticket.id) return;
  delete local.replies[state.ticket.id]; // re-inserted last: the newest targets are the ones kept
  local.replies[state.ticket.id] = replyRef(m);
  persist();
  renderTo();
  renderReply();
  select('chat');
  ta.focus();
  acStatus.textContent = `Replying to ${m.created_by}`;
}

function cancelReply(): void {
  const t = state?.ticket?.id;
  if (!t || !local.replies[t]) return;
  delete local.replies[t];
  persist();
  renderReply();
  toSel.value = '';
  acStatus.textContent = 'Stopped replying';
  ta.focus();
}

function renderReply(): void {
  const r = replyOf();
  replyBar.replaceChildren();
  replyBar.hidden = !r;
  if (!r) return;
  const x = el('button', 'reply-cancel', '×');
  x.type = 'button';
  x.id = 'reply-cancel';
  x.title = 'Stop replying (Escape)';
  x.setAttribute('aria-label', 'Stop replying');
  x.addEventListener('click', () => cancelReply());
  const go = el('button', 'reply-target');
  go.type = 'button';
  go.title = `Show the message (${r.id})`;
  go.append(el('span', 'rb-who', `Replying to @${r.by}:`), el('span', 'rb-text', r.excerpt));
  go.addEventListener('click', () => { if (!focusMsg(r.id) && state?.ticket) post({ type: 'showMessage', ticketId: state.ticket.id, messageId: r.id }); });
  replyBar.append(go, x);
  if ([...toSel.options].some(o => o.value === r.to)) toSel.value = r.to;
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

// -- tabs (C13) ---------------------------------------------------------------------------------------
function tabCtx(): TabCtx | null {
  if (!state) return null;
  const c: TabCtx = { state, local, post: m => post(m), persist, select: (id, o) => select(id, o), chatUnread, focusSha };
  return c;
}

/** Render the active tab (Chat renders itself) and every badge. */
function renderTab() {
  const c = tabCtx();
  tabs.bar.hidden = !state?.ticket;
  if (c && state?.ticket && tabs.current !== 'chat') {
    TABS.find(t => t.id === tabs.current)!.render(tabs.panelOf(tabs.current), c);
    focusSha = c.focusSha; // the Commits tab consumed it
  }
  tabs.badges(tabCtx());
}

function badges() { tabs.badges(tabCtx()); }

function select(id: string, o: { focus?: boolean; sha?: string } = {}) {
  if (!tabs.has(id)) return;
  const from = tabs.current;
  if (from === 'chat' && id !== 'chat') chatScroll = nearBottom() ? null : timeline.scrollTop;
  local.tab = id;
  persist();
  if (id === 'chat') chatUnread = 0;
  if (o.sha) focusSha = o.sha;
  tabs.show(id, o.focus);
  if (id === 'chat' && from !== 'chat') { if (chatScroll === null) toBottom(); else timeline.scrollTop = chatScroll; }
  renderTab();
}

/** A Chat marker: open the commit in the Commits tab, expanded and focused. */
const jump = (sha: string) => select('commits', { sha });

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

/** the thread the To select was last rendered for: a To chosen in one thread never carries into another */
let toThread: string | null = null;
function renderTo() {
  const t = state?.ticket?.id ?? null;
  const cur = toThread === t ? toSel.value : '';
  toThread = t;
  toSel.replaceChildren(new Option('to: thread', ''));
  for (const p of state?.people ?? []) toSel.append(new Option(`to: ${p.handle} (${p.type === 'human' ? 'human' : p.role})`, p.id));
  // C22: the reply's author (and the To chosen for it) when the people list does not name them (a closed seat),
  // but only while they wrote a loaded message: exactly what the host accepts as `to` (ChatController.handles)
  const r = replyOf();
  const have = (v: string) => [...toSel.options].some(o => o.value === v);
  const loaded = new Set((state?.items ?? []).map(i => i.created_by));
  for (const v of r ? [r.by, r.to] : []) if (v && !have(v) && loaded.has(v)) toSel.append(new Option(`to: ${v}`, v));
  toSel.value = r ? (have(r.to) ? r.to : '') : have(cur) ? cur : '';
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
  renderMarkers(s.commits, list, jump);
  composer.hidden = !s.ticket;
  attach.reset(s.ticket?.id ?? null, s.pending ?? [], s.artifacts ?? []);
  renderChip();
  renderReply();
  quoteChips.render(s.ticket?.id ?? null, s.ticket ? s.quotes ?? [] : []);
  quoter.close();
  ta.value = s.ticket ? local.drafts[s.ticket.id] ?? '' : '';
  kindSel.value = local.kind;
  grow();
  timeline.setAttribute('aria-live', 'off'); // the initial state is not announced
  toBottom();
  chatScroll = null;
  // a scope seen for the first time: its commits so far are not "new"; the badge counts later ones
  if (s.ticket && !(s.ticket.id in local.seen) && markSeen(local, s.ticket.id, s.commits)) persist();
  renderTab();
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

ta.addEventListener('input', () => { saveDraft(); grow(); acUpdate(); pathPicker.update(); sendErr.textContent = ''; });
ta.addEventListener('click', () => { acUpdate(); pathPicker.update(); });
ta.addEventListener('blur', () => setTimeout(() => { acClose(); pathPicker.close(); }, 0));
ta.addEventListener('keydown', e => {
  if (e.isComposing || e.keyCode === 229) return; // IME: never send or pick mid-composition
  if (pathPicker.onKey(e)) return; // the # list takes the keys while it is open, as the @ list does
  const open = !peopleList.hidden && acItems.length > 0;
  if (open) {
    if (e.key === 'ArrowDown') { e.preventDefault(); acActive = (acActive + 1) % acItems.length; acRender(); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); acActive = (acActive - 1 + acItems.length) % acItems.length; acRender(); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); acAccept(); return; }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); acClose(); return; }
  }
  if (isSendKey(e)) { e.preventDefault(); send(); } // a plain Enter inserts a newline (the textarea's default)
});
ta.addEventListener('keyup', e => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) { acUpdate(); pathPicker.update(); } });
onPathClick(list, post);

function send() {
  if (pendingTicket || !state?.ticket) return;
  const text = ta.value;
  const files = attach.ids();
  quoteChips.flush(); // a note still being typed goes before the send that carries it
  const quotes = quoteChips.keys;
  if (attach.busy()) { sendErr.textContent = 'Wait for the attachments to finish uploading.'; return; }
  if (!text.trim() && !files.length && !quotes.length) { if (state.chip) sendErr.textContent = 'Add a note about the tagged lines.'; return; }
  if (!text.trim() && state.chip) { sendErr.textContent = 'Add a note about the tagged lines.'; return; }
  if (text.length > TEXT_MAX) { sendErr.textContent = `Too long: ${text.length} of ${TEXT_MAX} characters.`; return; }
  pendingTicket = state.ticket.id;
  sendBtn.disabled = true;
  sendErr.textContent = '';
  const reply = replyOf();
  pendingReply = reply;
  post({ type: 'send', ticketId: pendingTicket, text, kind: kindSel.value as SendKind, ...(toSel.value ? { to: toSel.value } : {}),
    ...(reply ? { replyTo: reply.id } : {}),
    ...(state.chip ? { chipId: state.chip.id } : {}), ...(files.length ? { attachmentIds: files } : {}), ...(quotes.length ? { quoteKeys: quotes } : {}) });
}

composer.addEventListener('submit', e => { e.preventDefault(); send(); });
// Escape anywhere in the composer stops replying, once the @ and # lists have had it (they preventDefault)
composer.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing || !replyOf()) return;
  e.preventDefault(); e.stopPropagation(); cancelReply();
});
kindSel.addEventListener('change', () => { local.kind = kindSel.value as SendKind; persist(); });
toSel.addEventListener('change', () => { const r = replyOf(); if (r) { r.to = toSel.value; persist(); } });
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
olderBtn.addEventListener('click', () => { olderBtn.disabled = true; post({ type: 'loadOlder' }); });

// -- host messages -----------------------------------------------------------------------------------
window.addEventListener('message', (ev: MessageEvent) => {
  const m = ev.data as HostToView;
  if (!m || typeof m !== 'object' || m.v !== 1) return;
  switch (m.type) {
    case 'state':
      forgetMisses(); // a path created since is asked about again
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
      if (tabs.current !== 'chat') { chatUnread += fresh.length; badges(); }
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
      // C22: replies whose parent just loaded show its excerpt now
      for (const b of list.querySelectorAll<HTMLElement>('.reply-quote.unloaded')) fillParent(b);
      if (replyOf()) renderTo(); // a restored reply's author may be reachable now
      placeMarkers(list);
      timeline.scrollTop += timeline.scrollHeight - h0;
      break;
    }
    case 'commits': {
      if (!state || state.ticket?.id !== m.ticketId) return;
      const { all, fresh } = mergeCommits(state.commits ?? [], m.items);
      state.commits = all;
      const un = state.ticket.kind === 'epic' ? mergeUnlinked(state.unlinked ?? [], m.unlinked) : null;
      if (un) state.unlinked = un;
      const mine = fresh.filter(c => c.thread);
      if (mine.length) {
        const stick = nearBottom();
        timeline.setAttribute('aria-live', 'polite');
        list.querySelector('.empty')?.remove();
        for (const c of [...mine].reverse()) insertByTime(list, markerEl(c, jump));
        if (stick) toBottom();
      }
      if (tabs.current === 'commits') renderTab(); else badges();
      break;
    }
    case 'uncommitted':
      if (!state) return;
      state.uncommitted = m.card;
      if (tabs.current === 'changes') renderTab(); else badges();
      break;
    case 'stories':
      if (!state) return;
      state.stories = m.stories;
      renderStories();
      if (tabs.current === 'commits') renderTab(); // the epic's cards are labelled by story title
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
      // C22: the reply went (a failed send keeps it); a Reply picked while it was in flight stays
      const replied = !!pendingReply && local.replies[m.ticketId] === pendingReply;
      if (replied) delete local.replies[m.ticketId];
      pendingReply = null;
      persist();
      if (state?.ticket?.id === m.ticketId) {
        ta.value = ''; grow();
        if (replied) { renderReply(); renderTo(); toSel.value = ''; }
      }
      break;
    case 'sendFailed':
      if (pendingTicket && m.ticketId !== pendingTicket) return;
      pendingTicket = null;
      pendingReply = null;
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
    case 'paths':
      pathPicker.onPaths(m);
      break;
    case 'pathKinds':
      applyKinds(list, m);
      break;
    case 'pending': // C12
      if (state?.ticket?.id === m.ticketId) state.pending = m.pending;
      attach.setPending(m.ticketId, m.pending);
      break;
    case 'attachFailed':
      attach.failed(m.ticketId, m.text);
      break;
    case 'artifacts':
      attach.infos(m.items);
      break;
    case 'inbox': { // C15: the open scope's list, re-read
      if (!state || state.ticket?.id !== m.ticketId) return;
      const panel = tabs.panelOf('inbox');
      panel.dataset.reads = String(Number(panel.dataset.reads ?? 0) + 1); // a settle signal for the smoke
      // an unchanged re-read never rebuilds the rows: a button under the pointer stays the same button
      if (JSON.stringify(state.inbox) === JSON.stringify(m.inbox)) return;
      state.inbox = m.inbox;
      if (tabs.current === 'inbox') renderTab(); else badges();
      break;
    }
    case 'docs': { // C16: the open scope's linked docs, re-read
      if (!state || state.ticket?.id !== m.ticketId) return;
      const panel = tabs.panelOf('docs');
      panel.dataset.reads = String(Number(panel.dataset.reads ?? 0) + 1);
      if (JSON.stringify(state.docs) === JSON.stringify(m.docs)) return;
      state.docs = m.docs;
      if (tabs.current === 'docs') renderTab(); else badges();
      break;
    }
    case 'decisions': { // C17: the open scope's decision records, re-read
      if (!state || state.ticket?.id !== m.ticketId) return;
      const panel = tabs.panelOf('decisions');
      panel.dataset.reads = String(Number(panel.dataset.reads ?? 0) + 1);
      if (JSON.stringify(state.decisions) === JSON.stringify(m.decisions)) return;
      state.decisions = m.decisions;
      if (tabs.current === 'decisions') renderTab(); else badges();
      break;
    }
    case 'focusMessage': { // C17: a decision's source message, now in the open thread
      if (!state || state.ticket?.id !== m.ticketId) return;
      select('chat');
      focusMsg(m.id);
      break;
    }
    case 'quotes': { // C20: the thread's draft quotes changed (added from an editor, the reader or a message)
      if (m.text) { acStatus.textContent = m.text; if (m.text.startsWith('Not ')) sendErr.textContent = m.text; }
      if (!state || state.ticket?.id !== m.ticketId) return;
      state.quotes = m.quotes;
      quoteChips.render(m.ticketId, m.quotes);
      if (m.focus) { select('chat'); sendErr.textContent = ''; }
      break;
    }
    case 'inboxDone':
      inboxDone(state, local, m);
      persist();
      if (tabs.current === 'inbox') renderTab(); else badges();
      break;
    case 'error':
      olderBtn.disabled = false;
      notice.hidden = false;
      notice.replaceChildren(el('span', 'err', m.text));
      break;
  }
});

post({ type: 'ready' });
