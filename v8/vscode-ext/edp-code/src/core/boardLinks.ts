// Board page links for the open-on-board actions (chat panel, badge, tag; C10 s-e1cec79882, design-10b21760d9
// §13). An epic has its own page, /ui/epic/<id>; /ui/ticket/<epic id> is the story view with the wrong header.
// Pure: the VS Code shell passes `edp.boardUrl` and the id it has; `kind` wins when the caller knows it,
// otherwise the board's `epic-` id prefix decides.

export function isEpicId(id: string, kind?: string | null): boolean {
  return kind ? kind === 'epic' : id.startsWith('epic-');
}

/** `<base>/ui/epic/<id>` for an epic, `<base>/ui/ticket/<id>` otherwise, with an optional `#<messageId>` anchor. */
export function boardTicketUrl(base: string, id: string, messageId?: string | null, kind?: string | null): string {
  const page = isEpicId(id, kind) ? 'epic' : 'ticket';
  return `${base.replace(/\/+$/, '')}/ui/${page}/${encodeURIComponent(id)}${messageId ? `#${encodeURIComponent(messageId)}` : ''}`;
}
