import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { subscribeFeed } from "./feed";
import { affectedBy } from "./affectedQueries";

interface DraftGuardValue {
  pending: number;
  flush: () => void;
  setDirty: (id: string, dirty: boolean, subject?: string) => void;
}
const DraftGuardContext = createContext<DraftGuardValue | null>(null);

/** One feed and one 250ms window; hold affected draft keys rather than global invalidation.
 * Explicit flush updates data without clearing drafts or remounting their owners. */
export function DraftGuardProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const qc = useQueryClient();
  const [pending, setPending] = useState(0);
  const dirty = useRef(new Map<string, string | undefined>());
  const queued = useRef(new Map<string, QueryKey>());
  const held = useRef(new Map<string, QueryKey>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const drain = useCallback(() => {
    timer.current = null;
    for (const [hash, queryKey] of queued.current) {
      // A draft may become dirty AFTER an event queued, before the window closes.
      const blocked = [...dirty.current.values()].some((subject) => !subject || queryKey.includes(subject) || queryKey[0] === "me");
      if (blocked) { held.current.set(hash, queryKey); setPending((n) => n || 1); }
      else void qc.invalidateQueries({ queryKey, exact: true });
    }
    queued.current.clear();
  }, [qc]);
  const schedule = useCallback(() => {
    if (!timer.current && queued.current.size) timer.current = setTimeout(drain, 250);
  }, [drain]);
  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const keys = new Map([...queued.current, ...held.current]);
    queued.current.clear(); held.current.clear(); setPending(0);
    for (const queryKey of keys.values()) void qc.invalidateQueries({ queryKey, exact: true });
  }, [qc]);
  const setDirty = useCallback((id: string, value: boolean, subject?: string) => {
    if (value) dirty.current.set(id, subject);
    else {
      dirty.current.delete(id);
      for (const [hash, key] of held.current) {
        const blocked = [...dirty.current.values()].some((scope) => !scope || key.includes(scope) || key[0] === "me");
        if (!blocked) { queued.current.set(hash, key); held.current.delete(hash); }
      }
      if (!held.current.size) setPending(0);
      schedule();
    }
  }, [schedule]);
  useEffect(() => {
    const stop = subscribeFeed((event) => {
      let withheld = false;
      const cache = qc.getQueryCache().getAll();
      for (const query of cache) {
        if (!affectedBy(event, query, cache)) continue;
        const blocked = [...dirty.current.values()].some((subject) => !subject || query.queryKey.includes(subject) || query.queryKey[0] === "me");
        if (blocked) { held.current.set(query.queryHash, query.queryKey); withheld = true; }
        else queued.current.set(query.queryHash, query.queryKey);
      }
      if (withheld) setPending((n) => n + 1);
      schedule();
    });
    return () => { stop(); if (timer.current) clearTimeout(timer.current); timer.current = null; };
  }, [qc, schedule]);
  const value = useMemo(() => ({ pending, flush, setDirty }), [pending, flush, setDirty]);
  return <DraftGuardContext.Provider value={value}>{children}</DraftGuardContext.Provider>;
}
export function useDraftGuard(): DraftGuardValue { return useContext(DraftGuardContext) ?? NOOP; }
const NOOP: DraftGuardValue = { pending: 0, flush: () => {}, setDirty: () => {} };
export function useDirtyGuard(id: string, isDirty: boolean, subject?: string): void {
  const { setDirty } = useDraftGuard();
  useEffect(() => { setDirty(id, isDirty, subject); }, [id, isDirty, subject, setDirty]);
  useEffect(() => () => setDirty(id, false), [id, setDirty]);
}
