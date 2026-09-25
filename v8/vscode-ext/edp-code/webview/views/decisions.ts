// The Decisions tab (C17 s-5e83f9d0af; design-10b21760d9 §14.2, §14.4): the picked scope's decision records (owner
// m-db09472a68: a sixth tab, always scoped), live binding ones first, then newest; withdrawn ones stay listed,
// dimmed, with their reason. A row's source opens in Chat (a message) or the EDP reader (a doc). Withdraw and
// Binding on/off show only when the board said the viewer may manage (owner/architect); the host asks the reason.
// Rows come from the host; the view names a decision by id only. The badge counts live decisions.
import { decisionsBadge, rowActions, type DecisionRow } from '../../src/core/decisions';
import { action, type Tab, type TabCtx } from '../tabs';

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const domKey = (id: string) => id.replace(/[^A-Za-z0-9_-]/g, '_');

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function decisionRow(r: DecisionRow, ctx: TabCtx): HTMLElement {
  const st = ctx.state.decisions!;
  const k = domKey(r.id);
  const row = el('article', `de-row de-${r.status}${r.binding ? ' de-binding' : ''}`);
  row.id = `de-${k}`;
  row.dataset.id = r.id;
  const head = el('div', 'de-head');
  if (r.binding) head.append(el('span', 'de-flag de-flag-binding', 'binding'));
  if (r.status === 'withdrawn') head.append(el('span', 'de-flag de-flag-withdrawn', 'withdrawn'));
  head.append(el('span', 'de-text', r.text));
  row.append(head);
  if (r.detail) row.append(el('div', 'de-detail', r.detail));
  if (r.status === 'withdrawn' && r.withdrawnReason) row.append(el('div', 'de-reason', `Withdrawn: ${r.withdrawnReason}`));
  const meta = el('div', 'de-meta');
  const t = el('time', 'de-at', when(r.decidedAt));
  t.dateTime = r.decidedAt;
  meta.append(el('span', 'de-by', r.decidedBy || 'unknown'), t, el('span', 'de-id', r.id));
  if (r.scope && r.scope !== ctx.state.ticket?.id) {
    const title = ctx.state.stories.find(s => s.id === r.scope)?.title;
    meta.append(el('span', 'de-scope', title ? `on ${title}` : `on ${r.scope}`));
  }
  if (r.replaces.length) meta.append(el('span', 'de-replaces', `replaces ${r.replaces.join(', ')}`));
  if (r.sourceText) meta.append(el('span', 'de-source-text', `source ${r.sourceText}`));
  row.append(meta);
  const acts = el('div', 'de-actions');
  const busy = !!st.busy;
  if (r.source) {
    const label = r.source.kind === 'message' ? 'Open source message' : 'Open source doc';
    acts.append(action(`de-open-${k}`, r.source.kind === 'message' ? 'Source ↗' : 'Source doc ↗',
      r.source.kind === 'message' ? `${label} ${r.source.id} in Chat` : `${label} ${r.source.id} in the EDP reader`,
      () => ctx.post({ type: 'decisionOpen', id: r.id })));
  }
  const can = rowActions(r, st.canManage);
  if (can.binding) {
    acts.append(action(`de-binding-${k}`, r.binding ? 'Unbind' : 'Make binding',
      r.binding ? 'Stop handing this decision to every agent in scope' : 'Hand this decision to every agent in scope, never cut',
      () => ctx.post({ type: 'decisionBinding', id: r.id, binding: !r.binding }), busy));
  }
  if (can.withdraw) {
    const w = action(`de-withdraw-${k}`, 'Withdraw…', 'Withdraw this decision (asks the reason)', () => ctx.post({ type: 'decisionWithdraw', id: r.id }), busy);
    w.classList.add('de-withdraw');
    acts.append(w);
  }
  row.append(acts);
  if (st.busy === r.id) row.setAttribute('aria-busy', 'true');
  if (st.notice?.id === r.id) {
    const n = el('div', st.notice.ok ? 'de-note' : 'ib-error', st.notice.text);
    n.id = `de-notice-${k}`;
    n.setAttribute('role', st.notice.ok ? 'status' : 'alert');
    row.append(n);
  }
  return row;
}

export function renderDecisions(panel: HTMLElement, ctx: TabCtx): void {
  const st = ctx.state.decisions ?? null;
  const rows = st?.rows ?? [];
  const kind = ctx.state.ticket?.kind ?? 'ticket';
  const top = el('div', 'tab-top');
  const sum = el('span', 'tab-sum');
  sum.id = 'decisions-summary';
  const live = rows.filter(r => r.status === 'live').length;
  sum.textContent = !st || (st.loading && !rows.length) ? 'Reading the decisions…'
    : rows.length ? `${live} live${rows.length > live ? `, ${rows.length - live} withdrawn` : ''} in this ${kind}` : `No decisions recorded in this ${kind}`;
  top.append(sum, action('decisions-refresh', 'Refresh', 'Read the board again', () => ctx.post({ type: 'decisionsRefresh' })));
  const out: HTMLElement[] = [top];
  if (st?.error) { const e = el('div', 'ib-error ib-list-error', st.error); e.id = 'decisions-error'; e.setAttribute('role', 'alert'); out.push(e); }
  const list = el('div', 'de-list');
  list.setAttribute('role', 'list');
  for (const r of rows) { const n = decisionRow(r, ctx); n.setAttribute('role', 'listitem'); list.append(n); }
  out.push(list);
  panel.replaceChildren(...out);
}

export const decisionsTab: Tab = {
  id: 'decisions',
  label: 'Decisions',
  badge: ctx => decisionsBadge(ctx.state.decisions),
  render: renderDecisions,
};
