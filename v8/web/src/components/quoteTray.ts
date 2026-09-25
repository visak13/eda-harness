import { useSyncExternalStore } from "react";
import type { QuoteIn } from "../api/types";
import { identity } from "../auth/identity";

// C19 (design-10b21760d9 §14.5/§14.7): the quotes a viewer is building for ONE thread, in order —
// "quote once, quote multiple times, quote with context" (owner m-db09472a68). Every Quote from a
// doc or a message lands here as a chip; the thread's composer shows, reorders, removes and finally
// sends them as `quotes[]`. Kept per viewer+ticket in sessionStorage (tab-local, like drafts), so a
// reload or a hop between the thread and a doc keeps what was built. Nothing is sent from here.

export interface TrayQuote {
  key: string;
  quote: QuoteIn;
  /** What the chip names: "design-… v12 L41-43" / "m-… (architect…)". */
  label: string;
}

type Listener = () => void;
const trays = new Map<string, TrayQuote[]>();
const listeners = new Set<Listener>();
const EMPTY: TrayQuote[] = [];

function storageKey(ticketId: string): string {
  return `edp8.quotes.${identity()}:${ticketId}`;
}

function load(ticketId: string): TrayQuote[] {
  const hit = trays.get(storageKey(ticketId));
  if (hit) return hit;
  let rows: TrayQuote[] = EMPTY;
  try {
    const raw = sessionStorage.getItem(storageKey(ticketId));
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed) && parsed.every((q) => q && typeof q.key === "string" && typeof q.quote?.text === "string")) rows = parsed as TrayQuote[];
  } catch { /* an unreadable tray starts empty */ }
  trays.set(storageKey(ticketId), rows);
  return rows;
}

function save(ticketId: string, rows: TrayQuote[]): void {
  trays.set(storageKey(ticketId), rows);
  try {
    if (rows.length) sessionStorage.setItem(storageKey(ticketId), JSON.stringify(rows));
    else sessionStorage.removeItem(storageKey(ticketId));
  } catch { /* memory stays authoritative when tab storage is denied/full */ }
  for (const l of listeners) l();
}

export const MAX_TRAY = 20; // the board's cap per message (edp8/quotes.py MAX_QUOTES)

export const quoteTray = {
  get: load,
  /** Adds a quote to the end; false when the tray is full. */
  add(ticketId: string, quote: QuoteIn, label: string): boolean {
    const rows = load(ticketId);
    if (rows.length >= MAX_TRAY) return false;
    save(ticketId, [...rows, { key: `q${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`, quote, label }]);
    return true;
  },
  remove(ticketId: string, key: string): void {
    save(ticketId, load(ticketId).filter((q) => q.key !== key));
  },
  /** Moves a quote one place up (-1) or down (+1). */
  move(ticketId: string, key: string, by: -1 | 1): void {
    const rows = [...load(ticketId)];
    const i = rows.findIndex((q) => q.key === key);
    const j = i + by;
    if (i < 0 || j < 0 || j >= rows.length) return;
    [rows[i], rows[j]] = [rows[j], rows[i]];
    save(ticketId, rows);
  },
  setNote(ticketId: string, key: string, note: string): void {
    save(ticketId, load(ticketId).map((q) => (q.key === key ? { ...q, quote: { ...q.quote, note: note || undefined } } : q)));
  },
  /** Drops the quotes a successful send carried (by key; ones added meanwhile stay). */
  removeSent(ticketId: string, keys: string[]): void {
    save(ticketId, load(ticketId).filter((q) => !keys.includes(q.key)));
  },
  subscribe(l: Listener): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

export function useQuoteTray(ticketId: string | null): TrayQuote[] {
  return useSyncExternalStore(quoteTray.subscribe, () => (ticketId ? load(ticketId) : EMPTY), () => EMPTY);
}

// The thread a Quote goes to: the thread composer on screen (Ticket/Epic page), the last one
// mounted winning; a page without one (the full /doc page) falls back to the doc's own ticket scope.
const targets: string[] = [];
export function registerQuoteTarget(ticketId: string): () => void {
  targets.push(ticketId);
  for (const l of listeners) l();
  return () => {
    const i = targets.lastIndexOf(ticketId);
    if (i >= 0) targets.splice(i, 1);
    for (const l of listeners) l();
  };
}
export function activeQuoteTarget(): string | null {
  return targets[targets.length - 1] ?? null;
}
