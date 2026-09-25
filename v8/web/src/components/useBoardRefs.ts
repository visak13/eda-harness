import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";
import { findBoard, getEpicsSummary, getEpicTickets, getScopeDecisions, getScopeDocs, getTicket } from "../api/endpoints";
import { activeRef, boardRows, rankRefs, refToken, scopeRows, type RefRow } from "./boardRefs";

// C24 (s-5d1b171d57): the $ picker, the @ picker's twin (useMentions: same menu shape, same keys — ↑/↓ move,
// Enter/Tab pick, Esc closes and keeps the text). Rows are this epic's tree first (tickets, docs, live
// decisions), then the board's open items (open epics + /v1/find hits). Existing routes only.

const TICKET_ID = /^(?:epic|s|t)-[0-9a-f]{10}$/;

/** The rows of the current scope: the epic of `ticketId` (or of the page's :id), its tickets, docs, decisions. */
export function useRefScope(ticketId?: string | null, enabled = true): RefRow[] {
  const params = useParams();
  const id = ticketId ?? (params.id && TICKET_ID.test(params.id) ? params.id : null);
  const ticket = useQuery({ queryKey: ["ticket", id], queryFn: () => getTicket(id!), enabled: enabled && Boolean(id), retry: false, staleTime: 60_000 });
  const t = ticket.data;
  const epic = t ? (t.kind === "epic" ? t.id : (t.epic_id as string | null | undefined) ?? null) : null;
  const on = enabled && Boolean(epic);
  const opts = { enabled: on, retry: false, staleTime: 60_000 } as const;
  const epicTicket = useQuery({ queryKey: ["ticket", epic], queryFn: () => getTicket(epic!), ...opts });
  const tickets = useQuery({ queryKey: ["refs", "tickets", epic], queryFn: () => getEpicTickets(epic!), ...opts });
  const docs = useQuery({ queryKey: ["refs", "docs", epic], queryFn: () => getScopeDocs(epic!), ...opts });
  const decisions = useQuery({ queryKey: ["refs", "decisions", epic], queryFn: () => getScopeDecisions(epic!), ...opts });
  return useMemo(() => {
    const own = [...(epicTicket.data ? [epicTicket.data] : []), ...(tickets.data ?? []).filter((x) => x.id !== epic)];
    return scopeRows(own, docs.data ?? [], decisions.data?.decisions ?? []);
  }, [epic, epicTicket.data, tickets.data, docs.data, decisions.data]);
}

/** The board's open items for a query (debounced; nothing is fetched for a one-letter query). */
function useRefBoard(query: string | null, enabled: boolean): RefRow[] {
  const [q, setQ] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setQ(query && query.length >= 2 ? query : null), 150);
    return () => clearTimeout(t);
  }, [query]);
  const epics = useQuery({ queryKey: ["epics", "summary", "refs"], queryFn: () => getEpicsSummary(), enabled, retry: false, staleTime: 60_000 });
  const hits = useQuery({ queryKey: ["refs", "find", q], queryFn: () => findBoard(q!, "ticket,doc,decision"), enabled: enabled && Boolean(q), retry: false, staleTime: 30_000 });
  return useMemo(() => boardRows(hits.data ?? [], epics.data ?? []), [hits.data, epics.data]);
}

export interface BoardRefsMenu { open: boolean; items: RefRow[]; index: number }

export interface BoardRefs {
  menu: BoardRefsMenu;
  refresh: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) => boolean;
  accept: (row: RefRow) => void;
  close: () => void;
}

export function useBoardRefs(
  ticketId: string | null | undefined,
  fieldRef: React.RefObject<HTMLTextAreaElement | HTMLInputElement | null>,
  setText: (next: string) => void,
): BoardRefs {
  const [query, setQuery] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const dismissed = useRef<string | null>(null);
  const caretToSet = useRef<number | null>(null);
  // the scope is read once the first $ is typed (a thread with no $ costs nothing)
  const [wanted, setWanted] = useState(false);
  const scope = useRefScope(ticketId, wanted);
  const board = useRefBoard(query, wanted);
  const items = useMemo(() => (query === null ? [] : rankRefs(query, scope, board)), [query, scope, board]);
  const open = query !== null && items.length > 0;
  const idx = Math.min(index, Math.max(items.length - 1, 0));

  useLayoutEffect(() => {
    if (caretToSet.current !== null && fieldRef.current) {
      const pos = caretToSet.current;
      fieldRef.current.setSelectionRange(pos, pos);
      caretToSet.current = null;
    }
  });

  const close = useCallback(() => setQuery(null), []);

  const refresh = useCallback(() => {
    const f = fieldRef.current;
    if (!f) return;
    const caret = f.selectionStart ?? f.value.length;
    const hit = f.selectionStart === f.selectionEnd ? activeRef(f.value, caret) : null;
    if (!hit) { dismissed.current = null; setQuery(null); return; }
    const key = `${hit.start}:${hit.query}`;
    if (dismissed.current === key) return;
    dismissed.current = null;
    setWanted(true);
    setQuery((cur) => { if (cur !== hit.query) setIndex(0); return hit.query; });
  }, [fieldRef]);

  const accept = useCallback((row: RefRow) => {
    const f = fieldRef.current;
    if (!f) return;
    const caret = f.selectionStart ?? f.value.length;
    const hit = activeRef(f.value, caret);
    if (!hit) return;
    const ins = refToken(row);
    const next = f.value.slice(0, hit.start) + ins + f.value.slice(caret);
    caretToSet.current = hit.start + ins.length;
    setText(next);
    setQuery(null);
  }, [fieldRef, setText]);

  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>): boolean => {
    if (!open) return false;
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((idx + 1) % items.length); return true; }
    if (e.key === "ArrowUp") { e.preventDefault(); setIndex((idx - 1 + items.length) % items.length); return true; }
    if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); accept(items[idx]); return true; }
    if (e.key === "Escape") {
      e.preventDefault();
      const f = fieldRef.current;
      const hit = f ? activeRef(f.value, f.selectionStart ?? f.value.length) : null;
      dismissed.current = hit ? `${hit.start}:${hit.query}` : null;
      close();
      return true;
    }
    return false;
  }, [open, idx, items, accept, close, fieldRef]);

  return { menu: { open, items, index: idx }, refresh, onKeyDown, accept, close };
}
