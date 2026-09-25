// The Docs tab (C16 s-579fa02cca; design-10b21760d9 §14.2, §14.4): the picked scope's linked docs only (owner
// m-db09472a68: every tab is scoped), each with its type, version, status and why it is here. A row opens the doc in
// the EDP reader editor tab (its current version); Compare picks two versions for VS Code's diff. Rows come from the
// host; the view names a doc by id only and the host resolves it from its own list. The badge counts proposals.
import { docsBadge, whyText, type DocRow } from '../../src/core/docs';
import { action, type Tab, type TabCtx } from '../tabs';

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const domKey = (id: string) => id.replace(/[^A-Za-z0-9_-]/g, '_');

function docRow(d: DocRow, ctx: TabCtx): HTMLElement {
  const row = el('article', `dc-row dc-${d.docType}`);
  row.id = `dc-${domKey(d.id)}`;
  row.dataset.id = d.id;
  const open = el('button', 'dc-open');
  open.type = 'button';
  open.id = `dc-open-${domKey(d.id)}`;
  open.title = `Open ${d.id} v${d.version} in the EDP reader`;
  const head = el('span', 'dc-head');
  head.append(el('span', 'dc-title', d.title));
  const meta = el('span', 'dc-meta');
  meta.append(el('span', 'dc-type', d.docType), el('span', 'dc-version', `v${d.version}`), el('span', `dc-status dc-status-${d.status}`, d.status));
  open.append(head, meta);
  open.addEventListener('click', () => ctx.post({ type: 'docsOpen', id: d.id }));
  const why = el('div', 'dc-why', whyText(d.why, ctx.state.ticket?.id ?? ''));
  const acts = el('div', 'dc-actions');
  if (d.version > 1) acts.append(action(`dc-compare-${domKey(d.id)}`, 'Compare', `Compare two versions of ${d.id} in the diff editor`, () => ctx.post({ type: 'docsCompare', id: d.id })));
  row.append(open, why, acts);
  return row;
}

export function renderDocs(panel: HTMLElement, ctx: TabCtx): void {
  const docs = ctx.state.docs ?? null;
  const rows = docs?.docs ?? [];
  const kind = ctx.state.ticket?.kind ?? 'ticket';
  const top = el('div', 'tab-top');
  const sum = el('span', 'tab-sum');
  sum.id = 'docs-summary';
  sum.textContent = !docs || (docs.loading && !rows.length) ? 'Reading the linked docs…'
    : rows.length ? `${rows.length} doc${rows.length === 1 ? '' : 's'} linked to this ${kind}` : `No docs linked to this ${kind}`;
  top.append(sum, action('docs-refresh', 'Refresh', 'Read the board again', () => ctx.post({ type: 'docsRefresh' })));
  const out: HTMLElement[] = [top];
  if (docs?.error) { const e = el('div', 'ib-error ib-list-error', docs.error); e.setAttribute('role', 'alert'); out.push(e); }
  const list = el('div', 'dc-list');
  list.setAttribute('role', 'list');
  for (const d of rows) { const r = docRow(d, ctx); r.setAttribute('role', 'listitem'); list.append(r); }
  out.push(list);
  panel.replaceChildren(...out);
}

export const docsTab: Tab = {
  id: 'docs',
  label: 'Docs',
  badge: ctx => docsBadge(ctx.state.docs),
  render: renderDocs,
};
