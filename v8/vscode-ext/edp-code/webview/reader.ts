// The EDP reader editor tab (C16 s-579fa02cca; design-10b21760d9 §14.2, §14.7): one board doc at one version,
// rendered from the host's data (the webview never fetches), with an outline, a version picker, Compare / Source /
// Full screen, the design review (Approve / Request changes, only when the board says can_approve), a proposed
// strategy doc's Approve / Reject with its diff against the active doc, and the version's comments. Enter is a
// newline and Ctrl+Enter sends in the feedback box (C14). The selection is posted as a source line range for C20.
import type { HostToReader, ReaderComment, ReaderState, ReaderToHost, ReaderWrite } from '../src/core/reader';
import { approveReason, FEEDBACK_MAX, SIGNOFF_TIP } from '../src/core/reader'; // value imports: core/reader has no vscode or node import
import { isSendKey, sendChord } from '../src/core/composerKeys';
import { diffLines, lineRange, renderDoc } from './readerRender';

declare function acquireVsCodeApi(): { postMessage(m: unknown): void; getState(): unknown; setState(s: unknown): void };
const vscode = acquireVsCodeApi();
type Intent = ReaderToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
const post = (m: Intent) => vscode.postMessage({ v: 1, ...m });

type Local = { outline: boolean; feedback: string };
const saved = (vscode.getState() ?? {}) as Partial<Local>;
const local: Local = { outline: saved.outline !== false, feedback: typeof saved.feedback === 'string' ? saved.feedback.slice(0, 16_384) : '' };
const persist = () => vscode.setState(local);

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const btn = (id: string, label: string, title: string, on: () => void, cls = 'rd-btn') => {
  const b = el('button', cls, label);
  b.type = 'button'; b.id = id; b.title = title;
  b.addEventListener('click', on);
  return b;
};
const chord = () => sendChord(navigator.platform || navigator.userAgent);
const fmtTime = (iso: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

let state: ReaderState | null = null;
let busy: ReaderWrite | null = null;
let outcome: { ok: boolean; text: string } | null = null;
let renderedBody: string | null = null;

const app = document.getElementById('app')!;
const bar = el('header', 'rd-bar');
const layout = el('div', 'rd-layout');
const nav = el('nav', 'rd-outline');
nav.setAttribute('aria-label', 'Outline');
const main = el('main', 'rd-main');
const article = el('article', 'rd-doc');
article.id = 'doc';
const extras = el('div', 'rd-extras');
main.append(article, extras);
layout.append(nav, main);
const status = el('div', 'rd-status');
status.id = 'rd-status';
status.setAttribute('role', 'status');
app.append(bar, status, layout);

function renderBar(): void {
  const s = state, d = s?.doc;
  const out: HTMLElement[] = [];
  const toggle = btn('rd-outline-toggle', '☰', local.outline ? 'Hide the outline' : 'Show the outline', () => {
    local.outline = !local.outline; persist(); renderBar(); layoutOutline();
  }, 'rd-btn rd-icon');
  toggle.setAttribute('aria-pressed', String(local.outline));
  toggle.setAttribute('aria-label', 'Outline');
  out.push(toggle);
  const title = el('h1', 'rd-title', d ? d.title : s?.loading ? 'Reading…' : 'EDP doc');
  title.id = 'rd-title';
  out.push(title);
  if (d) {
    const meta = el('span', 'rd-meta');
    meta.id = 'rd-meta';
    meta.append(el('span', 'rd-type', d.docType), el('span', `rd-state rd-state-${d.status}`, d.status));
    out.push(meta);
    const pick = el('select', 'rd-version');
    pick.id = 'rd-version';
    pick.setAttribute('aria-label', 'Version');
    for (const v of [...d.versions].sort((a, b) => b - a)) {
      const o = el('option', '', `v${v}${v === d.current ? ' (current)' : ''}`);
      o.value = String(v);
      o.selected = v === d.version;
      pick.append(o);
    }
    pick.addEventListener('change', () => post({ type: 'pickVersion', version: Number(pick.value) }));
    out.push(pick);
    // C22: a design says why it shows no Approve, in one line; the tooltip says a design has no Reject
    if (d.docType === 'design') meta.title = SIGNOFF_TIP;
    const why = approveReason(d, s?.gate ?? null);
    if (why) {
      const line = el('span', 'rd-signoff');
      line.id = 'rd-signoff';
      line.title = SIGNOFF_TIP;
      line.setAttribute('role', 'note');
      line.append(el('span', 'rd-signoff-text', why.text));
      if (why.openVersion !== null) {
        const v = why.openVersion;
        line.append(btn('rd-signoff-open', 'open it', `Open v${v}, the version the sign-off is on`, () => post({ type: 'pickVersion', version: v }), 'rd-link'));
      }
      out.push(line);
    }
    const tools = el('span', 'rd-tools');
    if (d.versions.length > 1) tools.append(btn('rd-compare', 'Compare', 'Compare this version with another (diff of the markdown source)', () => post({ type: 'compare' })));
    tools.append(btn('rd-source', 'Source', 'Open the markdown source of this version', () => post({ type: 'source' })));
    tools.append(btn('rd-full', 'Full screen', 'Maximise this editor (again to restore)', () => post({ type: 'fullScreen' })));
    out.push(tools);
  }
  bar.replaceChildren(...out);
}

function layoutOutline(): void {
  nav.hidden = !local.outline || !nav.childElementCount;
  layout.classList.toggle('rd-no-outline', nav.hidden);
}

function renderDocBody(): void {
  const d = state?.doc;
  if (!d) {
    renderedBody = null;
    article.replaceChildren(el('p', 'rd-empty', state?.error ?? (state?.loading ? 'Reading the doc…' : 'No doc.')));
    nav.replaceChildren();
    layoutOutline();
    return;
  }
  const key = `${d.id}@${d.version}\n${d.body}`;
  if (key === renderedBody) return; // an unchanged re-read never rebuilds the doc (keeps scroll and selection)
  renderedBody = key;
  const { frag, outline } = renderDoc(document, d.body);
  article.replaceChildren(frag);
  const list = el('ol', 'rd-toc');
  for (const h of outline) {
    const li = el('li', `rd-toc-l${Math.min(h.level, 4)}`);
    const a = el('a', '', h.text);
    a.href = `#${h.id}`;
    a.dataset.target = h.id;
    li.append(a);
    list.append(li);
  }
  nav.replaceChildren(...(outline.length ? [el('div', 'rd-toc-title', 'Outline'), list] : []));
  layoutOutline();
}

function reviewBox(): HTMLElement | null {
  const s = state, d = s?.doc, g = s?.gate;
  if (!d || !g) return null;
  const box = el('section', 'rd-review');
  box.id = 'rd-review';
  box.setAttribute('aria-label', 'Design review');
  box.append(el('h2', 'rd-h', `Design review · ${g.ticketTitle}`));
  if (!g.canApprove) {
    const why = !g.gateEventId ? 'No design review is open on this design.'
      : !g.canReview ? 'Only the epic\'s owner reviews this design.'
      : d.version !== g.currentVersion ? `You are reading v${d.version}; the design is now v${g.currentVersion}. Review v${g.currentVersion}.`
      : 'The design review is not open for you.';
    box.append(el('p', 'rd-note', why));
    return box;
  }
  box.append(el('p', 'rd-note', `Approve or request changes on v${d.version}, the version shown. The same actions are in the editor title bar.`));
  const ta = el('textarea', 'rd-feedback');
  ta.id = 'rd-feedback';
  ta.rows = 3;
  ta.maxLength = FEEDBACK_MAX;
  ta.value = local.feedback;
  ta.placeholder = `What to change… ${chord()} sends as Request changes`;
  ta.setAttribute('aria-label', 'Feedback for Request changes');
  const send = () => {
    if (!ta.value.trim()) { outcome = { ok: false, text: 'Say what to change: Request changes needs feedback.' }; renderStatus(); ta.focus(); return; }
    // the host drops an over-long intent without a reply, which would leave `busy` set: refuse it here
    if (ta.value.length > FEEDBACK_MAX) { outcome = { ok: false, text: `Too long: ${ta.value.length} of ${FEEDBACK_MAX} characters.` }; renderStatus(); return; }
    if (busy) return;
    busy = 'requestChanges'; outcome = null;
    post({ type: 'requestChanges', feedback: ta.value });
    renderExtras();
  };
  ta.addEventListener('input', () => { local.feedback = ta.value; persist(); });
  ta.addEventListener('keydown', e => {
    if (e.isComposing || e.keyCode === 229) return;
    if (isSendKey(e)) { e.preventDefault(); send(); }
  });
  const acts = el('div', 'rd-actions');
  const ok = btn('rd-approve', `Approve v${d.version}`, `Approve ${d.id} v${d.version}`, () => {
    if (busy) return;
    busy = 'approve'; outcome = null;
    post({ type: 'approve' });
    renderExtras();
  }, 'rd-btn rd-primary');
  const rc = btn('rd-request', 'Request changes', `Send your feedback on v${d.version} to the architect (${chord()})`, send);
  ok.disabled = rc.disabled = busy !== null;
  acts.append(ok, rc);
  box.append(ta, acts);
  return box;
}

function proposalBox(): HTMLElement | null {
  const s = state, d = s?.doc;
  if (!d || !s) return null;
  if (!s.canResolve && !(d.status === 'proposed' && s.diff)) return null;
  const box = el('section', 'rd-proposal');
  box.id = 'rd-proposal';
  box.setAttribute('aria-label', 'Proposed doc');
  const base = s.diff?.baseId ? `${s.diff.baseId} v${s.diff.baseVersion}` : null;
  box.append(el('h2', 'rd-h', base ? `Proposed revision of ${base} (active)` : 'Proposed doc (no active doc to revise)'));
  if (s.canResolve) {
    const acts = el('div', 'rd-actions');
    const ap = btn('rd-resolve-approve', 'Approve', base ? `Approve: ${base} takes this text as its next version` : 'Approve: this doc becomes active', () => {
      if (busy) return; busy = 'resolveApprove'; outcome = null; post({ type: 'resolve', approve: true }); renderExtras();
    }, 'rd-btn rd-primary');
    const rj = btn('rd-resolve-reject', 'Reject', 'Reject: this proposal retires', () => {
      if (busy) return; busy = 'resolveReject'; outcome = null; post({ type: 'resolve', approve: false }); renderExtras();
    });
    ap.disabled = rj.disabled = busy !== null;
    acts.append(ap, rj);
    if (base) acts.append(btn('rd-proposal-diff', 'Open diff', `Open ${base} ↔ this proposal in the diff editor`, () => post({ type: 'openProposalDiff' })));
    box.append(acts);
  }
  if (s.diff) {
    const det = el('details', 'rd-diff');
    det.open = true;
    det.append(el('summary', '', 'Changes against the active doc'));
    const pre = el('pre', 'rd-diff-body');
    pre.id = 'rd-diff';
    for (const l of diffLines(s.diff.text)) pre.append(el('span', `dl dl-${l.cls}`, l.text + '\n'));
    det.append(pre);
    box.append(det);
  }
  return box;
}

function commentRow(c: ReaderComment): HTMLElement {
  const li = el('li', 'rd-comment');
  li.dataset.id = c.id;
  const meta = el('div', 'rd-comment-meta');
  meta.append(el('span', 'by', c.by), el('span', 'rd-kind', c.via === 'quote' ? 'quotes it' : c.kind));
  if (c.at) { const t = el('time', '', fmtTime(c.at)); t.dateTime = c.at; meta.append(t); }
  const body = el('div', 'rd-comment-body');
  body.append(renderDoc(document, c.text).frag);
  li.append(meta, body);
  return li;
}

function commentsBox(): HTMLElement | null {
  const s = state, d = s?.doc;
  if (!d || !s?.comments) return null;
  const box = el('section', 'rd-comments');
  box.id = 'rd-comments';
  const rows = s.comments.rows;
  box.setAttribute('aria-label', `Comments on v${d.version}, ${rows.length}`);
  box.append(el('h2', 'rd-h', `Comments on v${d.version} (${rows.length})`));
  if (s.comments.error) box.append(el('p', 'rd-note', s.comments.error));
  else if (!rows.length) box.append(el('p', 'rd-note', 'No comments on this version.'));
  else { const ol = el('ol', 'rd-comment-list'); ol.append(...rows.map(commentRow)); box.append(ol); }
  return box;
}

function renderExtras(): void {
  // keep the caret in the feedback box across a re-render
  const active = document.activeElement;
  const sel = active instanceof HTMLTextAreaElement && active.id === 'rd-feedback' ? [active.selectionStart, active.selectionEnd] as const : null;
  extras.replaceChildren(...[reviewBox(), proposalBox(), commentsBox()].filter((x): x is HTMLElement => !!x));
  if (sel) { const f = document.getElementById('rd-feedback') as HTMLTextAreaElement | null; f?.focus(); f?.setSelectionRange(sel[0], sel[1]); }
  renderStatus();
}

function renderStatus(): void {
  const s = state;
  const text = outcome?.text ?? (s?.doc && s.error ? s.error : '');
  status.textContent = text;
  status.className = `rd-status${outcome && !outcome.ok ? ' rd-error' : outcome?.ok ? ' rd-ok' : s?.error ? ' rd-error' : ''}`;
  status.hidden = !text;
}

function render(): void { renderBar(); renderDocBody(); renderExtras(); }

// -- the outline and links ----------------------------------------------------------------------------
document.addEventListener('click', e => {
  const a = (e.target as Element | null)?.closest?.('a');
  if (!a) return;
  const target = a.getAttribute('data-target') ?? (a.getAttribute('href')?.startsWith('#') ? a.getAttribute('href')!.slice(1) : null);
  if (target) {
    e.preventDefault();
    const h = document.getElementById(target);
    h?.scrollIntoView({ block: 'start' });
    (h as HTMLElement | null)?.setAttribute('tabindex', '-1');
    (h as HTMLElement | null)?.focus({ preventScroll: true });
    return;
  }
  const href = a.getAttribute('href');
  if (href && /^https?:/i.test(href)) { e.preventDefault(); post({ type: 'openLink', href }); }
});

// -- C20's hook: the selection as source lines ---------------------------------------------------------
let selTimer: ReturnType<typeof setTimeout> | undefined;
let lastSel = '';
document.addEventListener('selectionchange', () => {
  clearTimeout(selTimer);
  selTimer = setTimeout(() => {
    const s = document.getSelection();
    const r = s && s.rangeCount && !s.isCollapsed ? lineRange(s.getRangeAt(0).startContainer, s.getRangeAt(0).endContainer, article) : null;
    const msg = r ? { from: r.from, to: r.to, text: s!.toString() } : { from: 0, to: 0, text: '' };
    const key = `${msg.from}:${msg.to}:${msg.text.length}`;
    if (key === lastSel) return;
    lastSel = key;
    article.dataset.selFrom = String(msg.from);
    article.dataset.selTo = String(msg.to);
    post({ type: 'selection', ...msg });
  }, 150);
});

window.addEventListener('message', (ev: MessageEvent) => {
  const m = ev.data as HostToReader;
  if (!m || m.v !== 1) return;
  if (m.type === 'doc') {
    const moved = state?.doc?.id !== m.doc?.id || state?.doc?.version !== m.doc?.version;
    state = m;
    if (moved) { busy = null; }
    render();
    document.body.dataset.loaded = m.loading ? 'no' : 'yes';
    return;
  }
  if (m.type === 'done') {
    busy = null;
    outcome = { ok: m.ok, text: m.text };
    if (m.ok && m.what === 'requestChanges') { local.feedback = ''; persist(); }
    renderExtras();
  }
});

render();
post({ type: 'ready' });
