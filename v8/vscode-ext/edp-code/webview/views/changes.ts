// The Changes tab (C13 s-f4e767cfd1; design §13.1, C9 option (a)): the shared tree's uncommitted files.
// Files the open scope touched come first in their own group; the other seats' files sit in a collapsible
// "all seats (M more)" group, folded by default. A file opens its diff against HEAD, "Open all" the
// multi-diff. The rows name no seat: a shared tree cannot say who made an uncommitted edit (dec-8dfe3d97af).
import type { UncommittedCard } from '../../src/core/chatProtocol';
import { fileRow } from '../cards';
import { action, group, type Tab, type TabCtx } from '../tabs';

const files = (k: number) => `${k} file${k === 1 ? '' : 's'}`;

/** The badge: the scope's own uncommitted files (every file when there is no scope). */
export function changesBadge(card: UncommittedCard | null): { text: string; aria: string } | null {
  const n = card?.total ?? 0;
  if (!n) return null;
  if (card?.scoped == null) return { text: String(n), aria: `${files(n)} uncommitted` };
  return { text: String(card.scoped), aria: `${files(card.scoped)} this ${card.scope ?? 'epic'} touched, ${files(n)} uncommitted across all seats` };
}

function list(rows: UncommittedCard['files'], ctx: TabCtx, label: string): HTMLElement {
  const ul = document.createElement('ul');
  ul.className = 'cm-files uc-files';
  ul.setAttribute('aria-label', label);
  for (const f of rows) ul.append(fileRow(f, () => ctx.post({ type: 'openUncommitted', path: f.path }), false));
  return ul;
}

function note(text: string): HTMLElement {
  const d = document.createElement('div');
  d.className = 'cm-more';
  d.textContent = text;
  return d;
}

export function renderChanges(panel: HTMLElement, ctx: TabCtx): void {
  const card = ctx.state.uncommitted;
  const n = card?.total ?? 0;
  const top = document.createElement('div');
  top.className = 'tab-top';
  const sum = document.createElement('span');
  sum.className = 'tab-sum';
  sum.id = 'changes-summary';
  sum.textContent = n ? `${files(n)} uncommitted in the shared tree` : 'The shared tree is clean';
  top.append(sum, action('changes-open-all', 'Open all', n ? `Open every uncommitted change against HEAD (multi-diff, ${files(n)})` : 'Nothing to open',
    () => ctx.post({ type: 'openUncommitted' }), !n));
  const out: HTMLElement[] = [top];
  if (card && n) {
    const scope = card.scope ?? 'epic';
    const flip = (k: 'scoped' | 'allSeats') => (open: boolean) => {
      ctx.local.fold[k] = open;
      ctx.persist();
      renderChanges(panel, ctx);
      panel.querySelector<HTMLElement>(`#${k === 'scoped' ? 'changes-scoped' : 'changes-all'}-toggle`)?.focus();
    };
    if (card.scoped !== null) {
      const mine = card.files.filter(f => f.touched);
      const rest = card.files.filter(f => !f.touched);
      const restN = n - card.scoped;
      out.push(group({ id: 'changes-scoped', title: `This ${scope}`, count: files(card.scoped), open: ctx.local.fold.scoped, onToggle: flip('scoped'),
        actions: [action('changes-open-scoped', 'Open', `Open this ${scope}'s uncommitted changes (multi-diff)`,
          () => ctx.post({ type: 'openUncommitted', scoped: true }), !card.scoped)],
        body: () => (mine.length ? list(mine, ctx, `Uncommitted files this ${scope} touched`) : note(`No uncommitted file is one this ${scope} touched.`)) }));
      if (restN > 0) {
        out.push(group({ id: 'changes-all', title: 'All seats', count: `${restN} more`, open: ctx.local.fold.allSeats, onToggle: flip('allSeats'),
          body: () => {
            const b = document.createElement('div');
            b.append(list(rest, ctx, `Uncommitted files outside this ${scope}`));
            if (card.more) b.append(note(`+${card.more} more (Open all shows every file)`));
            return b;
          } }));
      }
    } else {
      const b = list(card.files, ctx, 'Uncommitted files');
      out.push(b);
      if (card.more) out.push(note(`+${card.more} more (Open all shows every file)`));
    }
  }
  panel.replaceChildren(...out);
}

export const changesTab: Tab = {
  id: 'changes',
  label: 'Changes',
  badge: ctx => changesBadge(ctx.state.uncommitted),
  render: renderChanges,
};
