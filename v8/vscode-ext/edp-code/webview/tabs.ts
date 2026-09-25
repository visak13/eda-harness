// The tab bar (C13 s-f4e767cfd1; design-10b21760d9 §13.1). Every view under the header is a tab from ONE
// registry (webview/registry.ts): a tab is `{id, label, badge, render}` and adding one is one registry entry
// plus one view module; the bar, the panels, the keyboard and the active-tab memory come from here. The scope
// picker in the header drives every tab: a tab renders from the same ChatState, never its own scope.
// ARIA tabs pattern: role=tablist/tab/tabpanel, roving tabindex, arrows/Home/End move and select.
import type { ChatState, ViewToHost } from '../src/core/chatProtocol';
import type { ViewLocal } from '../src/core/viewState';

type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;

/** What a tab renders from. `state` is the open scope; `local` is this viewer's webview state. */
export type TabCtx = {
  state: ChatState;
  local: ViewLocal;
  post: (m: Intent) => void;
  /** save `local` (vscode.setState) */
  persist: () => void;
  /** switch tabs (the Chat's commit markers open the Commits tab) */
  select: (id: string, opts?: { focus?: boolean; sha?: string }) => void;
  /** messages that arrived while the Chat tab was not showing */
  chatUnread: number;
  /** a commit to expand, scroll to and focus when the Commits tab renders (a Chat marker's jump) */
  focusSha?: string;
};

export type Badge = { text: string; aria: string } | null;

export type Tab = {
  id: string;
  label: string;
  badge: (ctx: TabCtx) => Badge;
  /** fill the tab's panel; called when the tab is shown and whenever the state changes while it shows */
  render: (panel: HTMLElement, ctx: TabCtx) => void;
  /** optional: the tab was just shown or hidden */
  shown?: (ctx: TabCtx) => void;
};

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

export class TabBar {
  readonly bar = el('div', 'tabbar');
  readonly panels = el('div', 'panels');
  private buttons = new Map<string, HTMLButtonElement>();
  private panel = new Map<string, HTMLElement>();
  private active: string;

  constructor(private tabs: readonly Tab[], initial: string, private onSelect: (id: string) => void) {
    this.bar.setAttribute('role', 'tablist');
    this.bar.setAttribute('aria-label', 'Views');
    this.active = tabs.some(t => t.id === initial) ? initial : tabs[0].id;
    for (const t of tabs) {
      const b = el('button', 'tab');
      b.type = 'button';
      b.id = `tab-${t.id}`;
      b.dataset.tab = t.id;
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-controls', `panel-${t.id}`);
      b.addEventListener('click', () => this.onSelect(t.id));
      this.buttons.set(t.id, b);
      this.bar.append(b);
      const p = el('section', `panel panel-${t.id}`);
      p.id = `panel-${t.id}`;
      p.setAttribute('role', 'tabpanel');
      p.setAttribute('aria-labelledby', b.id);
      this.panel.set(t.id, p);
      this.panels.append(p);
    }
    this.bar.addEventListener('keydown', e => this.onKey(e));
    this.paint();
  }

  get current(): string { return this.active; }
  panelOf(id: string): HTMLElement { return this.panel.get(id)!; }
  has(id: string): boolean { return this.panel.has(id); }

  /** Show `id`; the caller renders it. */
  show(id: string, focus = false): void {
    if (!this.has(id)) return;
    this.active = id;
    this.paint();
    const b = this.buttons.get(id)!;
    if (focus) b.focus();
    b.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); // C16: a bar wider than the panel scrolls to the shown tab
  }

  /** Labels and count badges, from the current state. */
  badges(ctx: TabCtx | null): void {
    for (const t of this.tabs) {
      const b = this.buttons.get(t.id)!;
      const badge = ctx ? t.badge(ctx) : null;
      b.replaceChildren(el('span', 'tab-label', t.label));
      if (badge) {
        const n = el('span', 'tab-badge', badge.text);
        n.setAttribute('aria-hidden', 'true');
        b.append(n);
      }
      b.setAttribute('aria-label', badge ? `${t.label}, ${badge.aria}` : t.label);
      b.title = badge ? `${t.label}: ${badge.aria}` : t.label;
    }
  }

  private paint(): void {
    for (const t of this.tabs) {
      const on = t.id === this.active;
      const b = this.buttons.get(t.id)!;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
      this.panel.get(t.id)!.hidden = !on;
    }
  }

  private onKey(e: KeyboardEvent): void {
    const ids = this.tabs.map(t => t.id);
    const i = ids.indexOf((e.target as HTMLElement).dataset?.tab ?? this.active);
    let j = -1;
    if (e.key === 'ArrowRight') j = (i + 1) % ids.length;
    else if (e.key === 'ArrowLeft') j = (i - 1 + ids.length) % ids.length;
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = ids.length - 1;
    if (j < 0) return;
    e.preventDefault();
    this.onSelect(ids[j]);
    this.buttons.get(ids[j])!.focus();
  }
}

/** A collapsible group: a header button (aria-expanded) that folds its body, by click or Enter/Space
 *  (a native button), plus optional actions beside it. Used by every list tab. */
export function group(opts: { id: string; title: string; count: string; open: boolean; onToggle: (open: boolean) => void;
  actions?: HTMLElement[]; body: () => HTMLElement }): HTMLElement {
  const g = el('section', `group${opts.open ? ' open' : ''}`);
  g.id = opts.id;
  const head = el('div', 'group-head');
  const t = el('button', 'group-toggle');
  t.type = 'button';
  t.id = `${opts.id}-toggle`;
  t.setAttribute('aria-expanded', String(opts.open));
  t.setAttribute('aria-controls', `${opts.id}-body`);
  t.append(el('span', 'group-caret', opts.open ? '▾' : '▸'), el('span', 'group-title', opts.title), el('span', 'group-count', opts.count));
  t.title = `${opts.open ? 'Fold' : 'Expand'} ${opts.title}`;
  t.addEventListener('click', () => opts.onToggle(!opts.open));
  head.append(t, ...(opts.actions ?? []));
  g.append(head);
  if (opts.open) {
    const b = opts.body();
    b.id = `${opts.id}-body`;
    b.classList.add('group-body');
    g.append(b);
  }
  return g;
}

/** A small action button (Open all, Open). */
export function action(id: string, text: string, title: string, run: () => void, disabled = false): HTMLButtonElement {
  const b = el('button', 'act', text);
  b.type = 'button';
  b.id = id;
  b.title = title;
  b.disabled = disabled;
  b.addEventListener('click', e => { e.stopPropagation(); run(); });
  return b;
}
