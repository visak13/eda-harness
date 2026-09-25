// The tab registry (C13 s-f4e767cfd1; design §13.1): every view under the header is one entry here plus one
// view module. Order is the tab bar's order; the first tab is the default. A later view (docs,
// attachments) adds an entry, never a band above the thread.
import type { Tab } from './tabs';
import { changesTab } from './views/changes';
import { commitsTab } from './views/commits';
import { inboxTab } from './views/inbox';

/** The Chat tab: the thread and the composer, which main.ts builds into its panel (C3/C4/C11/C12). The
 *  badge counts messages that arrived while another tab was showing. */
export const chatTab: Tab = {
  id: 'chat',
  label: 'Chat',
  badge: ctx => (ctx.chatUnread ? { text: ctx.chatUnread > 99 ? '99+' : String(ctx.chatUnread), aria: `${ctx.chatUnread} new message${ctx.chatUnread === 1 ? '' : 's'}` } : null),
  render: () => {},
};

export const TABS: readonly Tab[] = [chatTab, changesTab, commitsTab, inboxTab];
