import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { getThreadPage } from "../api/endpoints";
import type { MessageView, ThreadPage } from "../api/types";
import { Icon } from "./Icon";
import styles from "./Conversation.module.css";

/** Older pages never replace the source query/composer. Finding 13: the head window is a *sliding*
 * page (the newest ~100), so a live arrival can push the oldest head row off it. We keep every head
 * row we have ever shown in a per-thread cache and merge it back in, so a row that falls off the head
 * window stays in an already-loaded thread instead of vanishing until "Load older" is pressed again.
 * The cache resets when the thread id changes. */
export function useThreadHistory(id: string, page?: ThreadPage) {
  const qc = useQueryClient();
  const [older, setOlder] = useState<{ id: string; head: number | null | undefined; next: number | null | undefined; rows: MessageView[]; total?: number }>();
  const listRef = useRef<HTMLUListElement>(null);
  const anchor = useRef<{ id: string; top: number } | null>(null);
  const currentId = useRef(id); currentId.current = id;
  // Every head row ever seen for THIS thread (finding 13): a row that slides off the head window
  // stays in an already-loaded thread instead of vanishing. Consult claim 5: the cache is only
  // READ during render (gated by id — a stale-thread cache is treated as empty); it is MUTATED in
  // a commit-time effect below, never during render, so a speculative/thrown-away render can never
  // drop a head row. The current page's rows are merged directly here regardless, so the newest
  // head is always shown; the cache only carries rows that have already fallen off the window.
  const seen = useRef<{ id: string; rows: Map<string, MessageView> }>({ id, rows: new Map() });
  const seenRows = seen.current.id === id ? seen.current.rows : new Map<string, MessageView>();
  const rows = older?.id === id ? older.rows : [];
  const merged = new Map(rows.map((m) => [m.id, m]));
  for (const [mid, m] of seenRows) merged.set(mid, m);
  for (const m of page?.thread ?? []) merged.set(m.id, m);
  const messages = [...merged.values()].sort((a, b) => a.seq != null && b.seq != null ? a.seq - b.seq : a.at.localeCompare(b.at));
  const before = older?.id === id && older.head === page?.thread_before ? older.next : page?.thread_before;
  const total = Math.max(page?.thread_total ?? messages.length, older?.id === id ? older.total ?? 0 : 0);
  useEffect(() => {
    if (seen.current.id !== id) seen.current = { id, rows: new Map() };
    for (const m of page?.thread ?? []) seen.current.rows.set(m.id, m);
  }, [id, page]);
  const load = useMutation({
    mutationFn: ({ source, cursor }: { source: string; cursor: number; head: number | null | undefined }) => qc.fetchQuery({ queryKey: ["thread", source, cursor], queryFn: () => getThreadPage(source, cursor) }),
    onSuccess: (data, variables) => {
      if (currentId.current !== variables.source) return;
      const list = listRef.current;
      const visible = list && [...list.children].find((el) => el.getBoundingClientRect().bottom > list.getBoundingClientRect().top);
      anchor.current = visible ? { id: visible.id, top: visible.getBoundingClientRect().top } : null;
      setOlder((prev) => ({ id, head: variables.head, next: data.thread_before, total: data.thread_total,
        rows: [...(prev?.id === id ? prev.rows : []), ...data.thread] }));
    },
  });
  useLayoutEffect(() => {
    const saved = anchor.current;
    if (!saved || !listRef.current) return;
    const item = [...listRef.current.children].find((el) => el.id === saved.id);
    if (item) listRef.current.scrollTop += item.getBoundingClientRect().top - saved.top;
    anchor.current = null;
  }, [older]);
  // Consult claim 7: guard `more` by the count too — a cursor can survive after every older row is
  // already merged in, which showed a "0 older" affordance that loaded nothing.
  return { messages, total, listRef, more: before != null && messages.length < total, loading: load.isPending,
    error: load.variables?.source === id ? load.error : null,
    load: () => { if (before != null && !load.isPending) load.mutate({ source: id, cursor: before, head: page?.thread_before }); } };
}

/** Page size the backend serves (views.thread_page). A thread larger than one page shows the
 * indicator; a thread that never paged (nothing older) shows nothing. */
const THREAD_PAGE_SIZE = 100;

export function ThreadHistoryControls({ history }: { history: ReturnType<typeof useThreadHistory> }) {
  const paged = history.total > THREAD_PAGE_SIZE;
  const remaining = history.total - history.messages.length;
  return <>
    {paged ? <div className={styles.history} data-testid="thread-history">
      <span data-testid="thread-page-indicator">Showing {history.messages.length} of {history.total}{history.more ? ` · ${remaining} older` : ""}</span>
      {history.more ? <button type="button" className={styles.historyButton} onClick={history.load} disabled={history.loading}><Icon name="history" size={16} /> {history.loading ? "Loading older messages…" : "Load older messages"}</button> : null}</div> : null}
    {history.error ? <p role="alert" className={styles.historyError}>Could not load older messages: {(history.error as Error).message}. Your conversation and draft are kept; try again.</p> : null}
  </>;
}
