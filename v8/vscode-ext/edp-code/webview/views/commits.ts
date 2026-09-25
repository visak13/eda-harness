// The Commits tab (C13 s-f4e767cfd1; design §13.1): the commits attributed to the open scope, newest
// first, as expandable cards: a story with its tasks, or an epic with every ticket of it (each card labelled
// with its story, architect m-9bb99dbf72). At epic scope the commits naming no ticket sit in a collapsed
// Unlinked group at the bottom. The badge counts commits newer than this viewer last saw at this scope.
import type { CommitCard } from '../../src/core/chatProtocol';
import { markSeen, unseenCommits } from '../../src/core/viewState';
import { commitCardEl } from '../cards';
import { group, type Tab, type TabCtx } from '../tabs';

/** Cards this viewer opened, by sha (this view's life; a reload starts folded). */
const expanded = new Set<string>();

function cards(list: readonly CommitCard[], ctx: TabCtx, panel: HTMLElement, labels: Map<string, string> | null): HTMLElement {
  const box = document.createElement('div');
  box.className = 'cm-list';
  for (const c of list) {
    const label = labels ? (c.story ? labels.get(c.story) ?? c.story : 'epic') : undefined;
    box.append(commitCardEl(c, ctx.post, expanded.has(c.sha), open => {
      if (open) expanded.add(c.sha); else expanded.delete(c.sha);
      renderCommits(panel, ctx);
      panel.querySelector<HTMLElement>(`.commit[data-sha="${c.sha}"] .cm-head`)?.focus();
    }, label));
  }
  return box;
}

export function renderCommits(panel: HTMLElement, ctx: TabCtx): void {
  const s = ctx.state;
  const epic = s.ticket?.kind === 'epic';
  const labels = epic ? new Map(s.stories.map(x => [x.id, x.title])) : null;
  const focus = ctx.focusSha;
  if (focus) expanded.add(focus);
  const top = document.createElement('div');
  top.className = 'tab-top';
  const sum = document.createElement('span');
  sum.className = 'tab-sum';
  sum.id = 'commits-summary';
  const n = s.commits.length;
  sum.textContent = n ? `${n} commit${n === 1 ? '' : 's'} name this ${epic ? 'epic or its stories' : s.ticket?.kind ?? 'ticket'}` : `No commit names this ${s.ticket?.kind ?? 'ticket'} yet`;
  const out: HTMLElement[] = [top];
  top.append(sum);
  if (n) out.push(cards(s.commits, ctx, panel, labels));
  if (epic) {
    const un = s.unlinked ?? [];
    const onFocus = !!focus && un.some(c => c.sha === focus);
    out.push(group({ id: 'commits-unlinked', title: 'Unlinked', count: `${un.length}${un.length >= 100 ? '+ (newest 100)' : ''}`,
      open: ctx.local.fold.unlinked || onFocus,
      onToggle: open => { ctx.local.fold.unlinked = open; ctx.persist(); renderCommits(panel, ctx); panel.querySelector<HTMLElement>('#commits-unlinked-toggle')?.focus(); },
      body: () => {
        if (!un.length) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = 'Every commit in the window names a ticket.'; return p; }
        return cards(un, ctx, panel, null);
      } }));
  }
  panel.replaceChildren(...out);
  if (focus) {
    ctx.focusSha = undefined;
    const head = panel.querySelector<HTMLElement>(`.commit[data-sha="${focus}"] .cm-head`);
    head?.scrollIntoView?.({ block: 'nearest' });
    head?.focus();
  }
  if (s.ticket && markSeen(ctx.local, s.ticket.id, s.commits)) ctx.persist();
}

export const commitsTab: Tab = {
  id: 'commits',
  label: 'Commits',
  badge: ctx => {
    const n = ctx.state.ticket ? unseenCommits(ctx.state.commits, ctx.local.seen[ctx.state.ticket.id]) : 0;
    return n ? { text: n > 99 ? '99+' : String(n), aria: `${n} new commit${n === 1 ? '' : 's'}` } : null;
  },
  render: renderCommits,
};
